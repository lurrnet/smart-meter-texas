# PWA staging acceptance: v0.3.0-rc.1

Run on a separate HTTPS hostname behind Cloudflare Access, with isolated and synthetic data. Never copy the production SQLite store or `.env` to a publicly reachable staging environment.

## Deploy an immutable prerelease

1. Confirm `v0.3.0-rc.1` is an **annotated tag** on a commit of `main`, the exact main CI run is green, and the prerelease exists.
2. `git fetch --tags origin && git checkout --detach v0.3.0-rc.1` on the staging host.
3. Set a unique image tag for both services using `SMT_IMAGE_TAG=0.3.0-rc.1 docker compose build` followed by `SMT_IMAGE_TAG=0.3.0-rc.1 docker compose up -d`; confirm `docker compose ps` and `/api/health`.
4. Do not expose port 8090 directly. Ensure Cloudflare Access protects the entire staging hostname, including `/api/*`, `/manifest.webmanifest`, `/sw.js`, and icons. If `SMT_WEB_AUTH_ENABLED=false`, the origin must have no alternate unauthenticated ingress.

## Browser acceptance

- [ ] Android Chrome: install prompt/Add to Home Screen; inspect icon, standalone startup and navigation.
- [ ] iOS Safari: Add to Home Screen; inspect icon, standalone startup and navigation.
- [ ] In both installed contexts, confirm Cloudflare Access email login works after prior session expiry.
- [ ] Verify online data fetches and error behavior without connectivity; no private data appears offline.
- [ ] Inspect DevTools Application → Cache Storage: no HTML, API, JSON, readings, or Access login responses.
- [ ] Upgrade from RC to a different build; verify update behavior and manual reload action.
- [ ] Check network response types for `manifest.webmanifest` and `sw.js`, and confirm unauthorized requests are denied by the configured authentication boundary.
- [ ] Verify health, dashboard tabs, sync status, and rollback to a previous release.

Document devices, OS/browser versions, findings and any follow-up PRs before declaring a stable release.
