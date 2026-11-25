"""Validation runs, results, overview metrics, CI trigger API and the internal runner API."""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import serialize as S
from ..db import get_db
from ..models import (GitIntegration, Project, Requirement, TestCase, TestExecution, User,
                      ValidationRun)
from ..security import any_user, get_ci_integration, require_runner, writer
from ..services.validation import FINAL_STATES, create_run, finalize_run

router = APIRouter(prefix="/api", tags=["runs"])
SHA_RE = r"^[0-9a-f]{40}$"
MAX_LOG = 200_000


def _project_git(db: Session, pid: int) -> tuple[Project, GitIntegration]:
    p = db.get(Project, pid)
    if not p:
        raise HTTPException(404, "Project not found")
    if not p.git:
        raise HTTPException(400, "Connect a Git repository to this project first (CI/CD Integration)")
    return p, p.git


# --- Manual runs ---------------------------------------------------------------
class ManualRunIn(BaseModel):
    test_case_id: int | None = None
    commit_sha: str | None = Field(default=None, pattern=SHA_RE)


@router.post("/projects/{pid}/runs", status_code=201)
def start_manual_run(pid: int, body: ManualRunIn, db: Session = Depends(get_db), user: User = Depends(writer)):
    p, gi = _project_git(db, pid)
    if body.test_case_id is not None:
        tc = db.get(TestCase, body.test_case_id)
        if not tc or tc.project_id != pid:
            raise HTTPException(400, "Test case does not belong to this project")
    run, _ = create_run(db, p, gi, trigger="manual", created_by=user.username,
                        commit_sha=body.commit_sha, test_case_id=body.test_case_id)
    if run.status == "ERROR":
        raise HTTPException(409, run.message)
    return S.run(run)


