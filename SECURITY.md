# Security Policy

## Supported version

Security fixes target the latest v0.2.x release series.

## Responsible disclosure

Do not open a public issue containing credentials, tokens, meter data, or exploitable details. Contact the repository owner privately using GitHub's private vulnerability reporting mechanism when enabled. If it is unavailable, ask the maintainer to enable a private reporting channel without sharing exploit details publicly.

## Deployment

- Configure utility account credentials in a local, untracked `.env` file. Dashboard credentials are required only if app-level Basic authentication is enabled.
- The dashboard uses HTTP Basic authentication by default (`SMT_WEB_AUTH_ENABLED=true`). Use HTTPS or trusted local transport, not a public HTTP connection.
- To delegate login to Cloudflare Zero Trust Access, you can explicitly set `SMT_WEB_AUTH_ENABLED=false`. This disables **all application authentication** for both dashboard and API, including operations that change data. The application does not check or validate Cloudflare identity headers/tokens.
- When Basic auth is disabled, require Cloudflare Access login for the **entire application hostname**, including `/api/*`; block any direct origin access via public IP, other hostnames, open host ports, or bypassing reverse-proxy routes. Ensure only the authenticated gateway can reach the application.
- The Compose default host binding is 127.0.0.1. Maintain additional access controls at the reverse proxy or Cloudflare Access boundary.
- Treat `./data` and `./logs` as private, including SQLite backups that may contain energy use, location and Discord webhook credentials.
- Raw interval response capture is disabled by default; enable `SMT_SAVE_RAW_PAYLOADS=1` only for temporary troubleshooting.
- Regularly delete old raw payload logs and back up the SQLite store securely. The application does not remove historical logs automatically.
- Routine sync results do not include meter identifiers or upstream diagnostic response bodies; use explicit `--discover-meters` only in a private terminal.
- Avoid mounting the app's data or logs directory into any public/static web directory.
- Rotate any credential discovered in Git history even if the corresponding commit is deleted.
