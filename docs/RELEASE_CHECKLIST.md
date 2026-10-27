# v0.2.0 public release checklist

- [ ] Verify local/remote HTTPS deployment and successful login (Cloudflare Access if app Basic auth is disabled)
- [ ] If `SMT_WEB_AUTH_ENABLED=false`: verify every route, including `/api/*`, is covered by Access and no direct origin IP/port or alternate hostname bypasses Access
- [ ] Test lack of credentials denies access (fail-closed)
- [ ] Confirm no route can read outside frontend_dist
- [ ] Run Python tests, frontend build and Docker smoke test
- [ ] Run Gitleaks against **all Git history** and inspect GitHub Actions artifacts
- [ ] Inspect full-history Gitleaks CI result, then manually review for real meter identifiers, Discord URLs, API secrets and private information
- [x] Pin frontend dependencies, commit package-lock.json, and use npm ci in CI and Docker
- [ ] Confirm AGPL-3.0 is the intended open-source license
- [ ] **Provider access review:** review [SMT Terms](https://www.smartmetertexas.com/?view=security) and [Residential User Guide §9](https://www.smartmetertexas.com/commonapi/gethelpguide/help-guides/Smart_Meter_Texas_Residential_User_Guide.pdf); obtain any necessary authorization before recommending unofficial-website-endpoint automation
- [ ] **History decision:** Git history and merged/closed PRs still contain old sample locations; decide whether a clean public snapshot is preferable to exposing all private development history
- [ ] Delete unnecessary merged feature/release branches; review PR history, including the closed superseded Docker CI fixture PR
- [ ] Confirm the public documentation doesn't contain private addresses or screenshots
- [ ] Review README configuration, raw payload retention, and restore/backup instructions
- [ ] Confirm GitHub repository description, license choice, issues and private vulnerability reporting are configured as intended
- [ ] Remove stale release branches after the public release (preserve needed history)
- [ ] Enable GitHub private vulnerability reporting and branch protections where available
- [ ] Update version and changelog, create `v0.2.0` tag and GitHub Release
- [ ] Only then switch repository visibility to Public

Visibility and GitHub Release require a separate administrative action; neither is performed by the code changes.
