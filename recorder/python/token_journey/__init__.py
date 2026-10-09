"""token_journey: record an auth flow as a Token Journey trace.

Use this from the code that actually performs an OAuth/OIDC flow (a backend, a test harness,
a gateway) to describe what happened, then hand the JSON to the viewer
(viewer/token-journey.js). Standard library only.

    from token_journey import Journey

    j = Journey("Agent reads a ticket for Kim", subtitle="RFC 8693 token exchange")
    j.actor("user", "Kim (user)", kind="user")
    j.actor("agent", "Support agent", kind="agent")
    j.actor("idp", "Authorization server", short="AS", kind="idp")
    j.actor("api", "Ticket API", short="API", kind="resource")

    j.message("user", "agent", "ask for ticket 42")
    j.message("agent", "idp", "token exchange", detail="grant_type=token-exchange",
              tone="info", token="user token + agent creds",
              story=j.story("The agent asked for a token on Kim's behalf",
                            what="...", why="...", matters="..."))
    j.event("idp", "mints delegated token", tone="ok", token="act=agent")
    ...
    j.allow("Ticket returned", caption="delegated token minted, API returned 200")
    j.token("Delegated access token", raw=access_token)   # signature redacted by default
    j.save("journey.json")

Design notes
  - The builder validates as you go (unknown actor ids, bad tones) and raises ValueError with
    a precise message, so mistakes surface where you make them, not in the browser.
  - Tokens are REDACTED by default: the signature segment of a JWT is replaced, so a recorded
    trace can be shared or committed without handing anyone a replayable token. Claims stay
    readable, which is all the viewer needs. Pass redact=False only for local debugging.
  - Nothing here talks to the network or verifies tokens. Verification belongs in your code.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterable, List, Optional

__all__ = ["Journey", "decode_jwt", "redact_jwt", "TONES", "KINDS"]
__version__ = "1.0.0"

TONES = ("neutral", "info", "ok", "deny")
KINDS = ("user", "agent", "gateway", "idp", "resource", "service")
STATUSES = ("allow", "deny", "refused")
REDACTED_SIGNATURE = "REDACTED-SIGNATURE"


def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def decode_jwt(raw: str) -> Optional[Dict[str, Any]]:
    """Decode a compact JWT's header and payload WITHOUT verifying it. Returns None if not a JWT."""
    try:
        h, p = raw.split(".")[:2]
        return {"header": json.loads(_b64url_decode(h)), "payload": json.loads(_b64url_decode(p))}
    except (ValueError, AttributeError):
        return None


def redact_jwt(raw: str) -> str:
    """Replace a JWT's signature so the token can't be replayed. Header and claims stay intact.

    Non-JWT (opaque) tokens are reduced to a short prefix, since they carry no readable claims."""
    parts = raw.split(".") if isinstance(raw, str) else []
    if len(parts) == 3 and decode_jwt(raw) is not None:
        return f"{parts[0]}.{parts[1]}.{REDACTED_SIGNATURE}"
    return (raw[:6] + "...[opaque token redacted]") if isinstance(raw, str) else raw


