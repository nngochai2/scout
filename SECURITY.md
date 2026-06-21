# Security Policy

## Supported Versions

Scout is currently in active development (pre-1.0). Security fixes are applied to the latest commit on `main`.

| Version | Supported |
| ------- | --------- |
| main    | ✅        |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Email **nngochaial@gmail.com** with the subject line `[SECURITY] Scout — <brief description>`.

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Any suggested mitigations (optional)

You can expect an acknowledgement within **48 hours** and a status update within **7 days**. If the vulnerability is accepted, a fix will be prioritised and you will be credited (unless you prefer otherwise). If it is declined, you will receive an explanation.

## Scope

Areas of particular concern for this project:

- **API key exposure** — leaking `ANTHROPIC_API_KEY`, `FRESHDESK_API_KEY`, or database credentials through logs, error messages, or the dashboard API
- **MCP server access** — bypassing the read-only allowlist guard on MCP tool calls
- **SQL injection** — queries constructed through the Oracle MCP or SQLAlchemy ORM
- **SSRF** — the SSE client connecting to attacker-controlled MCP server URLs
- **Insecure deserialization** — loading untrusted `data/flow.json` or fixture files

Out of scope: vulnerabilities in third-party dependencies (report those upstream), UI cosmetic issues, and findings from automated scanners without a working proof-of-concept.
