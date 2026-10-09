# Contributing

Thanks for helping. Issues and pull requests are welcome, especially new example journeys for
flows the gallery doesn't cover yet.

## Ground rules

- **The viewer stays protocol-neutral.** No identity-provider or protocol names in
  `viewer/`. Flow knowledge belongs in traces, recorders, and adapters.
- **No runtime dependencies** in `viewer/` or the recorders.
- **Format changes need an issue first.** The format is versioned; additions must be optional
  and backward compatible within version 1.
- **Never commit real tokens.** Example tokens are synthetic (see `examples/build_examples.py`).

## Adding an example journey

1. Add a builder function to `examples/build_examples.py` and register it in `EXAMPLES`.
2. Run `npm run examples` to regenerate `examples/journeys/`.
3. Run the tests below; the render test picks up new examples automatically.

## Tests

```bash
npm test                              # Node 18+
python3 -m unittest discover tests    # Python 3.8+
python3 tests/render_smoke.py         # needs: pip install playwright && playwright install chromium
```

## Writing style for docs and example stories

Plain, direct sentences. Explain why something matters, not just what happened. Prefer role
names ("authorization server") over product names unless the product is the point.
