"""End-to-end: the live recorder runs a real auth-code + PKCE (+ token exchange + API call) flow
against the mock IdP and produces a valid journey with the right outcome."""
import importlib.util, json, os, socket, subprocess, sys, threading, time, unittest, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from mock_idp import MockIdP

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None

def run_flow(**idp_kw):
    """Start mock IdP + live app, drive the browser redirects by hand, return (journey, idp)."""
    idp = MockIdP(**idp_kw); port = free_port()
    env = dict(os.environ, TJ_ISSUER=idp.url, TJ_CLIENT_ID="test-client", TJ_PORT=str(port),
               TJ_EXCHANGE_AUDIENCE="api://orders", TJ_API_URL=idp.url + "/api")
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "examples", "live-oidc", "app.py")], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            try: urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1); break
            except Exception: time.sleep(0.1)
        op = urllib.request.build_opener(NoRedirect)
        def loc(url):
            try: op.open(url); return None
            except urllib.error.HTTPError as e: return e.headers.get("Location")
        auth = loc(f"http://127.0.0.1:{port}/login")            # app -> IdP authorize
        cb = loc(auth)                                          # IdP -> app callback (auto-approve)
        cb = cb.replace("localhost", "127.0.0.1")
        loc(cb)                                                 # app redeems code, exchanges, calls API
        j = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/journey.json"))
        return j, idp
    finally:
        proc.terminate(); proc.wait(); idp.close()

def node_validate(j):
    js = "const T=require(%r);const e=T.validate(JSON.parse(require('fs').readFileSync(0,'utf8')));console.log(JSON.stringify(e))" % os.path.join(ROOT, "viewer", "token-journey.js")
    out = subprocess.run(["node", "-e", js], input=json.dumps(j), capture_output=True, text=True, check=True)
    return json.loads(out.stdout)

class LiveOIDC(unittest.TestCase):
    def test_success_path(self):
        j, idp = run_flow()
        self.assertTrue(idp.pkce_checked, "mock IdP never verified a PKCE verifier")
        self.assertEqual(j["outcome"]["status"], "allow")
        self.assertEqual(node_validate(j), [])
        labels = [s["label"] for s in j["steps"]]
        for want in ("discovery", "/authorize", "/token", "token exchange", "mints exchanged token"):
            self.assertIn(want, labels)
        raws = [t["raw"] for t in j["tokens"] if "raw" in t]
        self.assertTrue(raws and all(r.endswith(".REDACTED-SIGNATURE") for r in raws), "signatures must be redacted")
        self.assertIn("Exchanged token", [t["label"] for t in j["tokens"]])

    def test_exchange_denied(self):
        j, _ = run_flow(deny_exchange=True)
        self.assertEqual(j["outcome"]["status"], "deny")
        self.assertIn("Policy evaluation failed", j["outcome"]["detail"])
        self.assertEqual(node_validate(j), [])

    def test_api_refused(self):
        j, _ = run_flow(api_status=403)
        self.assertEqual(j["outcome"]["status"], "refused")
        self.assertIn("insufficient_scope", j["outcome"]["detail"])

if __name__ == "__main__":
    unittest.main()
