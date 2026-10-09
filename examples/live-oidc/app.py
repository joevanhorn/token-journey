#!/usr/bin/env python3
"""Record a REAL OpenID Connect flow as a Token Journey and view it in the browser.

Runs the authorization code flow with PKCE against any standards-compliant provider (Okta, Auth0,
Microsoft Entra ID, Keycloak, Ping, ...), optionally exchanges the result for a second token
(RFC 8693) and calls an API with it, recording each step as it actually happens. Errors become a
"deny" journey with the provider's verbatim error, which is often the most useful case.

Standard library only. Configure with environment variables (or a .env file next to this script):

  TJ_ISSUER          required  e.g. https://dev-123.okta.com/oauth2/default
  TJ_CLIENT_ID       required  an OIDC client that allows redirect URI http://localhost:8765/callback
  TJ_CLIENT_SECRET   optional  omit for a public client (PKCE only)
  TJ_SCOPES          optional  default "openid profile email"
  TJ_EXCHANGE_AUDIENCE  optional  if set, do an RFC 8693 token exchange for this audience after sign-in
  TJ_EXCHANGE_SCOPE     optional  scope to request in the exchange
  TJ_API_URL         optional  if set, GET this URL with the final access token and record the result
  TJ_PORT            optional  default 8765

Then:  python3 examples/live-oidc/app.py   and open http://localhost:8765

Security: this is a local learning/debugging tool. It binds to 127.0.0.1 only, keeps tokens in
memory, and the journey it renders has JWT signatures redacted (token_journey's default), so a
saved journey.json can be shared without exposing a usable token. Don't run it on a shared host.
"""
import base64
import hashlib
import html
import http.server
import json
import os
import secrets
import socketserver
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "recorder", "python"))
from token_journey import Journey, decode_jwt  # noqa: E402


def load_env_file(path):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env_file(os.path.join(HERE, ".env"))
ISSUER = os.environ.get("TJ_ISSUER", "").rstrip("/")
CLIENT_ID = os.environ.get("TJ_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TJ_CLIENT_SECRET", "")
SCOPES = os.environ.get("TJ_SCOPES", "openid profile email")
EXCHANGE_AUDIENCE = os.environ.get("TJ_EXCHANGE_AUDIENCE", "")
EXCHANGE_SCOPE = os.environ.get("TJ_EXCHANGE_SCOPE", "")
API_URL = os.environ.get("TJ_API_URL", "")
PORT = int(os.environ.get("TJ_PORT", "8765"))
REDIRECT_URI = f"http://localhost:{PORT}/callback"

STATE = {"pending": {}, "journey": None}


# ── HTTP helpers that never raise on HTTP errors: an error response IS data for the journey ───
def http_json(url, data=None, headers=None):
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=dict(headers or {}, Accept="application/json"))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": f"HTTP {e.code}", "error_description": raw[:300]}
    except urllib.error.URLError as e:
        return 0, {"error": "network_error", "error_description": str(e.reason)}


def client_auth(data):
    """client_secret_post if a secret is configured; otherwise a public client (PKCE protects the code)."""
    data = dict(data, client_id=CLIENT_ID)
    if CLIENT_SECRET:
        data["client_secret"] = CLIENT_SECRET
    return data


def err_text(body):
    return (body.get("error", "error") + (": " + body["error_description"] if body.get("error_description") else ""))


def scopes_of(tok):
    p = (decode_jwt(tok) or {}).get("payload", {})
    s = p.get("scp") or p.get("scope") or []
    return s if isinstance(s, list) else s.split()


# ── the flow, recorded ──────────────────────────────────────────────────────────────────
def new_journey():
    host = urllib.parse.urlparse(ISSUER).hostname or "issuer"
    j = Journey("Live sign-in recorded from " + host, subtitle="OIDC authorization code + PKCE" +
                (" → RFC 8693 token exchange" if EXCHANGE_AUDIENCE else ""), tags=["live", "OIDC", "PKCE"])
    j.actor("browser", "Your browser", short="BROWSER", kind="user")
    j.actor("app", "This app (OIDC client)", short="APP", kind="service", sublabel="localhost")
    j.actor("idp", "Identity provider", short="IDP", kind="idp", sublabel=host)
    if API_URL:
        j.actor("api", "API", short="API", kind="resource", sublabel=urllib.parse.urlparse(API_URL).hostname)
    return j


