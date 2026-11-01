# Pre-invite Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the code items on the ROADMAP §2 "Before inviting friends" checklist so friends can be invited safely.

**Architecture:** Five independent fixes. The digest's per-person loop isolates every failure; a new last pipeline stage, `prune`, applies a retention rule to `price_observations`; the runner times every stage, and runs killed by GitHub are marked `interrupted` and reported; the scan and CI workflows get least-privilege `permissions` and stop splicing inputs into shell; the session cookie carries the email encrypted, and production refuses to start without an https `APP_BASE_URL`.

**Tech Stack:** Python 3.12, SQLAlchemy 2, FastAPI/Starlette `SessionMiddleware`, GitHub Actions, pytest against local Postgres; new dependency `cryptography` (Fernet).

**Spec:** `ROADMAP.md` §2 (the checklist items quoted in each task). Owner decisions, 2026-11-01: price data is kept until 90 days after the trip departs, and nothing older than 13 months; the Resend domain item stays open until the owner buys a domain (not in this plan); the signed-in check of the live planner is done with the owner after this plan ships (not in this plan).

## Global Constraints

- The repo is public: no emails, keys or personal data in code, fixtures or commits (tests use `@example.com`).
- No database migration in this plan (`pipeline_runs.status` is a free `String(16)`; `interrupted` fits).
- Tests run in the foreground with `timeout 300` (one file) or `timeout 900` (full suite), logged to a file whose tail you read; never two pytest runs at once.
- Commit as soon as the task's focused tests pass; stage files by explicit path; commit trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; push to `main`.
- Match the surrounding code: module docstrings, short comments explaining why, constants in `ptopilot/config.py`.

## Review Focus

1. A digest whose *render* raises (a bad card, a template bug) must skip that person only; the others still go out. → Task 1 `test_a_render_crash_skips_only_that_person`.
2. A database error *after* an email went out must not stop the remaining people, and must exit non-zero so the run shows red. → Task 1 `test_a_record_failure_after_sending_keeps_going`.
3. Month-only observations (`depart_date` NULL, cached fares) must follow the same retention rule by their month, never be deleted while the month is still upcoming. → Task 2 `test_month_only_rows_are_kept_until_their_month_is_long_past`.
4. A candidate pointing at a pruned observation must survive (its FK is `SET NULL`) and the digest/destination page must still render it. → Task 2 `test_pruning_keeps_candidates`.
5. An old cookie from before this change (plain `email` key) must read as signed out, not crash or sign anyone in. → Task 5 `test_an_old_plain_email_cookie_is_signed_out`.

---

### Task 1: One person's digest failure never stops the others

ROADMAP: "One person's digest failure stops the others. Only email failures are isolated today. A database hiccup right after sending could also cause one repeat send."

**Files:**
- Modify: `ptopilot/digest/send.py` (`deliver`)
- Modify: `ptopilot/digest/__main__.py` (exit code)
- Test: `tests/digest/test_send.py`

**Interfaces:**
- Produces: `deliver(...)` keeps its signature; new counter keys `"failed"` (render or email failed; nothing sent) and `"record_failed"` (sent, but recording it failed after one retry).

