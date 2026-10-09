# Architecture and design decisions

## The one idea

**Separate what happened from how it is drawn.** The original lab viewer computed its diagram
from a backend's internal status flags and hardcoded the actors, the order of steps, and the
explanatory copy inside the renderer. That made it beautiful for one flow and impossible to reuse.

Here, a trace (plain JSON) carries everything flow-specific. The viewer is a player for traces and
contains no protocol knowledge at all. Recorders and adapters are the only code that knows about
any particular protocol or product.

```
  flow knowledge                         no flow knowledge
  ─────────────────────────────────────  ──────────────────────────────
  recorder calls in your code  ─┐
  adapter for an app's shape   ─┼──► trace (JSON) ──► viewer ──► DOM
  hand-written file            ─┘
```

## Decisions

**Two views of one trace.** Narrative cards answer what, why, and why it matters for people
learning the concept; the sequence diagram shows the exact protocol steps for people debugging
it. Both are driven by the same trace, so they can never disagree.

**Three outcomes, not two.** `allow`, `deny` (no token was issued), and `refused` (a token was
issued but the resource rejected it). Collapsing the last two hides the most important lesson
in delegated and agentic access: a token can be valid and still be too narrow, and that narrowing
is the system working as designed.

**A traveling token pill.** Sequence diagrams normally show messages; this one also shows the
credential as a single object moving and changing. That is what makes token exchange and
delegation legible to newcomers.

**Zero dependencies, no build step.** The viewer is one JS file and one CSS file. It can be
dropped into a docs site, a slide, an internal tool, or a training lab without a toolchain.

**Safe with untrusted traces.** Every string goes through `textContent`; links are restricted to
http(s); the decoder never verifies and the docs say so loudly. Traces are data, and the viewer
treats them that way.

**Redact by default.** Recorders replace JWT signatures, so a trace saved during debugging is not
a replayable credential. Claims stay readable because they are the point.

**Validate early and explain precisely.** The recorders refuse invalid steps at the moment you
write them; the viewer renders a precise error list instead of a broken diagram.

## Testing strategy

| Layer | Test | What it proves |
|---|---|---|
| Format | `tests/viewer.test.js` | Every example validates; the validator names the faulty field. |
| Recorders | `tests/test_recorder.py`, parity test | Builders reject mistakes; Python and JS output is identical. |
| Adapter | `tests/adapter.test.js` | Each lab outcome classifies and converts to a valid journey. |
| Live flow | `tests/test_live_oidc.py` | A real auth code + PKCE (+ exchange + API) flow against a mock IdP that genuinely verifies PKCE, for success, a denied exchange, and a refused API call. |
| Rendering | `tests/render_smoke.py` | Every example, both views, both themes, in Chromium: no console errors, correct row and card counts, correct verdict. |
