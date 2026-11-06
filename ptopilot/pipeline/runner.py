"""Runs stages in order, records each in pipeline_runs, and applies the failure rules (spec §10)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine, select

from ptopilot.db.models import PipelineRun
from ptopilot.db.session import session_scope
from ptopilot.pipeline import (
    alerts,
    baselines,
    broad_scan,
    expand,
    gems,
    live_verify,
    photos,
    prune,
    related,
    score,
    seed_history,
    shortlist,
)
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.sources.base import snippet

log = logging.getLogger(__name__)

monotonic = time.monotonic  # tests replace this to fake a stage's duration
INTERRUPTED_ERROR = "the run was stopped before this stage finished"

STAGES: dict[str, Callable[[RunContext], dict[str, int]]] = {
    "expand": expand.run,
    "broad_scan": broad_scan.run,
    "shortlist": shortlist.run,
    "seed_history": seed_history.run,
    "live_verify": live_verify.run,
    "baselines": baselines.run,
    "score": score.run,
    "related": related.run,
    "gems": gems.run,
    "photos": photos.run,
    "alerts": alerts.run,
    "prune": prune.run,
}
# A failure here still lets later stages run on whatever data exists (cached or unverified prices).
# `related`, `gems` and `photos` are extras: their failure never holds back the alerts. `alerts` runs last,
# so its failure only matters for the health report. `prune` is housekeeping and never blocks anything.
CONTINUE_ON_FAILURE = frozenset(
    {"seed_history", "live_verify", "related", "gems", "photos", "alerts", "prune"}
)
# Stages whose work is for the whole day: after one ok run, the day's later scan runs skip them.
ONCE_A_DAY = frozenset({"expand", "broad_scan", "seed_history", "related", "gems", "photos", "prune"})
ALREADY_RAN = "already ran today"


@dataclass
class StageResult:
    stage: str
    status: str  # ok | skipped | failed | not_run
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    seconds: float | None = None


def mark_interrupted(engine: Engine) -> list[PipelineRun]:
    """Stages still 'running' belong to a run GitHub killed (timeout or cancel); close them out."""
    with session_scope(engine) as s:
        rows = list(s.scalars(select(PipelineRun).where(PipelineRun.status == "running")))
        for row in rows:
            row.status, row.error, row.finished_at = "interrupted", INTERRUPTED_ERROR, datetime.now(UTC)
    return rows


def run_stage(ctx: RunContext, name: str) -> StageResult:
    with session_scope(ctx.engine) as s:
        row = PipelineRun(run_date=ctx.run_date, stage=name, status="running")
        s.add(row)
        s.flush()
        run_id = row.id
    started = monotonic()
    try:
        result = StageResult(name, "ok", STAGES[name](ctx))
    except StageSkipped as exc:
        result = StageResult(name, "skipped", error=str(exc))
    except StageFailed as exc:
        result = StageResult(name, "failed", error=snippet(str(exc), 1000))
    except Exception as exc:
        log.exception("stage %s crashed", name)
        result = StageResult(name, "failed", error=snippet(f"{type(exc).__name__}: {exc}", 1000))
    result.seconds = monotonic() - started
    with session_scope(ctx.engine) as s:
        row = s.get(PipelineRun, run_id)
        # A dry run's rows must never count as 'ran today' for the real run that follows.
        row.status = "dry_run" if ctx.dry_run and result.status == "ok" else result.status
        row.counts, row.error = result.counts, result.error
        row.finished_at = datetime.now(UTC)
    log.info("stage %s: %s %s %s", name, result.status, result.counts, result.error or "")
    return result


def _ran_today(ctx: RunContext, name: str) -> bool:
    with session_scope(ctx.engine) as s:
        return (
            s.scalar(
                select(PipelineRun.id)
                .where(PipelineRun.run_date == ctx.run_date, PipelineRun.stage == name)
                .where(PipelineRun.status == "ok")
                .limit(1)
            )
            is not None
        )


def run_pipeline(ctx: RunContext, stages: Sequence[str] | None = None) -> list[StageResult]:
    names = list(stages or STAGES)
    unknown = [n for n in names if n not in STAGES]
    if unknown:
        raise ValueError(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")
    results: list[StageResult] = []
    for i, name in enumerate(names):
        # A manual `--stage` run always runs what it names.
        if stages is None and name in ONCE_A_DAY and _ran_today(ctx, name):
            results.append(StageResult(name, "skipped", error=ALREADY_RAN))
            continue
        result = run_stage(ctx, name)
        results.append(result)
        if result.status == "failed" and name not in CONTINUE_ON_FAILURE:
            results.extend(StageResult(n, "not_run") for n in names[i + 1 :])
            break
    return results
