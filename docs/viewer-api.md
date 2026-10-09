# Viewer API

`viewer/token-journey.js` has no dependencies and works as a `<script>` tag (global
`TokenJourney`), a CommonJS module, or inside a bundler. Include `viewer/token-journey.css` too.

## `TokenJourney.render(container, journey, options) -> controller`

Renders into `container` (any element), replacing its contents.

| Option | Default | Meaning |
|---|---|---|
| `view` | `'technical'` | Initial view: `'technical'` (sequence diagram) or `'narrative'` (story cards). |
| `controls` | `true` | Show the Narrative/Technical toggle and the replay button. |
| `animate` | `true` | Play the step-by-step build-out. `false` paints the final state at once (good for printing, screenshots, static docs). |
| `speed` | `1` | Animation speed multiplier. `2` is twice as fast. |
| `motion` | `'auto'` | `'auto'` honors the OS "reduce motion" setting; `'always'` animates regardless (for kiosks and recordings). |
| `theme` | `'auto'` | `'auto'` follows the OS; `'light'` or `'dark'` forces one. |
| `tokens` | `'technical'` | `'technical'` shows token cards only in Technical view; `'always'` shows them in both. |
| `onDone` | | Called each time a build-out finishes. |

The returned controller:

| Member | Meaning |
|---|---|
| `setView(view)` | Switch views and replay. |
| `replay()` | Replay the current view from the start. |
| `destroy()` | Stop animations and empty the container. |
| `journey` | The journey being shown. |
| `errors` | Present only when the journey was invalid. |

An invalid journey renders a list of validation errors instead of throwing, so a bad trace in a
docs page fails visibly and explains itself.

## Helpers

- `TokenJourney.validate(journey) -> string[]`: human-readable errors; empty means valid.
- `TokenJourney.decodeJwt(raw) -> { header, payload } | null`: decodes a compact JWT.
  **Does not verify the signature.** Never use it for trust decisions.
- `TokenJourney.scopesOf(claims) -> string[]`: scopes from `scp` (array or string) or `scope`.

## Theming

All styling is scoped under `.tj` and driven by custom properties. Override them on `.tj` (or a
wrapper) to re-brand:

```css
.my-docs .tj {
  --tj-info: #6d5efc;      /* in-flight steps, the pill, tags */
  --tj-ok: #16a34a;        /* success */
  --tj-deny: #dc2626;      /* refusals */
  --tj-panel: #ffffff;     /* card background */
  --tj-k-idp: #6d5efc;     /* actor colors by kind: user, agent, gateway, idp, resource, service */
  --tj-sans: "Inter", system-ui, sans-serif;
  --tj-mono: "IBM Plex Mono", ui-monospace, monospace;
}
```

Light and dark palettes are both built in. `data-theme="light"` or `data-theme="dark"` on `.tj`
or any ancestor forces one; otherwise the OS preference decides.

## Embedding notes

- The diagram sizes to its container and scrolls horizontally if lanes would be narrower than
  about 100 px, rather than squeezing labels. Around 520 px or wider suits five actors.
- Several viewers can live on one page; each `render` call is independent.
- The viewer is accessible by default: the view toggle is a labeled button group with
  `aria-pressed`, the verdict is a `role="status"` region, and the diagram has an `aria-label`.
  The Narrative view is the screen-reader-friendly rendering of the same journey.
