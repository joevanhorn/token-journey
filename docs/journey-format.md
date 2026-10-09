# Journey format (version 1)

A journey is one JSON document describing one flow. The viewer renders it; nothing in it is
specific to any identity provider. The machine-readable definition is
[`schema/journey.schema.json`](../schema/journey.schema.json); this page explains the intent.

## Minimal example

```json
{
  "version": 1,
  "title": "Nightly job reads the inventory",
  "actors": [
    { "id": "job", "label": "Batch job", "kind": "service" },
    { "id": "as",  "label": "Authorization server", "short": "AS", "kind": "idp" },
    { "id": "api", "label": "Inventory API", "kind": "resource" }
  ],
  "steps": [
    { "type": "message", "from": "job", "to": "as", "label": "/token", "detail": "client_credentials", "tone": "info" },
    { "type": "event", "at": "as", "label": "mints token", "tone": "ok", "token": "access token" },
    { "type": "message", "from": "job", "to": "api", "label": "GET /inventory", "tone": "ok", "token": "access token" }
  ],
  "outcome": { "status": "allow" }
}
```

That is a complete, renderable journey. Everything else adds detail.

## Top level

| Field | Required | Meaning |
|---|---|---|
| `version` | yes | Always `1`. |
| `title` | | Headline above the journey. |
| `subtitle` | | One line of context, usually the protocol or grant. |
| `tags` | | Short chips, e.g. `["agentic", "RFC 8693"]`. |
| `actors` | yes | At least two participants, in left-to-right lane order. |
| `steps` | yes | What happened, in order. Each step is one row of the diagram. |
| `outcome` | | How it ended. Drives the verdict banner and status. |
| `tokens` | | Token cards shown under the diagram. |
| `links` | | Outbound links, e.g. to the IdP's audit log for this request. |

## Actors

| Field | Meaning |
|---|---|
| `id` | Referenced by steps. Unique. |
| `label` | Full name. Shown on narrative cards and in tooltips. |
| `short` | Lane cap text in the diagram (e.g. `IDP`). Defaults to `label`. Keep it under ~10 characters. |
| `sublabel` | Optional second line under the cap, e.g. a hostname. |
| `kind` | `user`, `agent`, `gateway`, `idp`, `resource`, or `service`. Picks the accent color. |
| `color` | Any CSS color. Overrides the kind color. |
| `description` | Tooltip text. |

An actor that no step touches is drawn with a dimmed, dashed lifeline. Use that on purpose: in a
"denied" journey, keeping the resource in the lanes but never reaching it shows that the request
stopped before it got there.

## Steps

There are two step types. Every step needs a `label`.

**`message`**: an arrow from one actor to another (`from`, `to`). A request, or with
`"return": true` a dashed response arrow.

**`event`**: something that happens at one actor (`at`): a token minted, a policy evaluated,
a check failing.

| Field | Applies to | Meaning |
|---|---|---|
| `label` | both | Short text on the arrow or beside the marker. |
| `detail` | message | Smaller second line, e.g. `grant_type=token-exchange`. |
| `tone` | both | `neutral`, `info`, `ok`, or `deny`. See below. |
| `token` | both | Text for the traveling token pill. See below. |
| `symbol` | event | Marker glyph. Defaults to ◆ / ✓ / ✗ by tone. |
| `return` | message | Draw as a dashed response arrow. |
| `note` | both | Tooltip with extra detail (a raw parameter, a policy id). |
| `story` | both | Makes this step a card in the Narrative view. See below. |

### Tones

| Tone | Color | Use it for |
|---|---|---|
| `neutral` | grey | Plain requests that aren't the point of the story. |
| `info` | gold | The flow in progress: requests to the authorization server, assertions in flight. |
| `ok` | green | Success: a token minted, a 2xx response. |
| `deny` | red | A refusal: no token, an error, a 401/403. |

Default tone is `neutral` for messages and `info` for events.

### The token pill

The pill is the visual thread of the diagram: it shows the credential that is moving. When a
step has `token`, the pill appears at the start of the step showing that text and travels along a
message arrow (or morphs in place for an event). It keeps its last position between steps, so a
sequence like `"user ⊕ agent"` → `"ID-JAG"` → `"scoped token"` → `"200 OK"` reads as one
credential being transformed. A `deny` tone turns it red, `ok` turns it green.

Use it for the credential, not for every step. Steps without `token` simply don't move it.

### Stories (the Narrative view)

Any step with a `story` becomes a narrative card, in step order. A story answers three questions:

| Field | Question |
|---|---|
| `title` (required) | What is this step, in plain words? |
| `what` | What happened? |
| `why` | Why did it happen? |
| `matters` | Why does it matter? (The lesson. Rendered slightly stronger.) |
| `status` | `done` (✓), `deny` (✗), or `skip` (◦, faded: a step that never ran). Defaults to `deny` for a deny-toned step, else `done`. |
| `actor` | Actor id for the card's chip and color. Defaults to the step's `at` or `from`. |

You don't need a story on every step. Group detail: in the examples, the five or six diagram
steps of a token exchange are told as three or four cards.

## Outcome

| Field | Meaning |
|---|---|
| `status` | `allow`: it worked. `deny`: no token was issued. `refused`: a token was issued, but the resource rejected the call. |
| `headline` | Verdict banner title. Defaults to `✓ ALLOWED`, `✕ DENIED: NO TOKEN`, or `✕ REFUSED BY RESOURCE`. |
| `detail` | One or two sentences of explanation. |
| `caption` | A one-line summary under the diagram. |

The distinction between `deny` and `refused` is deliberate and worth keeping. "The authorization
server said no" and "the authorization server said yes, but to less than the call needed" are
different failures with different fixes, and teaching that difference is half the point of the
tool.

## Tokens

| Field | Meaning |
|---|---|
| `label` | Card title, e.g. `Delegated access token`. |
| `raw` | A compact JWT. Decoded in the browser, **never verified**. |
| `claims` | For opaque tokens (pass introspection output) or to override decoding. |
| `show` | Claims to display, in order. Default: `sub`, `aud`, `iss`, `scope`, `act`, `exp`. |
| `missing` | Scopes the call needed but the token lacks; shown struck through in red. |
| `note` | A sentence under the claims. |

`scope` in `show` renders the token's scopes as chips, from either `scp` (array) or `scope`
(space-delimited string, RFC 9068). `act` (the RFC 8693 actor claim) renders as `sub=<actor>`,
which is how delegation shows up in an agentic flow: `sub` is the user, `act.sub` is the agent.
`exp`, `iat`, and `nbf` render as ISO timestamps.

If `outcome.status` is `deny` and there are no tokens, the viewer shows a "No token issued" card.

## Links

`{ "label": "Open in System Log", "href": "https://..." }`. Only `http:` and `https:` URLs are
rendered.

## Validation

`TokenJourney.validate(journey)` returns a list of human-readable errors (empty means valid), and
the viewer shows them in place of the journey, e.g.
`steps[3].to "api" is not a declared actor`. The recorders check the same rules as you build, and
the JSON Schema lets editors and CI catch mistakes before anything renders.