def start_login():
    status, meta = http_json(ISSUER + "/.well-known/openid-configuration")
    j = new_journey()
    j.message("app", "idp", "discovery", detail="/.well-known/openid-configuration", tone="info" if status == 200 else "deny",
              story=Journey.story("The app looked up the provider's endpoints",
                                  what="It fetched the OpenID discovery document for " + ISSUER + ".",
                                  why="Discovery tells a client where to authorize, where to get tokens, and which keys sign them.",
                                  matters="Nothing is hardcoded, so the same client works against any compliant provider."))
    if status != 200:
        j.deny("Discovery failed: " + err_text(meta), caption="no discovery document · flow could not start")
        STATE["journey"] = j
        return None
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    STATE["pending"][state] = {"verifier": verifier, "meta": meta, "journey": j}
    params = {"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI, "scope": SCOPES,
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
              "nonce": secrets.token_urlsafe(12)}
    j.message("browser", "idp", "/authorize", detail="code_challenge=S256 · scope=" + SCOPES, tone="info",
              story=Journey.story("You were sent to sign in", what="The app generated a PKCE verifier, kept it, and redirected you with only its hash.",
                                  why="The provider authenticates you; the app never sees your password.",
                                  matters="PKCE binds the code to this app instance, so a stolen code is useless."))
    return meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(params)