class Journey:
    """Fluent builder for a version-1 Token Journey trace."""

    def __init__(self, title: str, subtitle: Optional[str] = None, tags: Optional[Iterable[str]] = None):
        self._d: Dict[str, Any] = {"version": 1, "title": title, "actors": [], "steps": []}
        if subtitle:
            self._d["subtitle"] = subtitle
        if tags:
            self._d["tags"] = list(tags)
        self._ids: set = set()

    # ── actors ────────────────────────────────────────────────────────
    def actor(self, id: str, label: str, *, short: Optional[str] = None, kind: Optional[str] = None,
              sublabel: Optional[str] = None, color: Optional[str] = None,
              description: Optional[str] = None) -> "Journey":
        """Declare a participant. Order of declaration = left-to-right lane order."""
        if not id:
            raise ValueError("actor id is required")
        if id in self._ids:
            raise ValueError(f"actor {id!r} declared twice")
        if kind is not None and kind not in KINDS:
            raise ValueError(f"actor {id!r}: kind must be one of {KINDS}")
        a = {"id": id, "label": label}
        for k, v in (("short", short), ("kind", kind), ("sublabel", sublabel), ("color", color), ("description", description)):
            if v is not None:
                a[k] = v
        self._d["actors"].append(a)
        self._ids.add(id)
        return self

    # ── steps ─────────────────────────────────────────────────────────
    @staticmethod
    def story(title: str, what: Optional[str] = None, why: Optional[str] = None, matters: Optional[str] = None,
              status: Optional[str] = None, actor: Optional[str] = None) -> Dict[str, Any]:
        """Narrative card for a step: what happened, why it happened, why it matters."""
        s = {"title": title}
        for k, v in (("what", what), ("why", why), ("matters", matters), ("status", status), ("actor", actor)):
            if v is not None:
                s[k] = v
        if status is not None and status not in ("done", "deny", "skip"):
            raise ValueError("story status must be done, deny or skip")
        return s

    def _check_actor(self, aid: str, field: str) -> None:
        if aid not in self._ids:
            raise ValueError(f"step {field} {aid!r} is not a declared actor (declared: {sorted(self._ids)})")

    def _step(self, base: Dict[str, Any], label: str, tone: Optional[str], extra: Dict[str, Any]) -> "Journey":
        if not label:
            raise ValueError("step label is required")
        if tone is not None and tone not in TONES:
            raise ValueError(f"tone must be one of {TONES}")
        base["label"] = label
        if tone is not None:
            base["tone"] = tone
        for k, v in extra.items():
            if v is not None and v is not False:
                base[k] = v
        self._d["steps"].append(base)
        return self

    def message(self, frm: str, to: str, label: str, *, detail: Optional[str] = None, tone: Optional[str] = None,
                token: Optional[str] = None, response: bool = False, note: Optional[str] = None,
                story: Optional[Dict[str, Any]] = None) -> "Journey":
        """An arrow from one actor to another (a request, or a response with response=True)."""
        self._check_actor(frm, "from")
        self._check_actor(to, "to")
        if frm == to:
            raise ValueError("a message needs two different actors; use event() for something at one actor")
        return self._step({"type": "message", "from": frm, "to": to}, label, tone,
                          {"detail": detail, "token": token, "return": response, "note": note, "story": story})

    def event(self, at: str, label: str, *, tone: Optional[str] = None, token: Optional[str] = None,
              symbol: Optional[str] = None, note: Optional[str] = None,
              story: Optional[Dict[str, Any]] = None) -> "Journey":
        """Something that happens at one actor: a token minted, a policy evaluated, a check failing."""
        self._check_actor(at, "at")
        return self._step({"type": "event", "at": at}, label, tone,
                          {"token": token, "symbol": symbol, "note": note, "story": story})

    # ── outcome, tokens, links ────────────────────────────────────────
    def outcome(self, status: str, headline: Optional[str] = None, detail: Optional[str] = None,
                caption: Optional[str] = None) -> "Journey":
        if status not in STATUSES:
            raise ValueError(f"outcome status must be one of {STATUSES}")
        o = {"status": status}
        for k, v in (("headline", headline), ("detail", detail), ("caption", caption)):
            if v is not None:
                o[k] = v
        self._d["outcome"] = o
        return self

    def allow(self, detail: Optional[str] = None, **kw: Any) -> "Journey":
        return self.outcome("allow", detail=detail, **kw)

    def deny(self, detail: Optional[str] = None, **kw: Any) -> "Journey":
        """No token was issued (the authorization server said no)."""
        return self.outcome("deny", detail=detail, **kw)

    def refused(self, detail: Optional[str] = None, **kw: Any) -> "Journey":
        """A token was issued, but the resource rejected the call (e.g. 403 insufficient_scope)."""
        return self.outcome("refused", detail=detail, **kw)

    def token(self, label: str, raw: Optional[str] = None, *, claims: Optional[Dict[str, Any]] = None,
              show: Optional[List[str]] = None, missing: Optional[List[str]] = None,
              note: Optional[str] = None, redact: bool = True) -> "Journey":
        """Attach a token card. For JWTs pass raw (decoded in the browser); for opaque tokens pass claims
        (e.g. from your introspection call). The JWT signature is redacted unless redact=False."""
        if raw is None and claims is None:
            raise ValueError("token needs raw or claims")
        t: Dict[str, Any] = {"label": label}
        if raw is not None:
            t["raw"] = redact_jwt(raw) if redact else raw
            if claims is None and decode_jwt(raw) is None:
                raise ValueError("raw is not a JWT; pass claims= for opaque tokens")
        for k, v in (("claims", claims), ("show", show), ("missing", missing), ("note", note)):
            if v is not None:
                t[k] = v
        self._d.setdefault("tokens", []).append(t)
        return self

    def link(self, label: str, href: str) -> "Journey":
        if not href.startswith(("http://", "https://")):
            raise ValueError("link href must be http(s)")
        self._d.setdefault("links", []).append({"label": label, "href": href})
        return self

    # ── output ────────────────────────────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        if len(self._d["actors"]) < 2:
            raise ValueError("a journey needs at least two actors")
        if not self._d["steps"]:
            raise ValueError("a journey needs at least one step")
        return json.loads(json.dumps(self._d))   # defensive deep copy

    def to_json(self, indent: Optional[int] = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json() + "\n")
        return path
