"""Runs stages in order, records each in pipeline_runs, and applies the failure rules (spec §10)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ptopilot.db.models import PipelineRun
from ptopilot.db.session import session_scope
from ptopilot.pipeline import (
    alerts,
    baselines,
    broad_scan,
    expand,
    live_verify,
    photos,
    related,
    score,
    seed_history,
    shortlist,
)
from ptopilot.pipeline.context import RunContext, StageFailed, StageSkipped
from ptopilot.sources.base import snippet

log = logging.getLogger(__name__)

STAGES: dict[str, Callable[[RunContext], dict[str, int]]] = {
    "expand": expand.run,
    "broad_scan": broad_scan.run,
    "shortlist": shortlist.run,
    "seed_history": seed_history.run,
    "live_verify": live_verify.run,
    "baselines": baselines.run,
    "score": score.run,
    "related": related.run,
    "photos": photos.run,
    "alerts": alerts.run,
}
# A failure here still lets later stages run on whatever data exists (cached or unverified prices).
# `related` and `photos` are extras: their failure never holds back the alerts. `alerts` runs last, so its
# failure only matters for the health report.
CONTINUE_ON_FAILURE = frozenset({"seed_history", "live_verify", "related", "photos", "alerts"})


@dataclass
class StageResult:
    stage: str
    status: str  # ok | skipped | failed | not_run
    counts: dict[str, int] = field(default_factory=dict)
    error: str | None = None


def run_stage(ctx: RunContext, name: str) -> StageResult:
    with session_scope(ctx.engine) as s:
        row = PipelineRun(run_date=ctx.run_date, stage=name, status="running")
        s.add(row)
        s.flush()
        run_id = row.id
    try:
        result = StageResult(name, "ok", STAGES[name](ctx))
    except StageSkipped as exc:
        result = StageResult(name, "skipped", error=str(exc))
    except StageFailed as exc:
        result = StageResult(name, "failed", error=snippet(str(exc), 1000))
    except Exception as exc:
        log.exception("stage %s crashed", name)
        result = StageResult(name, "failed", error=snippet(f"{type(exc).__name__}: {exc}", 1000))
    with session_scope(ctx.engine) as s:
        row = s.get(PipelineRun, run_id)
        row.status, row.counts, row.error = result.status, result.counts, result.error
        row.finished_at = datetime.now(UTC)
    log.info("stage %s: %s %s %s", name, result.status, result.counts, result.error or "")
    return result


def run_pipeline(ctx: RunContext, stages: Sequence[str] | None = None) -> list[StageResult]:
    names = list(stages or STAGES)
    unknown = [n for n in names if n not in STAGES]
    if unknown:
        raise ValueError(f"unknown stage(s) {unknown}; choose from {list(STAGES)}")
    results: list[StageResult] = []
    for i, name in enumerate(names):
        result = run_stage(ctx, name)
        results.append(result)
        if result.status == "failed" and name not in CONTINUE_ON_FAILURE:
            results.extend(StageResult(n, "not_run") for n in names[i + 1 :])
            break
    return results
