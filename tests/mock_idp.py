"""Minimal OIDC provider for tests: discovery, /authorize (auto-approves, no UI), /token with real
PKCE S256 verification, RFC 8693 token exchange (configurable to deny), and a protected /api.
Issues unsigned demo JWTs. NEVER use outside tests."""
import base64, hashlib, http.server, json, socketserver, threading, urllib.parse

def jwt(payload):
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    return enc({"alg": "RS256", "kid": "test"}) + "." + enc(payload) + ".testsig"

class MockIdP:
    def __init__(self, deny_exchange=False, api_status=200):
        self.codes, self.deny_exchange, self.api_status, self.pkce_checked = {}, deny_exchange, api_status, False
        idp = self
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def _json(self, code, obj, headers=None):
                b = json.dumps(obj).encode(); self.send_response(code)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items(): self.send_header(k, v)
                self.end_headers(); self.wfile.write(b)
            def do_GET(self):
                path, _, q = self.path.partition("?"); qs = dict(urllib.parse.parse_qsl(q))
                if path == "/.well-known/openid-configuration":
                    return self._json(200, {"issuer": idp.url, "authorization_endpoint": idp.url + "/authorize",
                                            "token_endpoint": idp.url + "/token", "jwks_uri": idp.url + "/keys"})
                if path == "/authorize":
                    code = "code-" + qs["state"][:8]
                    idp.codes[code] = (qs["code_challenge"], qs["redirect_uri"], qs["client_id"])
                    self.send_response(302)
                    self.send_header("Location", qs["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": qs["state"]}))
                    return self.end_headers()
                if path == "/api":
                    if idp.api_status == 200: return self._json(200, {"ok": True})
                    return self._json(idp.api_status, {"error": "insufficient_scope"},
                                      {"WWW-Authenticate": 'Bearer error="insufficient_scope", scope="orders.write"'})
                self._json(404, {})
            def do_POST(self):
                form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
                if form.get("grant_type") == "authorization_code":
                    chal, redir, cid = idp.codes.pop(form.get("code"), (None, None, None))
                    calc = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                    if chal is None or calc != chal or redir != form.get("redirect_uri"):
                        return self._json(400, {"error": "invalid_grant", "error_description": "PKCE verification failed"})
                    idp.pkce_checked = True
                    return self._json(200, {"access_token": jwt({"iss": idp.url, "sub": "kim@example.com", "aud": "api://default", "scp": ["openid", "orders.read"]}),
                                            "id_token": jwt({"iss": idp.url, "sub": "00u1", "aud": cid, "email": "kim@example.com"}),
                                            "token_type": "Bearer"})
                if form.get("grant_type") == "urn:ietf:params:oauth:grant-type:token-exchange":
                    if idp.deny_exchange:
                        return self._json(400, {"error": "access_denied", "error_description": "Policy evaluation failed for this request"})
                    return self._json(200, {"access_token": jwt({"iss": idp.url, "sub": "kim@example.com", "aud": form["audience"],
                                                                 "scope": "orders.read", "act": {"sub": "test-client"}}),
                                            "issued_token_type": "urn:ietf:params:oauth:token-type:access_token"})
                self._json(400, {"error": "unsupported_grant_type"})
        socketserver.TCPServer.allow_reuse_address = True
        self.srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
    def close(self): self.srv.shutdown()
