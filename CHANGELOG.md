# Changelog

## [0.2.0] - 2026-10-27

### Features
- Smart Meter Texas 15-minute data retrieval and scheduled incremental sync
- Dashboard overview, usage charts, data health, gap repair and tariff-period cost analytics
- Weather correlation, inferred HVAC estimates and anomaly detection
- Web UI-managed electricity defaults, weather location, Discord webhook and anomaly threshold
- Opt-in automatic Discord anomaly alerts with deduplication and a delivery test

### Security and reliability
- Fail-closed HTTP Basic authentication for dashboard and API by default
- Optional `SMT_WEB_AUTH_ENABLED=false` to delegate login to Cloudflare Access or another trusted upstream gateway
- Localhost-only Docker published port by default
- Prevent traversal from SPA fallback to sensitive files outside compiled frontend
- Align CLI app serving port with Compose / Dockerfile port 8090
- Add authentication and routing regression tests
- Expand exclusions for sensitive/local build files
- Disable raw interval payload retention by default and restrict sensitive file permissions
- Redact routine sync API output and prevent webhook URLs from appearing in settings API responses
- Reproducible npm lockfile and CI security checks

### Documentation
- Replace outdated MVP1 README with installation, deployment and privacy guidance
- Add SECURITY.md, GitHub CI and release-readiness checklist

First public source snapshot, tagged as v0.2.0. The tagged source passed CI Python tests, frontend build, Docker smoke test and full-history Gitleaks scan. Production-specific access controls and any authorization required by Smart Meter Texas remain the responsibility of each operator. Publishing source code does not grant permission for automated retrieval.