- [ ] **Step 1: Write the failing tests** in `tests/digest/test_send.py`, using the file's existing digest/emailer fixtures:
  - `test_a_render_crash_skips_only_that_person`: two digests; monkeypatch `ptopilot.digest.send.render` to raise `RuntimeError` for the first user only. Assert the second email was sent, `counts["failed"] == 1`, `counts["sent"] == 1`.
  - `test_a_record_failure_after_sending_keeps_going`: two digests; make `session_scope` used by `deliver` raise `OperationalError` on every call for the first user (monkeypatch a wrapper keyed on `digest.user_id`). Assert both emails were sent, `counts["record_failed"] == 1`, `counts["sent"] == 2`.
  - `test_a_record_failure_is_retried_once`: the recording raises once, then succeeds. Assert a `DigestSend` row exists for that user and `"record_failed"` is not in counts.
  - `test_digest_cli_exits_1_when_a_record_failed` in the same file (or `tests/digest/` CLI test if one exists): `main()` returns 1 when `deliver` returns `record_failed=1`.
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/digest/test_send.py -q > $LOG 2>&1; tail -5 $LOG` — Expected: the four new tests FAIL.
- [ ] **Step 3: Implement.** In `deliver`, wrap `render` (with `emailer.send`) so any `Exception` counts `failed`, logs `log.exception("digest for user %s not sent", user_id)` and continues. Move the recording into a helper `_record(engine, digest, deals) -> None`; call it, on any `SQLAlchemyError` retry once, and on a second failure count `record_failed` and `log.exception(...)` saying the deals may be sent again next time. `sent`/`deals_sent` count when the email went out. Update `deliver`'s docstring. In `__main__.py`, return 1 if `counts["failed"] or counts["record_failed"]`.
- [ ] **Step 4: Run** the same command — Expected: all of `tests/digest/test_send.py` PASS; then `timeout 300 .venv/Scripts/python -m pytest tests/digest -q` PASS.
- [ ] **Step 5: Commit** `git add ptopilot/digest/send.py ptopilot/digest/__main__.py tests/digest/test_send.py` — message `digest: one person's failure never stops the others`.

### Task 2: A retention rule for old price data (`prune` stage)

ROADMAP: "A rule for deleting old price data. Price observations grow without limit." Owner rule: delete observations for trips that departed more than 90 days ago, and anything observed more than 13 months ago.

**Files:**
- Create: `ptopilot/pipeline/prune.py`
- Modify: `ptopilot/config.py`, `ptopilot/pipeline/runner.py` (`STAGES`, `CONTINUE_ON_FAILURE`), `ptopilot/db/models.py` (`PriceObservation` docstring only), `.github/workflows/scan.yml` (stage choice list gains `prune`)
- Test: `tests/pipeline/test_prune.py`

**Interfaces:**
- Produces: `config.PRICE_KEEP_AFTER_DEPARTURE_DAYS = 90`, `config.PRICE_KEEP_MAX_DAYS = 395  # about 13 months`; `prune.run(ctx: RunContext) -> dict[str, int]` returning `{"deleted": n}`; stage name `"prune"`, registered last (after `alerts`) and in `CONTINUE_ON_FAILURE`.

