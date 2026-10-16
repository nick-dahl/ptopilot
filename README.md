# ptopilot

PTO-aware flight deal tracker. Tell it your PTO budget, office holiday calendar, rough travel windows, and bucket-list destinations; it builds realistic trips, tracks their prices daily, and emails a twice-weekly digest of the ones priced well below normal.

- Design: [`docs/superpowers/specs/2026-10-16-ptopilot-design.md`](docs/superpowers/specs/2026-10-16-ptopilot-design.md)
- Roadmap: [`ROADMAP.md`](ROADMAP.md)

## Development (Windows)

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
```

### Local database

A private Postgres 17 server lives in `.pgdata/` (git-ignored) on port 5433 with no password, using the binaries from a standard PostgreSQL install. One-time setup:

```powershell
$pg = "C:\Program Files\PostgreSQL\17\bin"
& "$pg\initdb.exe" -D .pgdata -U ptopilot --auth=trust -E UTF8 --locale=C
& "$pg\pg_ctl.exe" -D .pgdata -o "-p 5433" -l .pgdata/server.log start
& "$pg\psql.exe" -h localhost -p 5433 -U ptopilot -d postgres -c "CREATE DATABASE ptopilot" -c "CREATE DATABASE ptopilot_test"
```

After a reboot, start it again with the `pg_ctl ... start` line. Apply migrations to the dev database with `.venv/Scripts/python -m alembic upgrade head`.

### Tests

```powershell
.venv/Scripts/python -m pytest          # database tests skip if the server is down
.venv/Scripts/python -m pytest -m live  # hits real flight sources; run by hand
```

## Daily scan

```powershell
.venv/Scripts/python -m ptopilot.pipeline run --dry-run            # whole pipeline, no health email
.venv/Scripts/python -m ptopilot.pipeline run --stage expand       # one stage (repeatable)
.venv/Scripts/python -m ptopilot.pipeline run --date 2026-10-20    # re-run a past day
```

Stages: `expand → broad_scan → shortlist → live_verify → baselines → score`. Each run is recorded in `pipeline_runs`. A failed `expand` or `broad_scan` stops the rest; a failed `live_verify` does not. In production, `.github/workflows/scan.yml` runs it daily at 06:00 UTC (and on demand from the Actions tab, with optional date/stage inputs); `keepalive.yml` stops GitHub from disabling the schedule.

## Configuration

Environment variables (never committed; GitHub Actions secrets in production):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (Neon in production); defaults to the local dev database |
| `TRAVELPAYOUTS_TOKEN` | Cached fares for the broad scan; without it `broad_scan` is skipped |
| `SERPAPI_KEY` | Live-check fallback (~8 searches/run, 250/month) |
| `RESEND_API_KEY`, `ADMIN_EMAIL` | Health email after each scan |
| `EMAIL_FROM` | Sender; defaults to Resend's shared `onboarding@resend.dev`, which only delivers to your own Resend account address |