def finish_login(query):
    q = dict(urllib.parse.parse_qsl(query))
    pending = STATE["pending"].pop(q.get("state", ""), None)
    if pending is None:
        j = new_journey()
        j.event("app", "unknown state", tone="deny")
        j.deny("The callback's state didn't match a login this app started (possible CSRF, or the app restarted).")
        STATE["journey"] = j
        return
    j, meta = pending["journey"], pending["meta"]
    if "error" in q:
        j.event("idp", q["error"], tone="deny", token="no code",
                story=Journey.story("The provider refused the sign-in", status="deny", what=err_text(q),
                                    why="The provider's sign-on or app policy didn't allow this request.",
                                    matters="Read the error verbatim: it names the policy decision, not a bug in the client."))
        j.deny(err_text(q), caption="authorization refused · no code · no token")
        STATE["journey"] = j
        return
    j.event("idp", "authenticated", tone="info", token="session")
    j.message("idp", "app", "redirect ?code=", tone="info", token="auth code", response=True)

    status, tok = http_json(meta["token_endpoint"], client_auth({
        "grant_type": "authorization_code", "code": q.get("code", ""), "redirect_uri": REDIRECT_URI,
        "code_verifier": pending["verifier"]}))
    j.message("app", "idp", "/token", detail="code + code_verifier", tone="info",
              story=Journey.story("The app redeemed the code", what="It sent the code and the original PKCE verifier to the token endpoint.",
                                  why="The provider recomputes the hash and compares it with the challenge from the redirect.",
                                  matters="Only the client that started the flow can finish it."))
    if status != 200 or "access_token" not in tok:
        j.event("idp", "token request rejected", tone="deny", token="DENIED",
                story=Journey.story("The token request was rejected", status="deny", what=err_text(tok),
                                    why="The provider checks the client, the redirect URI, the verifier and policy before minting.",
                                    matters="A rejected token request means no token exists, so nothing downstream can be called."))
        j.deny(err_text(tok), caption="code not redeemed · no token")
        STATE["journey"] = j
        return
    access = tok["access_token"]
    j.event("idp", "mints tokens", tone="ok", token="tokens",
            story=Journey.story("The provider issued tokens", what="Granted scopes: " + (" ".join(scopes_of(access)) or tok.get("scope", "(opaque token)")) + ".",
                                why="Policy matched this user and client.",
                                matters="The access token carries what this app may do for you, nothing more."))
    j.message("idp", "app", "id_token + access_token", tone="ok", response=True)
    if tok.get("id_token"):
        j.token("ID token", raw=tok["id_token"], show=["sub", "email", "aud", "amr", "exp"])
    if decode_jwt(access):
        j.token("Access token", raw=access)
    else:
        j.token("Access token", claims={"note": "opaque token (not a JWT); introspect it to see claims"}, show=["note"])

    if EXCHANGE_AUDIENCE:
        data = {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange", "subject_token": access,
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token", "audience": EXCHANGE_AUDIENCE}
        if EXCHANGE_SCOPE:
            data["scope"] = EXCHANGE_SCOPE
        status, ex = http_json(meta["token_endpoint"], client_auth(data))
        j.message("app", "idp", "token exchange", detail="audience=" + EXCHANGE_AUDIENCE, tone="info", token="subject token",
                  story=Journey.story("The app exchanged your token for another audience",
                                      what="It presented your access token as subject_token and asked for a token for " + EXCHANGE_AUDIENCE + ".",
                                      why="Tokens are minted per audience; a downstream service needs its own.",
                                      matters="Delegation is a policy-checked exchange, not token forwarding."))
        if status != 200 or "access_token" not in ex:
            j.event("idp", "exchange denied", tone="deny", token="DENIED",
                    story=Journey.story("The exchange was refused", status="deny", what=err_text(ex),
                                        why="The provider didn't allow this client to act for you at that audience.",
                                        matters="This is where delegation is governed."))
            j.deny(err_text(ex), caption="signed in · exchange refused · no downstream token")
            STATE["journey"] = j
            return
        access = ex["access_token"]
        j.event("idp", "mints exchanged token", tone="ok", token="exchanged")
        if decode_jwt(access):
            j.token("Exchanged token", raw=access, show=["sub", "act", "aud", "scope", "exp"])

    if API_URL:
        req = urllib.request.Request(API_URL, headers={"Authorization": "Bearer " + access})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                code, why = r.status, ""
        except urllib.error.HTTPError as e:
            code, why = e.code, e.headers.get("WWW-Authenticate", "") or e.reason
        except urllib.error.URLError as e:
            code, why = 0, str(e.reason)
        ok = 200 <= code < 300
        j.message("app", "api", "GET " + urllib.parse.urlparse(API_URL).path, detail="Bearer token", tone="ok" if ok else "info", token="access token")
        j.event("api", f"{code}" if code else "unreachable", tone="ok" if ok else "deny", token=f"{code}" if code else "error",
                story=Journey.story("The API answered" if ok else "The API refused the call", status="done" if ok else "deny",
                                    what=f"HTTP {code}" + (f": {why}" if why else ""),
                                    why="The API validates the token's signature, audience, expiry and scope.",
                                    matters="A token that's valid but too narrow is refused at the resource."))
        if ok:
            j.allow("Signed in, " + ("exchanged, " if EXCHANGE_AUDIENCE else "") + "and the API accepted the token.", caption=f"token issued · API returned {code}")
        else:
            j.refused(f"A token was issued, but the API returned {code}." + (f" {why}" if why else ""), caption=f"token issued · API refused ({code})")
    else:
        j.allow("Signed in" + (" and exchanged" if EXCHANGE_AUDIENCE else "") + "; tokens issued.", caption="code + verifier redeemed · tokens issued")
    STATE["journey"] = j


# ── tiny web server ─────────────────────────────────────────────────────────────────────
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Live token journey</title>
<link rel="stylesheet" href="/viewer/token-journey.css">
<style>body{margin:0;padding:24px;background:#0a0d15;color:#e8ecf6;font:14px system-ui,sans-serif}
@media (prefers-color-scheme:light){body{background:#f1ece0;color:#262119}} .w{max-width:980px;margin:0 auto}
a.b{display:inline-block;margin:0 10px 16px 0;padding:8px 14px;border-radius:8px;border:1px solid #edb24a;color:inherit;text-decoration:none}</style>
</head><body><div class="w"><a class="b" href="/login">Sign in and record a journey</a>
<a class="b" href="/journey.json" download="journey.json">Download journey.json</a>
<p>%s</p><div id="v"></div></div>
<script src="/viewer/token-journey.js"></script>
<script>fetch('/journey.json').then(r=>r.ok?r.json():null).then(j=>{ if(j) TokenJourney.render(document.getElementById('v'), j); });</script>
</body></html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=REPO, **kw)

    def log_message(self, fmt, *args):  # quieter console
        pass

    def _send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            msg = ("Configured for <b>%s</b>." % html.escape(ISSUER)) if ISSUER else "Set TJ_ISSUER and TJ_CLIENT_ID first."
            return self._send(200, PAGE % msg)
        if path == "/login":
            url = start_login()
            return self._send(302, "", headers={"Location": url or "/"})
        if path == "/callback":
            finish_login(query)
            return self._send(302, "", headers={"Location": "/"})
        if path == "/journey.json":
            j = STATE["journey"]
            return self._send(200, j.to_json(), "application/json") if j else self._send(404, "{}", "application/json")
        if path.startswith("/viewer/"):
            return super().do_GET()
        return self._send(404, "not found", "text/plain")


def main():
    if not ISSUER or not CLIENT_ID:
        sys.exit("Set TJ_ISSUER and TJ_CLIENT_ID (see the docstring at the top of this file).")
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as srv:
        print(f"Token Journey live recorder: http://localhost:{PORT}  (redirect URI: {REDIRECT_URI})")
        srv.serve_forever()


if __name__ == "__main__":
    main()