@router.get("/projects/{pid}/runs")
def list_runs(pid: int, status: str = "", commit: str = "", limit: int = 50,
              db: Session = Depends(get_db), _: User = Depends(any_user)):
    stmt = select(ValidationRun).where(ValidationRun.project_id == pid)
    if status:
        stmt = stmt.where(ValidationRun.status == status)
    if commit:
        stmt = stmt.where(ValidationRun.commit_sha.like(f"{commit}%"))
    stmt = stmt.order_by(ValidationRun.id.desc()).limit(min(max(limit, 1), 500))
    return [S.run(r) for r in db.scalars(stmt)]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    r = db.get(ValidationRun, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    return S.run(r, with_executions=True, with_logs=True)


@router.get("/projects/{pid}/executions")
def list_executions(pid: int, requirement_id: int | None = None, test_case_id: int | None = None,
                    commit: str = "", verdict: str = "", limit: int = 200,
                    db: Session = Depends(get_db), _: User = Depends(any_user)):
    stmt = select(TestExecution).join(ValidationRun).where(ValidationRun.project_id == pid)
    if requirement_id:
        stmt = stmt.where(TestExecution.requirement_id == requirement_id)
    if test_case_id:
        stmt = stmt.where(TestExecution.test_case_id == test_case_id)
    if commit:
        stmt = stmt.where(ValidationRun.commit_sha.like(f"{commit}%"))
    if verdict:
        stmt = stmt.where(TestExecution.status == verdict)
    stmt = stmt.order_by(TestExecution.id.desc()).limit(min(max(limit, 1), 1000))
    out = []
    for e in db.scalars(stmt):
        r = e.run
        out.append(S.execution(e, with_log=False) | {
            "repo_url": r.repo_url, "branch": r.branch, "commit_sha": r.commit_sha,
            "trigger": r.trigger, "quality_gate": r.quality_gate, "run_status": r.status})
    return out


# --- Overview ------------------------------------------------------------------
@router.get("/projects/{pid}/overview")
def overview(pid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    total_req = db.scalar(select(func.count()).select_from(Requirement).where(Requirement.project_id == pid))
    total_tc = db.scalar(select(func.count()).select_from(TestCase).where(TestCase.project_id == pid))
    mapped = db.scalar(select(func.count(func.distinct(TestCase.requirement_id)))
                       .where(TestCase.project_id == pid))
    full_runs = (select(ValidationRun).where(ValidationRun.project_id == pid,
                                             ValidationRun.scope_test_case_id.is_(None),
                                             ValidationRun.status.in_(FINAL_STATES),
                                             ValidationRun.total > 0))
    latest = db.scalar(full_runs.order_by(ValidationRun.id.desc()).limit(1))
    last_passed = db.scalar(full_runs.where(ValidationRun.quality_gate == "PASSED")
                            .order_by(ValidationRun.id.desc()).limit(1))
    executed_reqs = 0
    if latest:
        executed_reqs = len({e.requirement_id for e in latest.executions if e.status in FINAL_STATES})
    history = list(db.scalars(full_runs.order_by(ValidationRun.id.desc()).limit(30)))
    recent = db.scalars(select(TestExecution).join(ValidationRun)
                        .where(ValidationRun.project_id == pid, TestExecution.status.in_(FINAL_STATES))
                        .order_by(TestExecution.id.desc()).limit(10))
    active = db.scalar(select(func.count()).select_from(ValidationRun).where(
        ValidationRun.project_id == pid, ValidationRun.status.in_(("QUEUED", "RUNNING"))))
    pct = lambda a, b: round(100.0 * a / b, 1) if b else 0.0  # noqa: E731
    return {
        "total_requirements": total_req, "total_test_cases": total_tc,
        "mapped_requirements": mapped, "mapping_coverage": pct(mapped, total_req),
        "executed_requirements": executed_reqs, "execution_coverage": pct(executed_reqs, total_req),
        "pass_rate": pct(latest.passed, latest.total) if latest else None,
        "latest_run": S.run(latest) if latest else None,
        "last_passing_run": S.run(last_passed) if last_passed else None,
        "active_runs": active,
        "recent_executions": [S.execution(e, with_log=False) | {"commit_sha": e.run.commit_sha}
                              for e in recent],
        "history": [{"id": r.id, "commit_sha": r.commit_sha, "status": r.status,
                     "quality_gate": r.quality_gate, "trigger": r.trigger, "passed": r.passed,
                     "total": r.total, "created_at": S._dt(r.created_at)} for r in reversed(history)],
    }


# --- CI API (authenticated by per-project CI token) ------------------------------
class CiTriggerIn(BaseModel):
    commit_sha: str = Field(pattern=SHA_RE)
    branch: str = Field(pattern=r"^[A-Za-z0-9._/-]{1,128}$")
    repository: str = Field(default="", max_length=256)
    event_id: str = Field(default="", max_length=128)
    run_url: str = Field(default="", max_length=512)


@router.post("/ci/trigger")
def ci_trigger(body: CiTriggerIn, db: Session = Depends(get_db), gi: GitIntegration = Depends(get_ci_integration)):
    branch = re.sub(r"^refs/heads/", "", body.branch)
    if not gi.auto_validation:
        return {"status": "SKIPPED", "reason": "Automatic validation is disabled for this project"}
    if branch != gi.branch:
        return {"status": "SKIPPED", "reason": f"Branch '{branch}' is not the configured branch '{gi.branch}'"}
    run, created = create_run(db, gi.project, gi, trigger="ci", created_by="github-actions",
                              commit_sha=body.commit_sha, branch=branch, ci_event_id=body.event_id,
                              ci_run_url=body.run_url)
    return {"status": "CREATED" if created else "DUPLICATE", "run": S.run(run)}


@router.get("/ci/runs/{run_id}")
def ci_run_status(run_id: int, db: Session = Depends(get_db), gi: GitIntegration = Depends(get_ci_integration)):
    r = db.get(ValidationRun, run_id)
    if not r or r.project_id != gi.project_id:
        raise HTTPException(404, "Run not found")
    return S.run(r, with_executions=True, with_logs=False)


# --- Internal runner API (authenticated by EVAP_RUNNER_TOKEN) ----------------------
class CommitIn(BaseModel):
    commit_sha: str = Field(pattern=SHA_RE)


class ExecResultIn(BaseModel):
    status: str = Field(pattern="^(RUNNING|PASS|FAIL|ERROR)$")
    log: str = ""
    duration_s: float | None = None


class CompleteIn(BaseModel):
    error: str = Field(default="", max_length=4000)


def _runner_payload(r: ValidationRun) -> dict:
    return {"run": S.run(r), "executions": [{
        "execution_id": e.id, "tc_id": e.test_case.tc_id, "requirement_code": e.requirement.req_id,
        "script_revision": e.script_revision.revision, "sha256": e.script_revision.sha256,
        "source": e.script_revision.source} for e in r.executions]}


@router.post("/runner/recover", dependencies=[Depends(require_runner)])
def runner_recover(db: Session = Depends(get_db)):
    """Called on runner start-up: runs left RUNNING by a crashed runner are closed as ERROR."""
    stuck = list(db.scalars(select(ValidationRun).where(ValidationRun.status == "RUNNING")))
    for r in stuck:
        for e in r.executions:
            if e.status in ("QUEUED", "RUNNING"):
                e.status, e.log = "ERROR", (e.log + "\n[evap] runner restarted during execution").strip()
        finalize_run(db, r, "Runner restarted during execution")
    return {"recovered": [r.id for r in stuck]}


@router.post("/runner/claim", dependencies=[Depends(require_runner)])
def runner_claim(db: Session = Depends(get_db)):
    r = db.scalar(select(ValidationRun).where(ValidationRun.status == "QUEUED")
                  .order_by(ValidationRun.id).limit(1).with_for_update(skip_locked=True))
    if not r:
        return {"run": None}
    r.status, r.started_at = "RUNNING", datetime.now(timezone.utc)
    db.commit()
    return _runner_payload(r)


@router.post("/runner/runs/{run_id}/commit", dependencies=[Depends(require_runner)])
def runner_set_commit(run_id: int, body: CommitIn, db: Session = Depends(get_db)):
    r = db.get(ValidationRun, run_id)
    if not r:
        raise HTTPException(404, "Run not found")
    if r.commit_sha and r.commit_sha != body.commit_sha:
        raise HTTPException(409, "Commit already set")
    r.commit_sha = body.commit_sha
    db.commit()
    return {"ok": True}


@router.post("/runner/executions/{exec_id}", dependencies=[Depends(require_runner)])
def runner_execution(exec_id: int, body: ExecResultIn, db: Session = Depends(get_db)):
    e = db.get(TestExecution, exec_id)
    if not e or e.run.status != "RUNNING":
        raise HTTPException(404, "Execution not found or run not running")
    now = datetime.now(timezone.utc)
    e.status = body.status
    if body.status == "RUNNING":
        e.started_at = now
    else:
        e.finished_at, e.duration_s = now, body.duration_s
        e.log = body.log[-MAX_LOG:]
    db.commit()
    return {"ok": True}


@router.post("/runner/runs/{run_id}/complete", dependencies=[Depends(require_runner)])
def runner_complete(run_id: int, body: CompleteIn, db: Session = Depends(get_db)):
    r = db.get(ValidationRun, run_id)
    if not r or r.status != "RUNNING":
        raise HTTPException(404, "Run not found or not running")
    for e in r.executions:
        if e.status in ("QUEUED", "RUNNING"):
            e.status = "ERROR"
            e.log = (e.log + "\n[evap] not executed: " + (body.error or "run aborted")).strip()
    finalize_run(db, r, body.error)
    return S.run(r)


