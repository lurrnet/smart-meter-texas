# Contributing to Smart Meter Texas

Thanks for helping improve this unofficial, self-hosted dashboard.

## Workflow
1. Open an issue for significant features or behavior changes.
2. Branch from current `main` using `feature/<topic>`, `fix/<topic>`, or `chore/<topic>`.
3. Never commit credentials, real meter data, private logs, SQLite databases, Cloudflare tokens, or screenshots containing them.
4. Run `python -m pip install -e '.[dev]'` and `python -m pytest -q`.
5. Run `cd frontend && npm ci && npm run build`.
6. Open a pull request to `main`; wait for all required checks and review. Maintainers squash or rebase according to repository protections.
7. Delete merged topic branches. Do not push directly to protected `main`.

## Security and data
Use fake data for tests and screenshots. Report vulnerabilities privately per [SECURITY.md](SECURITY.md), not in a public issue. Keep deployed origins and `/api/*` protected by application authentication or a verified Cloudflare Access boundary.

## Releases
`main` is stable but not automatically deployed. Maintainers create annotated, immutable semver tags (`vX.Y.Z` or `vX.Y.Z-rc.N`) only after CI. Place release notes at `docs/releases/<tag>.md` on `main` **before tagging**, and update `CHANGELOG.md`. Run the manually dispatched **Publish GitHub Release** workflow from `main`, entering the existing tag. It validates the tag and successful `main` CI before publication; RC tags become prereleases.

Production upgrades are **manual**, after database backups and staging verification. Never overwrite existing release tags. Document any migrations and rollback steps. A GitHub source release is not an automatic Docker deployment, and publication does not confer permission to scrape Smart Meter Texas.
