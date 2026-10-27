# v0.2.0 public release verification

## Completed / confirmed on GitHub

- [x] Public repository created from an isolated single-commit source snapshot (2026-10-27)
- [x] AGPL-3.0 license file included in the public source
- [x] Repository description and SECURITY.md present
- [x] README includes deployment, privacy, raw payload retention and Cloudflare Access warnings
- [x] Frontend dependencies pinned with package-lock.json and npm ci
- [x] Python tests passed in CI (run 40443537318)
- [x] Frontend build passed in CI (run 40443537318)
- [x] Docker image health and Basic-authentication smoke test passed in CI (run 40443537318)
- [x] Full-history Gitleaks scan passed in CI (run 40443537318, clean public snapshot only)
- [x] CodeQL setup workflow completed successfully (run 40444880000)
- [x] `main` branch ruleset active, requiring PR, checks, signed commits and linear history
- [x] Annotated `v0.2.0` tag exists and references source commit `6ca35498fbc95c23a4c7e23a2a7f2cc22eb1b06f`

## Release publication

- [x] Release notes prepared in [v0.2.0.md](releases/v0.2.0.md)
- [ ] GitHub Release published (check [Releases](https://github.com/lurrnet/smart-meter-texas/releases/tag/v0.2.0) and the release workflow after merge)

## Operator and policy checks not verified by CI

- [ ] Validate actual HTTPS and Cloudflare Access login at the deployed hostname
- [ ] If app Basic auth is disabled, verify Access covers all paths including `/api/*`, and there are no alternate routes to the origin
- [ ] Confirm a production database backup and restore procedure
- [ ] Manually review repository artifacts, public screenshots and disclosures for confidential information
- [ ] Confirm GitHub private vulnerability reporting is enabled
- [ ] Review current SMT terms and Residential User Guide §9; obtain any authorization necessary for automated website-endpoint retrieval

The software is **unofficial** and the GitHub release is a source-code publication, not authorization by Smart Meter Texas. Automated CI checks do not substitute for deployment-specific verification or review of provider terms.
