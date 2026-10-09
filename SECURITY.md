# Security

## What this project is, and isn't

Token Journey visualizes authentication flows for learning and debugging. It is **not** a
security control:

- The viewer and recorders **decode tokens without verifying them**. Never use either to decide
  whether a token is trustworthy.
- Rendering a trace proves nothing about what really happened; a trace is only as accurate as the
  code that recorded it.

## Handling traces safely

- Recorders replace JWT signatures with `REDACTED-SIGNATURE` by default, so a saved trace can't be
  replayed. Don't disable this (`redact=False`) for traces you share.
- Claims are still personal data (subjects, emails, group names). Don't publish traces recorded
  from real users, and treat traces from production like logs.
- `examples/live-oidc/app.py` is a local tool: it binds to 127.0.0.1, keeps tokens in memory only,
  and should never be exposed on a shared host.

## Rendering untrusted traces

The viewer writes every trace string with `textContent` and only renders http(s) links, so a
malicious trace can't inject markup or script. If you find a way around that, please report it.

## Reporting a vulnerability

Please report security issues privately through GitHub's "Report a vulnerability" (Security tab)
rather than in a public issue.
