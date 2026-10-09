#!/usr/bin/env python3
"""Generate the example journeys in examples/journeys/ with the Python recorder.

Every example here is ILLUSTRATIVE: the tokens are synthetic JWTs built below (no real issuer,
no real signature), and all hostnames are example.com. They show the shape of each flow, so you
can compare a real recording against them.

Run:  python3 examples/build_examples.py
"""
import base64
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "recorder", "python"))
from token_journey import Journey  # noqa: E402

OUT = os.path.join(HERE, "journeys")
NOW = 1767225600  # fixed timestamp so regenerated files are byte-stable


def fake_jwt(payload, kid="example-key-1"):
    """A syntactically valid, deliberately unsigned JWT for demos. Never accepted by anything."""
    enc = lambda o: base64.urlsafe_b64encode(json.dumps(o, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256', 'kid': kid, 'typ': 'JWT'})}.{enc(payload)}.not-a-real-signature"


S = Journey.story
ISS = "https://idp.example.com/oauth2/default"


# ── 1-3. Agentic: user -> agent -> gateway -> IdP (ID-JAG two-hop) -> resource ─────────────────
def agentic(variant):
    """Okta Cross App Access (XAA): an AI agent acts for a user through an MCP gateway.

    variant: 'allow' (user is entitled), 'deny' (policy matches no rule: no token),
             'refused' (token minted, but the agent's connection is limited below the user)."""
    who = {"allow": "Kim", "deny": "Frank", "refused": "Susan"}[variant]
    tool = "tickets.update" if variant == "refused" else "tickets.read"
    titles = {"allow": f"Agent reads a ticket for {who}",
              "deny": f"Agent tries to read a ticket for {who}",
              "refused": f"Agent tries to update a ticket for {who}"}
    j = Journey(titles[variant], subtitle="Cross App Access: ID-JAG token exchange through an MCP gateway",
                tags=["agentic", "XAA / ID-JAG", "RFC 8693", "RFC 7523"])
    j.actor("user", f"{who} (user)", short="USER", kind="user")
    j.actor("agent", "AI agent", short="AGENT", kind="agent", description="An MCP client, e.g. a coding assistant")
    j.actor("gw", "MCP gateway", short="GATEWAY", kind="gateway", description="Brokers tokens for the agent")
    j.actor("idp", "Identity provider", short="IDP", kind="idp", sublabel="org + resource AS")
    j.actor("api", "Ticket API", short="API", kind="resource", sublabel="MCP server")

    j.message("user", "agent", "ask agent", detail=f'"{tool.split(".")[1]} ticket 42"',
              story=S("You asked the agent", what=f"{who} asked the agent to work with ticket 42.",
                      why=f"The agent has no rights of its own here. It acts strictly on {who}'s behalf.",
                      matters="Every agent action traces back to a real person and inherits that person's limits."))
    j.message("agent", "gw", "tools/call", detail=tool, tone="info")
    j.message("gw", "idp", "ID-JAG request", detail="grant=token-exchange", tone="info", token="user ⊕ agent",
              story=S("The gateway brokered the request to the identity provider",
                      what=f"The gateway presented {who}'s identity and the agent's own credentials, asking for an Identity Assertion JWT (ID-JAG).",
                      why="An agent can't mint its own access. Only the identity provider issues tokens, and only after evaluating policy.",
                      matters="The exchange is the checkpoint: every agent action passes through policy before it can touch a resource."))
    j.event("idp", "mints ID-JAG", tone="info", token="ID-JAG")
    j.message("gw", "idp", "token exchange", detail="grant=jwt-bearer", tone="info")

    if variant == "deny":
        j.event("idp", "no matching rule", tone="deny", token="DENIED",
                story=S("The identity provider refused: no token", status="deny",
                        what=f"No access-policy rule for the ticket API matched {who}, so nothing was minted.",
                        why=f"{who} isn't entitled to tickets, and the agent only ever borrows {who}'s rights.",
                        matters="The agent can't do what the user can't. The denial happens at the identity provider, before the API is ever reached."))
        j.message("idp", "gw", "no token", tone="deny", response=True)
        j.event("api", "never reached", tone="neutral", symbol="◦",
                story=S("The ticket API was never called", status="skip",
                        what="With no token, the call stopped at the identity provider.",
                        why="There was nothing to present to the API.",
                        matters="The resource is not the first line of defense. Policy is."))
        j.deny(f"{who} matched no rule at the exchange, so no token was issued. The agent can't do what the user can't.",
               headline="✕ BLOCKED: NO TOKEN", caption="no rule matched at the exchange · no token · API never reached")
        return j

    scopes = ["tickets.read"] if variant == "allow" else ["tickets.read"]
    j.event("idp", "narrows scopes" if variant == "refused" else "mints token", tone="ok",
            token="scoped token", story=S(
                "The identity provider minted a narrow token" if variant == "refused" else "The identity provider minted a scoped token",
                what=(f"A token for the ticket API was issued, but the agent's connection is limited below {who}, so it carries only tickets.read."
                      if variant == "refused" else f"Policy matched {who}, and a token scoped to tickets.read was issued for the ticket API."),
                why=("The token is the intersection of what the user may do and what this agent may do."),
                matters=("Even though Susan may update tickets, this agent may not. The limit is in the token itself."
                         if variant == "refused" else "The agent borrows the user's keys, bounded to the user's rights. It can never exceed them.")))
    j.message("gw", "api", f"call {tool}", detail="+ access token", tone="ok" if variant == "allow" else "info", token="access token")
    if variant == "allow":
        j.event("api", "200 OK", tone="ok", token="200 OK",
                story=S("The ticket API honored the call", what="The API validated the token and returned ticket 42.",
                        why="The token carried exactly the scope this call required, and nothing more.",
                        matters="Access was proven for this one call, not assumed from a standing login."))
        j.allow(f"Policy authorized {who} and minted a token for the ticket API, bounded to what {who} may do.",
                headline="✓ ALLOWED: TOKEN ISSUED", caption="scoped token minted · API returned 200")
    else:
        j.event("api", "403 insufficient_scope", tone="deny", token="403",
                story=S("The ticket API refused the call (403)", status="deny",
                        what="The API checked the token, found no tickets.write scope, and refused.",
                        why="Resources enforce scope on every call.",
                        matters="The agent limit is not a policy note. It is a machine-checked refusal at the resource."))
        j.message("api", "gw", "refused", tone="deny", response=True)
        j.refused("A token was minted, but the agent's connection is limited below Susan, so it lacked tickets.write and the API refused.",
                  headline="✕ REFUSED: AGENT LIMITED", caption="token minted but narrower than the user · API refused (403)")

    claims = {"iss": "https://idp.example.com/oauth2/tickets-as", "sub": f"{who.lower()}@example.com",
              "aud": "api://tickets", "cid": "ai-agent-7f3a", "scp": scopes,
              "act": {"sub": "ai-agent-7f3a"}, "iat": NOW, "exp": NOW + 3600}
    j.token("Delegated access token", raw=fake_jwt(claims),
            missing=["tickets.write"] if variant == "refused" else None,
            show=["sub", "act", "aud", "iss", "scope", "exp"],
            note="sub is the user; act.sub is the agent acting on their behalf (RFC 8693 actor claim).")
    return j


# ── 4. OIDC authorization code + PKCE (a person signing in to a web app) ─────────────────────
def auth_code_pkce():
    j = Journey("Sign in to a web app", subtitle="OpenID Connect authorization code flow with PKCE",
                tags=["OIDC", "RFC 7636 PKCE"])
    j.actor("user", "User's browser", short="BROWSER", kind="user")
    j.actor("app", "Web app (client)", short="APP", kind="service")
    j.actor("idp", "Identity provider", short="IDP", kind="idp", sublabel="idp.example.com")
    j.actor("api", "API", short="API", kind="resource")
    j.message("user", "app", "click Sign in",
              story=S("The app sent you to sign in", what="The app generated a PKCE code_verifier, kept it, and redirected you to the identity provider with its hash (code_challenge).",
                      why="The app never sees your password. Only the identity provider authenticates you.",
                      matters="PKCE binds the eventual code to this app instance, so an intercepted code is useless."))
    j.message("app", "idp", "/authorize", detail="code_challenge=S256(...)", tone="info")
    j.event("idp", "authenticates user", tone="info", token="session",
            story=S("You signed in at the identity provider", what="You entered credentials (and MFA, if required) on the identity provider's page.",
                    why="Authentication happens in one trusted place, under its sign-on policy.",
                    matters="Every app gets the same strong sign-in without handling secrets itself."))
    j.message("idp", "app", "redirect ?code=", tone="info", token="auth code", response=True)
    j.message("app", "idp", "/token", detail="code + code_verifier", tone="info",
              story=S("The app redeemed the code", what="The app sent the code plus the original code_verifier to the token endpoint.",
                      why="The identity provider checks the verifier against the challenge from step one.",
                      matters="Only the app that started the flow can finish it."))
    j.event("idp", "mints tokens", tone="ok", token="ID + access token")
    j.message("idp", "app", "id_token, access_token", tone="ok", response=True)
    j.message("app", "api", "GET /me", detail="Bearer access_token", tone="ok", token="access token",
              story=S("The app called the API with your token", what="The API validated the access token and returned your profile.",
                      why="The token says who you are, which app asked, and what it may do.",
                      matters="The API trusts the identity provider's signature, not the app's say-so."))
    j.event("api", "200 OK", tone="ok", token="200 OK")
    j.allow("The user authenticated at the identity provider and the app received tokens bound to this sign-in.",
            caption="code + verifier redeemed · tokens issued · API returned 200")
    j.token("ID token", raw=fake_jwt({"iss": ISS, "sub": "00u-kim", "aud": "web-app-client", "email": "kim@example.com",
                                     "amr": ["pwd", "mfa"], "iat": NOW, "exp": NOW + 3600}),
            show=["sub", "email", "aud", "amr", "exp"], note="The ID token is for the app: proof of who signed in.")
    j.token("Access token", raw=fake_jwt({"iss": ISS, "sub": "kim@example.com", "aud": "api://default", "cid": "web-app-client",
                                         "scp": ["openid", "profile", "orders.read"], "iat": NOW, "exp": NOW + 3600}),
            note="The access token is for the API: what the app may do on the user's behalf.")
    return j


# ── 5. RFC 8693 token exchange (service delegation, with the act claim) ──────────────────────
def token_exchange():
    j = Journey("Orders service calls Billing for the user", subtitle="OAuth 2.0 Token Exchange (RFC 8693) with delegation",
                tags=["RFC 8693", "delegation", "act claim"])
    j.actor("user", "User", short="USER", kind="user")
    j.actor("orders", "Orders service", short="ORDERS", kind="service")
    j.actor("idp", "Authorization server", short="AS", kind="idp")
    j.actor("billing", "Billing API", short="BILLING", kind="resource")
    j.message("user", "orders", "POST /checkout", detail="Bearer user token (aud=orders)", tone="info", token="user token",
              story=S("You called the Orders service", what="Your token is scoped to the Orders service (aud=orders).",
                      why="Each token is minted for one audience.",
                      matters="Orders can't simply forward your token to Billing; Billing would reject the wrong audience."))
    j.message("orders", "idp", "token exchange", detail="subject_token=user, actor_token=orders", tone="info",
              token="subject + actor",
              story=S("Orders exchanged your token for one Billing will accept", what="Orders presented your token as subject_token and its own credentials as actor_token.",
                      why="The authorization server decides if Orders may act for you at Billing.",
                      matters="Delegation is explicit and policy-checked, not implicit token forwarding."))
    j.event("idp", "mints delegated token", tone="ok", token="act=orders")
    j.message("idp", "orders", "access_token (aud=billing)", tone="ok", response=True)
    j.message("orders", "billing", "POST /charges", detail="Bearer delegated token", tone="ok", token="delegated token",
              story=S("Billing saw both of you", what="The token's sub is you; its act.sub is the Orders service.",
                      why="RFC 8693 records the delegation chain in the act claim.",
                      matters="Billing can authorize and audit on both identities: who the charge is for, and which service asked."))
    j.event("billing", "201 Created", tone="ok", token="201")
    j.allow("Orders received a Billing-audience token that names both the user and itself.",
            caption="subject + actor exchanged · delegated token · Billing returned 201")
    j.token("Delegated token", raw=fake_jwt({"iss": "https://as.example.com", "sub": "kim@example.com", "aud": "billing",
                                            "scope": "charges.create", "act": {"sub": "orders-service"},
                                            "iat": NOW, "exp": NOW + 300}),
            show=["sub", "act", "aud", "scope", "exp"], note="Short-lived (5 minutes): exchanged tokens should be.")
    return j


# ── 6. Client credentials (machine to machine, no user) ─────────────────────────────────────
def client_credentials():
    j = Journey("Nightly job reads the inventory", subtitle="OAuth 2.0 client credentials grant (machine to machine)",
                tags=["M2M", "client credentials", "private_key_jwt"])
    j.actor("job", "Batch job", short="JOB", kind="service")
    j.actor("idp", "Authorization server", short="AS", kind="idp")
    j.actor("api", "Inventory API", short="API", kind="resource")
    j.message("job", "idp", "/token", detail="client_credentials + private_key_jwt", tone="info", token="client assertion",
              story=S("The job authenticated as itself", what="The job signed a short-lived JWT with its private key and asked for a token.",
                      why="No user is involved; the workload is the principal.",
                      matters="Key-based client auth means no shared secret to leak or rotate by hand."))
    j.event("idp", "mints token", tone="ok", token="access token")
    j.message("idp", "job", "access_token", tone="ok", response=True)
    j.message("job", "api", "GET /inventory", detail="Bearer access_token", tone="ok", token="access token",
              story=S("The API saw a machine, not a person", what="The token's sub is the client itself.",
                      why="Client credentials tokens carry no user identity.",
                      matters="Grant these narrowly: there is no user whose limits bound them."))
    j.event("api", "200 OK", tone="ok", token="200 OK")
    j.allow("The workload authenticated with its key and received a token scoped to inventory reads.",
            caption="client authenticated · token minted · API returned 200")
    j.token("Access token", raw=fake_jwt({"iss": "https://as.example.com", "sub": "batch-job-client", "aud": "inventory",
                                         "scope": "inventory.read", "iat": NOW, "exp": NOW + 3600}),
            show=["sub", "aud", "scope", "exp"], note="sub is the client: there is no user in this token.")
    return j


# ── 7. MCP authorization: discovery (RFC 9728) + DCR + auth code ────────────────────────────
def mcp_discovery():
    j = Journey("An MCP client connects to a protected server", subtitle="MCP authorization: RFC 9728 discovery, dynamic client registration, auth code + PKCE",
                tags=["MCP", "RFC 9728", "RFC 7591 DCR", "agentic"])
    j.actor("client", "MCP client (agent)", short="CLIENT", kind="agent")
    j.actor("server", "MCP server", short="SERVER", kind="resource")
    j.actor("as", "Authorization server", short="AS", kind="idp")
    j.actor("user", "User's browser", short="BROWSER", kind="user")
    j.message("client", "server", "initialize", detail="no token", tone="neutral",
              story=S("The client tried to connect", what="The MCP client sent initialize without a token.",
                      why="It doesn't yet know this server needs authorization.",
                      matters="Discovery starts from a plain request; nothing is preconfigured."))
    j.message("server", "client", "401 + WWW-Authenticate", detail="resource_metadata=...", tone="deny", response=True,
              story=S("The server challenged it", status="deny", what="The server answered 401 with a pointer to its protected-resource metadata.",
                      why="RFC 9728 lets a resource advertise which authorization server protects it.",
                      matters="If a server skips this challenge, discovery-driven clients never start the auth flow."))
    j.message("client", "server", "GET protected-resource metadata", tone="info")
    j.message("client", "as", "register client", detail="POST /register (RFC 7591)", tone="info", token="client metadata",
              story=S("The client registered itself", what="The client registered dynamically and received a client_id.",
                      why="Agents meet servers at runtime; pre-registration doesn't scale.",
                      matters="The authorization server still decides which redirect URIs and grants it allows."))
    j.message("client", "user", "open browser", detail="/authorize + PKCE", tone="info")
    j.message("user", "as", "sign in + consent", tone="info", token="user session",
              story=S("You signed in and approved", what="You authenticated at the authorization server and consented to the client's access.",
                      why="The agent acts with your identity, so you authorize it.",
                      matters="The agent never handles your credentials."))
    j.event("as", "mints token", tone="ok", token="access token")
    j.message("as", "client", "code -> token", tone="ok", response=True)
    j.message("client", "server", "tools/list", detail="Bearer access_token", tone="ok", token="access token",
              story=S("The client connected with a token", what="The MCP server accepted the token and listed its tools.",
                      why="The token's audience is this server (RFC 8707 resource indicator).",
                      matters="One server's token can't be replayed against another."))
    j.event("server", "tools listed", tone="ok", token="200 OK")
    j.allow("Discovery, registration and sign-in completed; the client holds a token for this MCP server only.",
            caption="challenge → discovery → DCR → auth code → token · tools listed")
    j.token("Access token", raw=fake_jwt({"iss": "https://as.example.com", "sub": "kim@example.com", "aud": "https://mcp.example.com",
                                         "client_id": "dcr-4f1c", "scope": "mcp:tools", "iat": NOW, "exp": NOW + 3600}),
            show=["sub", "aud", "client_id", "scope", "exp"])
    return j


EXAMPLES = {
    "agentic-xaa-allow": lambda: agentic("allow"),
    "agentic-xaa-deny": lambda: agentic("deny"),
    "agentic-xaa-refused": lambda: agentic("refused"),
    "oidc-auth-code-pkce": auth_code_pkce,
    "rfc8693-token-exchange": token_exchange,
    "client-credentials": client_credentials,
    "mcp-authorization-discovery": mcp_discovery,
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    index = []
    for name, build in EXAMPLES.items():
        j = build()
        j.save(os.path.join(OUT, name + ".json"))
        d = j.to_dict()
        index.append({"file": name + ".json", "title": d["title"], "subtitle": d.get("subtitle", ""),
                      "status": d.get("outcome", {}).get("status", "")})
        print("wrote", name)
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump(index, f, indent=2)
        f.write("\n")
