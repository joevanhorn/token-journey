"""Unit tests for the Python recorder (recorder/python/token_journey)."""
import json, os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "recorder", "python"))
from token_journey import Journey, decode_jwt, redact_jwt

JWT = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJraW0iLCJzY3AiOlsiYSJdfQ.c2ln"   # {"alg":"RS256"}.{"sub":"kim","scp":["a"]}.sig

def basic():
    return Journey("t").actor("u", "User", kind="user").actor("s", "Server", kind="resource")

class Recorder(unittest.TestCase):
    def test_decode_and_redact(self):
        self.assertEqual(decode_jwt(JWT)["payload"]["sub"], "kim")
        r = redact_jwt(JWT)
        self.assertTrue(r.endswith(".REDACTED-SIGNATURE") and decode_jwt(r)["payload"]["sub"] == "kim")
        self.assertIsNone(decode_jwt("not-a-jwt"))
        self.assertTrue(redact_jwt("opaque-token-value-123").endswith("[opaque token redacted]"))

    def test_token_redacted_by_default_and_opt_out(self):
        d = basic().message("u", "s", "go").token("A", raw=JWT).token("B", raw=JWT, redact=False).to_dict()
        self.assertTrue(d["tokens"][0]["raw"].endswith("REDACTED-SIGNATURE"))
        self.assertEqual(d["tokens"][1]["raw"], JWT)

    def test_errors_are_precise(self):
        j = basic()
        with self.assertRaisesRegex(ValueError, "not a declared actor"): j.message("u", "nope", "x")
        with self.assertRaisesRegex(ValueError, "two different actors"): j.message("u", "u", "x")
        with self.assertRaisesRegex(ValueError, "tone must be"): j.event("u", "x", tone="green")
        with self.assertRaisesRegex(ValueError, "declared twice"): j.actor("u", "again")
        with self.assertRaisesRegex(ValueError, "kind must be"): j.actor("z", "Z", kind="robot")
        with self.assertRaisesRegex(ValueError, "outcome status"): j.outcome("maybe")
        with self.assertRaisesRegex(ValueError, "pass claims"): j.token("t", raw="opaque")
        with self.assertRaisesRegex(ValueError, "http"): j.link("x", "javascript:alert(1)")
        with self.assertRaisesRegex(ValueError, "at least one step"): basic().to_dict()

    def test_response_flag_and_story(self):
        d = basic().message("s", "u", "200", response=True, story=Journey.story("T", what="w")).to_dict()
        self.assertTrue(d["steps"][0]["return"])
        self.assertEqual(d["steps"][0]["story"], {"title": "T", "what": "w"})

    def test_output_is_json_and_isolated(self):
        j = basic().message("u", "s", "go")
        d = j.to_dict(); d["steps"].clear()
        self.assertEqual(len(j.to_dict()["steps"]), 1)
        self.assertEqual(json.loads(j.to_json())["version"], 1)

if __name__ == "__main__":
    unittest.main()