- [ ] **Step 1: Write the failing tests** in `tests/pipeline/test_prune.py` (use `tests/pipeline/conftest.py`'s engine/context helpers; run date `2026-11-01`):
  - `test_departed_more_than_90_days_ago_is_deleted`: rows with `depart_date` 2026-08-02 (91 days before) deleted; 2026-08-03 (90 days) and any future date kept; `run(ctx) == {"deleted": 1}`.
  - `test_anything_observed_over_13_months_ago_is_deleted`: a future-departure row with `observed_at` 396 days before the run date is deleted; one at 395 days is kept.
  - `test_month_only_rows_are_kept_until_their_month_is_long_past`: `depart_date=None`; `month=2026-07-01` deleted (whole month ended more than 90 days before), `month=2026-08-01` kept, `month=2027-01-01` kept.
  - `test_pruning_keeps_candidates`: a `Candidate` pointing at a deleted observation still exists with `price_observation_id is None`.
  - `test_prune_runs_last_and_never_blocks`: `list(STAGES)[-1] == "prune"` and `"prune" in CONTINUE_ON_FAILURE`.
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_prune.py -q` — Expected: FAIL (`No module named ptopilot.pipeline.prune`).
- [ ] **Step 3: Implement** `prune.run` as one `DELETE` on `price_observations` where `(depart_date IS NOT NULL AND depart_date < cutoff) OR (depart_date IS NULL AND month < month_of(cutoff)) OR observed_at < start_of(run_date - PRICE_KEEP_MAX_DAYS)`, with `cutoff = run_date - PRICE_KEEP_AFTER_DEPARTURE_DAYS`; module docstring states the rule and why (the scoring and charts read at most ~60 days back; a trip's own history matters until it departs). In dry runs (`ctx.dry_run`) count matching rows instead of deleting and return `{"would_delete": n}`. Register the stage, add `prune` to `scan.yml`'s stage options, and change the `PriceObservation` docstring to "Every price seen. Append-only: never update rows; only the prune stage deletes, by its retention rule."
- [ ] **Step 4: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_prune.py tests/pipeline/test_runner.py tests/test_workflows.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** the five files plus the test — message `pipeline: prune stage deletes price data past its retention rule`.

### Task 3: Stage durations in the health email, and runs GitHub kills

ROADMAP: "Health email: add per-stage durations (the spec asks for them). If GitHub kills a run, its stages stay marked 'running' and no health email goes out."

**Files:**
- Modify: `ptopilot/pipeline/runner.py` (`StageResult`, `run_stage`, `run_pipeline`), `ptopilot/pipeline/health.py` (`build_report`, new `interrupted_report`), `ptopilot/pipeline/__main__.py` (new `interrupted` command), `.github/workflows/scan.yml` (a cancelled-run step)
- Test: `tests/pipeline/test_runner.py`, `tests/pipeline/test_audit.py` (or the file holding `build_report` tests)

**Interfaces:**
- Produces: `StageResult.seconds: float | None = None`; `runner.mark_interrupted(engine) -> list[PipelineRun]` (sets every `status == "running"` row to `"interrupted"`, `finished_at = now`, `error = "the run was stopped before this stage finished"`, returns them); `health.interrupted_report(rows) -> tuple[str, str]`; CLI `python -m ptopilot.pipeline interrupted [--dry-run]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_each_stage_result_has_its_duration` (runner): a fake stage that advances an injected clock 42 s; `results[0].seconds == 42`. Inject the clock as a module-level `monotonic = time.monotonic` in `runner.py` that the test monkeypatches.
  - `test_health_report_shows_durations` (health): a result with `seconds=125.4` renders `2m05s` on its stage line; `seconds=8.2` renders `8s`; `None` renders nothing.
  - `test_a_new_run_marks_leftover_running_stages_interrupted` (runner): a `PipelineRun(status="running")` from a previous date; after `run_pipeline`, it is `interrupted` with the error text above, and the health report's body contains `Interrupted earlier: <date> <stage>`.
  - `test_interrupted_command_marks_and_emails` (CLI): one `running` row; `main(["interrupted"])` marks it, sends one email to the admin whose subject is `ptopilot scan <date>: INTERRUPTED (<stage>)`, and returns 1; with no `running` rows it sends nothing and returns 0.
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/pipeline/test_runner.py tests/pipeline/test_audit.py -q` — Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Time each stage in `run_stage` and set `seconds`. At the start of `run_pipeline`, call `mark_interrupted` and keep the rows on the returned results' report path (pass them to `build_report` via a new keyword `interrupted: Sequence[PipelineRun] = ()`; one line each under "Stages:"). Duration format: under 60 s `"{s:.0f}s"`, otherwise `"{m}m{s:02.0f}s"`. Add the `interrupted` subcommand, reusing `build_context` and `ctx.emailer`/`ctx.admin_email` like `send_report` (dry run prints only). In `scan.yml`, after "Run pipeline", add a step `name: Report a cancelled run`, `if: cancelled()`, `run: python -m ptopilot.pipeline interrupted`.
- [ ] **Step 4: Run** the same command plus `tests/test_workflows.py` — Expected: PASS.
- [ ] **Step 5: Commit** — message `health: stage durations, and runs GitHub kills are reported`.

### Task 4: Harden the workflows

ROADMAP: "Harden the scan workflow: its manual-run inputs go into a shell command unescaped; `scan.yml` has no `permissions:` block."

**Files:**
- Modify: `.github/workflows/scan.yml`, `.github/workflows/ci.yml`
- Test: `tests/test_workflows.py`

- [ ] **Step 1: Write the failing tests** in `tests/test_workflows.py`:
  - `test_every_workflow_is_read_only`: every `*.yml` in `.github/workflows` has top-level `permissions == {"contents": "read"}`.
  - `test_no_workflow_splices_inputs_into_shell`: no step's `run:` text in any workflow contains `${{ inputs.` or `${{ github.event.inputs.`.
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/test_workflows.py -q` — Expected: both FAIL (scan.yml, ci.yml).
- [ ] **Step 3: Implement.** Add `permissions: contents: read` to `scan.yml` and `ci.yml` (same placement as `digest.yml`). In `scan.yml`, pass the inputs through the job or step `env` (`RUN_DATE: ${{ inputs.date }}`, `RUN_STAGE: ${{ inputs.stage }}`, with the digest workflow's comment "passed via env, never spliced into the shell script") and use `"$RUN_DATE"` / `"$RUN_STAGE"` in the script.
- [ ] **Step 4: Run** the same command — Expected: PASS.
- [ ] **Step 5: Commit** — message `workflows: read-only permissions; inputs via env`.

### Task 5: Encrypted session cookie, https in production, and the snooze-link note

ROADMAP: "Session cookie. It is signed but not encrypted, so the email inside is readable as base64. And if `APP_BASE_URL` were unset in production, the cookie would lose its https-only flag." and "README note: snooze links work for anyone holding them for 30 days, so forwarding a digest forwards them."

**Files:**
- Modify: `pyproject.toml` (add `"cryptography>=43"`), `ptopilot/web/app.py` (sign-in, `current_email`, sign-out), `ptopilot/web/main.py`, `README.md`, `ROADMAP.md`
- Test: `tests/web/test_hardening.py`

**Interfaces:**
- Produces: in `ptopilot/web/app.py`, `SESSION_KEY = "who"` and helpers `seal_email(secret_key: str, email: str) -> str`, `open_email(secret_key: str, token: str) -> str | None` (Fernet with key `urlsafe_b64encode(sha256(b"ptopilot-session:" + secret_key.encode()).digest())`; `None` on any `InvalidToken`); in `ptopilot/web/main.py`, `check_production(settings: Settings, env: Mapping[str, str]) -> None` raising `SystemExit` with the message `APP_BASE_URL must be the site's https:// URL in production` when `env.get("RENDER")` is set and `settings.app_base_url` does not start with `https://`.

- [ ] **Step 1: Write the failing tests** in `tests/web/test_hardening.py`:
  - `test_the_session_cookie_does_not_reveal_the_email`: after `sign_in`, base64-decode the payload part of `client.cookies["ptopilot_session"]` (before the first `.`) and assert `b"nick@example.com"` is not in it; the dashboard still loads signed in.
  - `test_an_old_plain_email_cookie_is_signed_out`: set `request.session["email"]` via a cookie signed with the same key in Starlette's format (build it with `itsdangerous.TimestampSigner(KEY).sign(b64encode(json.dumps({"email": "nick@example.com"}).encode()))`); `/` shows the signed-out page.
  - `test_a_tampered_session_is_signed_out`: `open_email(KEY, "garbage") is None`.
  - `test_production_requires_an_https_base_url`: `check_production(Settings(database_url="x", app_base_url=""), {"RENDER": "true"})` raises `SystemExit`; with `app_base_url="https://ptopilot.onrender.com"` it does not; with `{}` and an empty URL it does not (local dev).
- [ ] **Step 2: Run** `timeout 300 .venv/Scripts/python -m pytest tests/web/test_hardening.py -q` — Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** `.venv/Scripts/pip install -e .` after adding the dependency. Sign-in stores `request.session[SESSION_KEY] = seal_email(...)`; `current_email` reads it with `open_email` (and clears the session when it is unreadable or the invite is gone); the `page()` helper's `signed_in` uses `current_email`. Nothing else reads `session["email"]` (grep to confirm). In `main.py`, call `check_production(settings, os.environ)` before `create_app`. In `README.md`'s sign-in paragraph, add after the snooze sentence: "Snooze links work for anyone holding them for 30 days, so forwarding a digest forwards them." In `ROADMAP.md` §2, tick the five items this plan closes and leave the Resend domain and signed-in planner items open.
- [ ] **Step 4: Run** `timeout 300 .venv/Scripts/python -m pytest tests/web -q` — Expected: PASS. Then the full suite, `timeout 900 .venv/Scripts/python -m pytest -q -p no:randomly`, PASS.
- [ ] **Step 5: Commit** — message `web: encrypted session cookie; production requires https`.

**Deploy note (controller, after Task 5):** Render redeploys on push and reinstalls dependencies; the owner's existing session ends once (old cookie), so they sign in again. No migration is needed.
