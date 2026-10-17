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
    }
    assert needed <= job_env("scan.yml")
