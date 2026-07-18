# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in yeaboi, please report it privately so
it can be fixed before public disclosure.

- **Preferred:** open a [GitHub private security advisory](https://github.com/omardin14/yeaboi.ai/security/advisories/new)
  (Security → Advisories → *Report a vulnerability*).
- **Alternatively:** email **onoureldin@gmail.com** with the details.

Please include: a description of the issue, the affected version, steps to
reproduce (a proof of concept if you have one), and the impact you foresee.
Do **not** open a public issue for a suspected vulnerability.

We aim to acknowledge reports within a few days and to ship a fix or mitigation
as quickly as the severity warrants. You'll be credited in the release notes
unless you prefer to remain anonymous.

## Supported versions

yeaboi ships from `main` to PyPI. Security fixes target the latest released
version; please upgrade (`uv tool install --upgrade yeaboi` /
`pipx upgrade yeaboi`) before reporting to confirm the issue still reproduces.

## Threat model & notes for users

yeaboi is a local terminal tool. A few features have deliberate trust boundaries
worth understanding:

- **Retro mode runs a LAN web server with no TLS.** It binds all interfaces so
  teammates on your network can join with a short code. Access to `/api/*` is
  gated by a 128-bit token, and the join endpoint is rate-limited, but this is a
  **LAN-trust** model — do not port-forward it to the public internet.
- **"Share Remotely" opens a public Cloudflare tunnel.** While active, the
  token-gated board is reachable from the internet (over HTTPS). Anyone with the
  link + join code can participate. Stop sharing when the retro ends.
- **`cloudflared` is auto-downloaded** from a pinned Cloudflare release and
  verified against a bundled SHA-256 before it is made executable or run.
- **Credentials are stored in `~/.yeaboi/.env`** (plaintext, `0600`, in a `0700`
  directory). Anyone with read access to your account can read them — treat that
  file like any other secrets file and never commit it.
- **External content (Jira/Confluence/Notion tickets, git commits, retro cards,
  1:1 transcripts) is fed to the LLM.** The agent's tools are read-only, which
  limits the blast radius of prompt injection, but treat generated output as
  untrusted when it is rendered or delivered.

## Automated scanning

Every pull request runs SAST (ruff flake8-bandit rules), a dependency CVE audit
(`pip-audit` against the committed `uv.lock`), and secret scanning (gitleaks).
Dependabot proposes dependency and GitHub Actions updates weekly, and a scheduled
workflow re-scans `main` and opens a fix PR for any new finding. Run the same
checks locally with `make security`.
