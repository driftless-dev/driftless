# Security policy

## Supported versions

Driftless is currently in the `0.3.x` alpha release line. Security fixes are
made against the latest published release; users should upgrade to the newest
patch before reporting an issue.

## Reporting a vulnerability

Please do **not** open a public issue for a suspected vulnerability.

Use GitHub's private vulnerability reporting for this repository:

<https://github.com/driftless-dev/driftless/security/advisories/new>

Include:

- the affected Driftless version and Python version;
- the command, contract fields, or GitHub Action configuration involved;
- a minimal reproduction or proof of concept;
- the potential impact, especially whether secrets, arbitrary commands, or
  repository writes are involved.

You should receive an acknowledgement within five business days. We will
coordinate disclosure and release timing with the reporter.

## Security boundaries

- Driftless executes the `run.command` and optional data-source command declared
  in `driftless.yml`. Treat contract authors as trusted; review contract changes
  with the same care as CI workflow changes.
- Prompt repair may call external model providers and sends the repair context
  configured by the user. Do not include secrets or sensitive records unless
  the selected provider and account are approved for them.
- GitHub workflows should use least-privilege permissions. Driftless never
  auto-merges a migration; passing changes are proposed for review.
- Agent tools and other side-effecting harnesses must be sandboxed by the user.
  Driftless does not provide a hosted execution sandbox.

