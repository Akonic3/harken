# Deploying Harken on Railway

1. Railway → New Project → Deploy from GitHub repo → pick this fork, branch `kims-saveera` (or `main` after merge).
   Railway builds the `Dockerfile` and uses `railway.json` (health check: `/health`).
2. Add a **Volume** to the service, mount path `/data` (the SQLite DB lives at `/data/harken.db`).
3. Set these **Variables**:

| Variable | Value |
|---|---|
| `RAILWAY_RUN_UID` | `0` (lets the container write to the root-owned volume) |
| `HARKEN_DB` | `/data/harken.db` |
| `HARKEN_AUTH_USERNAME` / `HARKEN_AUTH_PASSWORD` | **required** — hospital data must not be public |
| `HARKEN_SOURCES` | e.g. `rss,reddit,youtube` |
| `HARKEN_RSS_FEEDS` | Google Alerts / news RSS URLs |
| `HARKEN_LLM_PROVIDER` / `ANTHROPIC_API_KEY` | optional, for LLM theme labels |

4. Service → Settings → Networking → Generate Domain. Open it; log in with the Basic-auth pair.
5. Keep a scan running: add a second service (same repo) with start command
   `harken watch "KIMS Saveera" --every 3600`, sharing the same volume — or run scans from the dashboard.

Never deploy without auth set. `HARKEN_AUTH_*` enables HTTP Basic auth (Railway terminates HTTPS for you).
