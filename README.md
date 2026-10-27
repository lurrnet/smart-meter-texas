# Smart Meter Texas

Self-hosted electricity usage monitoring and analytics, powered by Smart Meter Texas consumption data.

**Version:** [v0.2.0](https://github.com/lurrnet/smart-meter-texas/releases/tag/v0.2.0) (first public source release)

> **Unofficial integration:** This community project is not affiliated with or endorsed by Smart Meter Texas. It authenticates against website endpoints that are not the formally provisioned SMT API/FTPS integration; those endpoints may change. The [SMT Website Terms and Conditions](https://www.smartmetertexas.com/?view=security) restrict automated extraction except through prescribed functionality or with appropriate authorization. The [Residential User Guide, Section 9](https://www.smartmetertexas.com/commonapi/gethelpguide/help-guides/Smart_Meter_Texas_Residential_User_Guide.pdf) describes an official API/FTPS integration process through SMT Support. **Publishing this source code does not authorize automated access.** Review the provider terms and obtain any required permission before operating it.

## Features

- 15-minute and daily energy usage, dashboard KPIs, usage charts and a 7-day heatmap
- Incremental scheduled sync, manual catch-up, DST-aware data health and gap repair
- Date-ranged electricity pricing, historical cost charts and monthly bill forecasts
- Open-Meteo weather correlation and inferred HVAC-related consumption
- Modified Z-score usage anomalies, editable Discord webhook settings, and opt-in automatic Discord alerts
- Responsive light/dark dashboard with dedicated pages for Overview, Data Health, Energy Cost, Weather & HVAC, and Anomalies & Notifications

## Requirements

- Docker Engine with Docker Compose
- Smart Meter Texas account with access to your meter
- A private, trusted deployment network or HTTPS reverse proxy
- **Never publish port 8090 directly to the public internet**

## Quick start

```bash
git clone https://github.com/lurrnet/smart-meter-texas.git
cd smart-meter-texas
cp .env.example .env
# Edit .env: set SMT_USERNAME, SMT_PASSWORD, SMT_ESIID.
# By default, also set SMT_WEB_USERNAME and a unique SMT_WEB_PASSWORD (16+ characters).
# If access is already enforced by Cloudflare Zero Trust Access, you may instead
# set SMT_WEB_AUTH_ENABLED=false, provided port 8090 has no alternate public path.
docker compose up --build -d
```

Visit http://localhost:8090 on the Docker host. With the default `SMT_WEB_AUTH_ENABLED=true`, your browser will request the dashboard's HTTP Basic credentials. With the explicit `false` setting, the application itself does not authenticate users; the external gateway must do so.

By default Docker binds port 8090 to **127.0.0.1 only**. For a remote self-hosted deployment, put the app behind a trusted HTTPS reverse proxy with access controls, or use an SSH tunnel. If you deliberately change `SMT_BIND_ADDRESS`, restrict access with a firewall and never expose Basic-auth traffic over plain HTTP.

```bash
# Manual refresh
docker compose run --rm scheduler smt-scheduler --once
```

Note: automatic sync runs in a separate scheduler service. The `web` and `scheduler` services share `./data` and `./logs` directories.

## Configuration

See [`.env.example`](.env.example). The utility account variables `SMT_USERNAME`, `SMT_PASSWORD`, and `SMT_ESIID` are needed for usage retrieval. Application-level Basic authentication additionally needs a username and password unless explicitly delegated to a trusted upstream access gateway.

| Variable | Purpose |
| --- | --- |
| `SMT_USERNAME` / `SMT_PASSWORD` | Smart Meter Texas account credentials |
| `SMT_ESIID` | Electricity service identifier |
| `SMT_WEB_AUTH_ENABLED` | Optional dashboard/API Basic auth switch (default `true`; explicit `false` disables it) |
| `SMT_WEB_USERNAME` / `SMT_WEB_PASSWORD` | Required only if Basic auth is enabled; a missing or weak password prevents app access |
| `SMT_BIND_ADDRESS` | Optional Docker bind host (default `127.0.0.1`) |
| `SMT_TIMEZONE` / `SMT_REFRESH_TIME` | Daily scheduler time zone and local run time |
| `SMT_SAVE_RAW_PAYLOADS` | Optional raw response retention for diagnostics (default `0`, disabled) |

**Configure in the Web UI, not in `.env`:**

- **Energy Cost → Default Electricity Rate:** cents/kWh and monthly fixed fee (fresh-install defaults: `15.0` cents/kWh and `$0`).
- **Weather & HVAC → Weather Location Settings:** US ZIP code or optional latitude/longitude (initially unconfigured).
- **Anomalies & Notifications:** Discord webhook and anomaly score threshold (defaults: no webhook and score `3.5`; automatic alerts are off).

Pricing, weather location, and notification settings are managed in the Web UI and stored in `./data/smt_interval_usage_history.sqlite`. They are intentionally absent from [`.env.example`](.env.example) and do not require a Docker restart when changed. Existing saved settings and historical rate periods persist across updates. **Upgrading from an older version?** If you configured these values only in an old `.env`, re-enter them in the Web UI and check your cost estimates. Back up `./data` before upgrading.

### Anomaly detection and Discord notifications

The Anomalies & Notifications page allows you to save, replace, or remove the Discord webhook, change the anomaly score threshold, send a test message, and opt in to automatic alerts. Settings are saved directly to SQLite; they do not read values from `.env` and do not require a container restart. The webhook URL is never returned by the settings API. Removing a webhook also disables automatic notifications.

Anomaly score is a **Modified Z-score**: `0.6745 × (daily kWh - reference median) / MAD`, where MAD is the median absolute deviation in a reference window of up to 90 days excluding the latest reading. Positive scores mean unusually high usage; negative scores mean unusually low usage. The default `3.5` is a statistical threshold, not a percentage or probability. The detector requires at least 15 daily readings and evaluates the most recent 30 usage days. The threshold is now used for both the dashboard and automatic notification eligibility.

Automatic alerts are **off by default**. Once enabled, successful manual and scheduled syncs check the most recent available usage day (at most two days old), and notify only if its absolute score reaches the threshold. A day is sent at most once; old anomalies are not replayed. Failed HTTP delivery may be retried by a later sync. Avoid entering a shared/public webhook URL and protect local database backups.

The Energy Cost page supports a default cents/kWh rate and fixed monthly fee, both editable directly in the Web UI. The baseline is stored in SQLite and persists across restarts; changing it affects estimates for dates not covered by a more specific rate period. The page also allows multiple date-ranged tariffs stored in SQLite. When tariffs overlap, the matching tariff with the latest start date wins. When a rate changes during a calendar month, the estimated monthly fixed fee is prorated across the calendar days at each rate and allocated to the first available usage day for charting. Actual utility billing rules may differ. Configure the ZIP code or optional latitude/longitude override in the Weather & HVAC page, then select **Refresh Weather History**. Saving a different weather location marks prior weather data as stale and temporarily hides weather-based charts until refreshed. Existing weather records are not deleted.

## Using Cloudflare Zero Trust Access instead of Basic auth

If the app's public hostname is fully protected by a Cloudflare Access application with an email login policy, you can avoid the second browser login:

```env
SMT_WEB_AUTH_ENABLED=false
```

`SMT_WEB_USERNAME` and `SMT_WEB_PASSWORD` can then be left empty or omitted. All dashboard pages and `/api/*` routes (including data-changing POST requests) will bypass **application-level** authentication. The app does **not** verify Cloudflare Access identity tokens; it relies entirely on the gateway.

**Critical:** Protect the entire hostname and every path in Cloudflare Access, including `/api/*`. Ensure there is **no other route to the origin** (public IP:8090, alternate hostname, reverse-proxy route without Access, or exposed LAN port). Ideally publish port 8090 only on loopback when cloudflared is on the same host, or connect cloudflared and the app via a private Docker network. If you use `SMT_BIND_ADDRESS=0.0.0.0`, restrict access with host/network firewalls. This mode is not safe for a directly exposed application.

If you remove `SMT_WEB_AUTH_ENABLED=false` or set it to any unrecognized value, Basic auth is enabled again. The default remains secure and fail-closed.

## Security and privacy

- **Do not commit .env, raw data, consumption logs or credentials.** The project excludes these by default.
- By default, the HTTP API requires Basic authentication on **all routes except `/api/health`**. If explicitly disabled, an upstream access gateway must protect all routes. HTTP Basic credentials must only cross a trusted local channel or HTTPS reverse proxy.
- Docker's published host port defaults to loopback. Do not expose the app directly to untrusted networks.
- SQLite data and state stay inside local `./data`, with restrictive file permissions on POSIX hosts. Raw utility responses are **not saved by default**. Opt in temporarily with `SMT_SAVE_RAW_PAYLOADS=1` or `smt-interval --save-raw-payloads`; files under `./logs/raw-payloads` include meter identifiers and detailed usage. Previously saved logs are not automatically deleted; review and remove them manually when no longer needed.
- Sync CLI/API responses no longer expose ESIID in routine summaries; meter discovery via explicit `--discover-meters` remains sensitive and should be used only in a trusted local shell.
- The application communicates with Smart Meter Texas for meter data, Open-Meteo when weather is refreshed, and Discord when a webhook test or explicitly enabled automatic anomaly alert is sent.
- Keep the optional Discord webhook secret; rotate it if it becomes public.
- This application estimates electricity cost and HVAC-related load; it does not replace a utility bill or a dedicated HVAC meter.

See [SECURITY.md](SECURITY.md) for vulnerability reporting and deployment guidance.

## Development and tests

```bash
python -m pip install -e '.[dev]'
python -m pytest -q
cd frontend && npm ci && npm run build
```

The frontend uses a committed npm lockfile and pinned direct dependency versions. Use `npm ci` for reproducible installs.

## Release and operational checks

For release history, verification evidence, and outstanding operational/provider-access checks, see the [release readiness checklist](docs/RELEASE_CHECKLIST.md). Always back up the local SQLite database, configuration, and private logs before upgrading. The tagged snapshot passed automated Docker CI smoke tests. A full production deployment and Cloudflare Access configuration must be verified separately. Never upload real meter readings or `.env` values into public issue reports.

## License

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0).
