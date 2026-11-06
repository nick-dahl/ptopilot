"""Scheduled workflows must pass every setting their CLI reads; a missing one only shows up in production."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def job_env(name: str) -> set[str]:
    workflow = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    [job] = workflow["jobs"].values()
    return set(job.get("env", {}))


def test_digest_workflow_passes_everything_the_digest_reads():
    needed = {
        "DATABASE_URL",
        "RESEND_API_KEY",
        "EMAIL_FROM",
        "ADMIN_EMAIL",
        "SECRET_KEY",
        "APP_BASE_URL",
        "MIN_LEVEL",
    }
    assert needed <= job_env("digest.yml")


def test_scan_workflow_passes_everything_the_scan_reads():
    needed = {
        "DATABASE_URL",
        "TRAVELPAYOUTS_TOKEN",
        "SERPAPI_KEY",
        "RESEND_API_KEY",
        "ADMIN_EMAIL",
        "EMAIL_FROM",
        "SECRET_KEY",  # instant alerts carry snooze links, like the digest
        "APP_BASE_URL",
    }
    assert needed <= job_env("scan.yml")


def test_scan_workflow_offers_every_stage():
    from ptopilot.pipeline.runner import STAGES

    workflow = yaml.safe_load((WORKFLOWS / "scan.yml").read_text(encoding="utf-8"))
    options = workflow[True]["workflow_dispatch"]["inputs"]["stage"]["options"]
    assert set(STAGES) <= set(options)


# keepalive.yml commits and pushes a heartbeat file, so it alone needs write access.
PERMISSION_EXCEPTIONS = {"keepalive.yml": {"contents": "write"}}


def _workflows():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        yield path.name, yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_workflow_is_read_only():
    for name, workflow in _workflows():
        expected = PERMISSION_EXCEPTIONS.get(name, {"contents": "read"})
        assert workflow.get("permissions") == expected, name


def test_no_workflow_splices_inputs_into_shell():
    for name, workflow in _workflows():
        for job in workflow["jobs"].values():
            for step in job["steps"]:
                run = step.get("run", "")
                assert "${{ inputs." not in run, name
                assert "${{ github.event.inputs." not in run, name


def test_scan_runs_three_times_a_day():
    workflow = yaml.safe_load((WORKFLOWS / "scan.yml").read_text(encoding="utf-8"))
    crons = [entry["cron"] for entry in workflow[True]["schedule"]]
    assert crons == ["0 6 * * *", "0 14 * * *", "0 22 * * *"]
