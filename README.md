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

## Traveler profiles

Until the web app's onboarding exists, travelers are loaded from YAML:

```powershell
copy profiles\example.yaml profiles\me.yaml                       # profiles/* is git-ignored (holds your email)
.venv/Scripts/python -m ptopilot.profiles load profiles/me.yaml --dry-run   # validate and preview
.venv/Scripts/python -m ptopilot.profiles load profiles/me.yaml             # save (re-run any time to update)
```

Destinations must exist in `ptopilot/data/geo.yaml` (with season ratings in `seasons.yaml`). A destination with `return_airports` is an **open-jaw** route (fly into one airport, home from another); only SerpApi can price those. Live checks skip departures more than ~300 days out (Google Flights doesn't search that far yet).

## Daily scan

```powershell
.venv/Scripts/python -m ptopilot.pipeline run --dry-run            # whole pipeline, no emails (alerts report what they would send)
.venv/Scripts/python -m ptopilot.pipeline run --stage expand       # one stage (repeatable)
.venv/Scripts/python -m ptopilot.pipeline run --date 2026-10-20    # re-run a past day
```

A dry run still makes real return-flight searches, but only with free sources, and they don't use the real run's daily return-check allowance or any SerpApi searches.

Stages: `expand → broad_scan → shortlist → seed_history → live_verify → baselines → score → related → alerts`. Each run is recorded in `pipeline_runs`. A failed `expand` or `broad_scan` stops the rest; a failed `seed_history`, `live_verify`, `related` or `alerts` does not. In production, `.github/workflows/scan.yml` runs it daily at 06:00 UTC (and on demand from the Actions tab, with optional date/stage inputs); `keepalive.yml` stops GitHub from disabling the schedule.

## Neon (production database)

The repo is linked to Neon project `green-feather-91450838`, branch `production` (`.neon`, git-ignored; `neon.ts` declares the services: Postgres only). After `neon login`, `neon env pull` writes `DATABASE_URL` (pooled) and `DATABASE_URL_UNPOOLED` (direct) to `.env.local` (git-ignored). Use the direct URL for migrations. The `DATABASE_URL` GitHub secret holds the direct URL, because the scan job runs migrations before the pipeline.

## Digest

```powershell
.venv/Scripts/python -m ptopilot.digest send --preview out/                 # write each digest to out/*.html + .txt
.venv/Scripts/python -m ptopilot.digest send --preview out/ --min-level none # include trips that aren't deals yet (tuning)
.venv/Scripts/python -m ptopilot.digest send                                 # email them (needs RESEND_API_KEY)
```

`.github/workflows/digest.yml` sends on Mondays and Thursdays at 12:00 UTC, after the morning scan. A digest with no deals ("quiet week") only goes out on Mondays. Run it by hand from the Actions tab with `min_level: none` to get a tuning email built from every priced trip. Tuning emails go only to `ADMIN_EMAIL` and never count as "already sent". Without a verified sending domain, Resend only delivers to the Resend account's own address; a send to anyone else fails, is logged, and the run exits red while the other digests still go out.

## Web app

```powershell
$env:SECRET_KEY = "local-dev-key"
.venv/Scripts/python -m uvicorn ptopilot.web.main:app --reload --port 8000   # http://127.0.0.1:8000
.venv/Scripts/python -m ptopilot.profiles invite you@example.com            # only invited emails can sign in
```

The site's scripts are small vanilla JavaScript modules in `ptopilot/web/static/` with no build step; every form also works without JavaScript. The stylesheet URL carries a hash of its contents, so browsers pick up a new `app.css` after each deploy.

Sign-in is by emailed link (valid 15 minutes). Without `RESEND_API_KEY` the server logs the link instead, which is handy locally. Signed-in travelers get a dashboard (trackers, best current prices, snooze), a profile page for traveler settings, `/plan` for open date ranges, PTO and trips by year, and `/destinations` for places. `profiles load` still works for bulk setup: it updates only the years and trackers the file lists and leaves everything else alone. With `APP_BASE_URL` and `SECRET_KEY` set, digests get snooze buttons that open a confirmation page in the app. They only act when you press Confirm, because mail scanners pre-open links.

### Deploying (Render, free tier)

1. Render dashboard → **New → Blueprint** → connect this GitHub repo. `render.yaml` defines the service.
2. Fill in the environment variables it asks for: `DATABASE_URL` (Neon **pooled** URL), `SECRET_KEY` (the same value as the GitHub secret), `RESEND_API_KEY`, `EMAIL_FROM` (optional), `APP_BASE_URL` (the service's own `https://….onrender.com` URL).
3. Set the GitHub variable `APP_BASE_URL` to the same URL so the digest links to it: `gh variable set APP_BASE_URL`.

The free service sleeps after ~15 idle minutes; the first request after that takes ~30–60 s.

## Configuration

Environment variables (never committed; GitHub Actions secrets in production):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres URL (Neon in production); defaults to the local dev database |
| `TRAVELPAYOUTS_TOKEN` | Cached fares for the broad scan; without it `broad_scan` is skipped |
| `SERPAPI_KEY` | Live-check fallback (~8 searches/run, 250/month) |
| `RESEND_API_KEY`, `ADMIN_EMAIL` | Health email after each scan |
| `EMAIL_FROM` | Sender; defaults to Resend's shared `onboarding@resend.dev`, which only delivers to your own Resend account address |
| `SECRET_KEY` | Signs sign-in links, sessions and snooze links; must be identical for the web app and the digest job |
| `APP_BASE_URL` | Public URL of the web app; turns on snooze buttons in the digest (a GitHub *variable* for the workflow) |
