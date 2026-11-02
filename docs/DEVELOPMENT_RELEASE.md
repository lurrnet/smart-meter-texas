# Development and release process

This public repository uses GitHub Flow: protected `main`, short-lived `feature/*` and `fix/*` branches, pull requests and required CI. There is no long-lived `develop` branch.

## Release procedure

1. Merge reviewed feature/fix PRs only after checks pass.
2. Prepare `CHANGELOG.md` and `docs/releases/vX.Y.Z.md` (or `vX.Y.Z-rc.N.md`) in a PR to `main`.
3. Wait for the **main-branch CI run** on the exact commit intended for the release to succeed.
4. Create an **annotated** immutable tag on that commit: `git tag -a vX.Y.Z <sha> -m "Release vX.Y.Z"`; push the tag.
5. On GitHub Actions, manually run **Publish GitHub Release** from `main`, entering the tag. The workflow checks semver, tag type, ancestry, notes and successful CI for the exact tag commit. Existing releases are left untouched.
6. RC releases use `vX.Y.Z-rc.N` and are marked prerelease. Validate using a dedicated staging instance and synthetic data.
7. After RC acceptance, tag the tested code as `vX.Y.Z` (or a reviewed successor commit) and publish the stable release.
8. Back up the production SQLite database and local configuration; deploy the **tagged** source deliberately, not the moving `main` branch. Validate health, app authentication, Cloudflare Access protections, all `/api/*` routes, sync status and UI after deploy.

## Versioning and rollback

`v0.2.0` remains immutable. Feature work toward installable PWA targets `v0.3.0`, with patch releases for fixes. The Compose file builds local `smart-meter-texas:0.3.0` images for both services; the Python and frontend package metadata also report `0.3.0`. These source versions do not imply a published GitHub release. Verify the checked-out tag and image identity explicitly. Image labels alone do **not** prove deployed source provenance.

For rollback, stop the service, restore the previous tagged checkout/image and the compatible backed-up SQLite data if a migration occurred. Keep private `.env`, `data/` and `logs/` outside source control. Never deploy CI with real SMT credentials or real meter data.

### PWA staging acceptance (v0.3.0)

Verify Android and iOS installation, standalone launch, update behavior, access session expiration, fresh login, offline failure behavior, and that Service Workers do not cache `/api/*`, authorization responses, or private readings. Use HTTPS and synthetic test data.
