# Adapting Token Journey to your flow

The viewer only ever reads a trace, so adapting to a new flow is always the same job: produce a
trace that describes it. There are three ways to do that. Start with the first even if you plan
to end at the third: a hand-written trace is the fastest way to decide what your journey should
say.

## Before you start: design the journey

Spend ten minutes on paper first. The journeys that teach well share a shape.

1. **Pick the actors.** Usually three to five. Name them by role (`Authorization server`,
   `MCP gateway`), not by product, unless the product name is the point. Order them left to
   right in the order a request travels.
2. **Decide what the token pill tracks.** Follow one credential through the flow: what it
   starts as, what it's exchanged for, what it becomes. That transformation is the story.
3. **Choose the decision points.** Where does something say yes or no? Those are your `event`
   steps, and they get tones (`ok` or `deny`).
4. **Write the failure versions too.** The denied and refused journeys usually teach more than
   the successful one. Record all three outcomes of the same flow side by side.
5. **Write stories last**, and only for the steps a newcomer needs explained. Three or four cards
   per journey is plenty.

## Route 1: hand-write a trace

Best for documentation, slides, training, and explaining a design that isn't built yet.

1. Copy the closest example from [`examples/journeys/`](../examples/journeys) (they cover
   agentic delegation, auth code + PKCE, token exchange, client credentials, and MCP discovery).
2. Point your editor at the schema for autocompletion and inline errors. In VS Code, add to the
   top of the file: `"$schema": "../../schema/journey.schema.json"` (adjust the path).
3. Edit it, then paste it into the playground (`python3 -m http.server`, open `/examples/`).
   Validation errors appear in place of the journey with the exact field at fault.

Tokens in a hand-written trace can be `claims` objects instead of real JWTs:
`{ "label": "Access token", "claims": { "sub": "kim", "aud": "api", "scope": "read" } }`.

## Route 2: record from your code

Best when you actually run the flow: a backend, a gateway, an integration test, a CLI. You add a
few recorder calls next to the HTTP calls you already make.

```python
from token_journey import Journey

j = Journey("Service calls API", subtitle="client credentials")
j.actor("svc", "My service", kind="service").actor("as", "Auth server", short="AS", kind="idp").actor("api", "API", kind="resource")

resp = requests.post(token_url, data={...})          # your real call
j.message("svc", "as", "/token", detail="client_credentials", tone="info")
if resp.ok:
    j.event("as", "mints token", tone="ok", token="access token")
    j.token("Access token", raw=resp.json()["access_token"])   # signature redacted by default
else:
    j.event("as", resp.json().get("error", "error"), tone="deny", token="DENIED")
    j.deny(resp.text)                                 # the verbatim error is the most useful detail
j.save("journey.json")
```

Patterns that work well:

- **Record what happened, not what you expected.** Branch on the real response, as above. A
  journey built from assumptions hides exactly the bugs it should reveal.
- **Put the verbatim error in `outcome.detail`.** Authorization servers usually name the policy
  decision in their error text; that's what the reader needs.
- **Use `deny` for "no token" and `refused` for "token, but the resource said no".**
- **Keep recording off the hot path** in production: build the trace only when a debug flag or
  header is set, or only in tests.
- [`examples/live-oidc/app.py`](../examples/live-oidc/app.py) is a complete, commented example
  that records a real auth code + PKCE flow, an optional token exchange, and an API call.

The JavaScript recorder ([`recorder/js/journey-builder.js`](../recorder/js/journey-builder.js))
has the same API for Node services and middleware.

## Route 3: write an adapter

Best when an app already returns flow information in its own shape (an audit API, a gateway's
debug response, log events) and you want journeys without changing that app.

An adapter is one function: `yourResponse -> journey`. It's the right place for all the flow
knowledge (which actors exist, what each internal status means, what to tell the reader), so the
viewer stays generic.

[`adapters/okta-xaa-lab.js`](../adapters/okta-xaa-lab.js) is a complete worked example. Its input
is a lab backend's response listing four hops (agent, gateway, token exchange, app), each `ok` or
`denied`. The adapter:

1. **Classifies** the response into one outcome (`allow`, `deny`, `refused`, or a gateway denial)
   with a small, separately testable `classify()` function.
2. **Builds** the journey with the recorder, adding only the steps that actually ran for that
   outcome. A denied exchange ends at the identity provider; the resource lane stays dimmed.
3. **Extracts specifics** from verbatim fields, such as pulling the missing scope out of a
   `403 missing required scope: X` message so the token card can show it struck through.

Test the adapter with captured responses for every outcome, and validate each result (see
[`tests/adapter.test.js`](../tests/adapter.test.js)).

## Changing the look

You never need to edit the viewer to adapt a flow, but you may want it to match your brand.
Everything visual is CSS custom properties on `.tj`; see "Theming" in
[viewer-api.md](viewer-api.md). Actor colors come from `kind`, or set `color` per actor.

## Extending the format

If your flow needs something the format can't express, open an issue first. The format is
versioned (`"version": 1`) so it can grow without breaking existing traces, and additions should
stay protocol-neutral: the viewer must never need to know what a "Cross App Access" or a "PKCE
verifier" is.
