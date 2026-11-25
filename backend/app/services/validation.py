"""Script registry, run creation (with idempotency) and quality gate evaluation."""
import ast
import hashlib
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import GitIntegration, Project, TestCase, TestExecution, TestScriptRevision, ValidationRun

FINAL_STATES = ("PASS", "FAIL", "ERROR")
GATE_POLICIES = ("all_pass", "pass_rate")
# Imports that are not forbidden (the sandbox enforces isolation) but deserve reviewer attention.
REVIEW_FLAG_MODULES = {"subprocess", "socket", "shutil", "ctypes", "requests", "urllib", "http"}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_script(source: str) -> dict:
    """Static validation: syntax, at least one pytest test function, reviewer warnings."""
    errors, warnings, tests = [], [], []
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {"ok": False, "errors": [f"SyntaxError line {exc.lineno}: {exc.msg}"],
                "warnings": [], "tests": []}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            tests.append(node.name)
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            mods = [(node.module or "").split(".")[0]]
        else:
            mods = []
        for m in mods:
            if m in REVIEW_FLAG_MODULES:
                warnings.append(f"line {node.lineno}: imports '{m}' — review carefully")
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("eval", "exec"):
            warnings.append(f"line {node.lineno}: uses {node.func.id}()")
    if not tests:
        errors.append("No pytest test function found (function names must start with 'test')")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "tests": tests}


def executable_scripts(db: Session, project_id: int, test_case_id: int | None = None) -> list[TestScriptRevision]:
    """Dynamic test discovery: the latest APPROVED revision of every test case."""
    sub = (select(TestScriptRevision.test_case_id, func.max(TestScriptRevision.revision).label("rev"))
           .join(TestCase).where(TestCase.project_id == project_id,
                                 TestScriptRevision.approval_status == "approved"))
    if test_case_id is not None:
        sub = sub.where(TestScriptRevision.test_case_id == test_case_id)
    sub = sub.group_by(TestScriptRevision.test_case_id).subquery()
    q = (select(TestScriptRevision)
         .join(sub, (TestScriptRevision.test_case_id == sub.c.test_case_id)
               & (TestScriptRevision.revision == sub.c.rev))
         .order_by(TestScriptRevision.test_case_id))
    return list(db.scalars(q).all())


def baseline_hash(scripts: list[TestScriptRevision]) -> str:
    parts = sorted(f"{s.test_case_id}:{s.revision}:{s.sha256}" for s in scripts)
    return sha256_text("|".join(parts))


def gate_label(gi: GitIntegration) -> str:
    return "all_pass" if gi.gate_policy == "all_pass" else f"pass_rate>={gi.gate_threshold:g}%"


def create_run(db: Session, project: Project, gi: GitIntegration, *, trigger: str, created_by: str,
               commit_sha: str | None = None, branch: str | None = None, test_case_id: int | None = None,
               ci_event_id: str = "", ci_run_url: str = "") -> tuple[ValidationRun, bool]:
    """Returns (run, created). CI runs are idempotent per (project, commit, test baseline)."""
    scripts = executable_scripts(db, project.id, test_case_id)
    base = baseline_hash(scripts)
    key = None
    if trigger == "ci" and commit_sha:
        key = sha256_text(f"{project.id}|{commit_sha}|{base}")
        existing = db.scalar(select(ValidationRun).where(ValidationRun.idempotency_key == key))
        if existing:
            return existing, False
    run = ValidationRun(
        project_id=project.id, repo_url=gi.repo_url, branch=branch or gi.branch, commit_sha=commit_sha,
        trigger=trigger, status="QUEUED", quality_gate="PENDING", gate_policy=gate_label(gi),
        baseline_hash=base, idempotency_key=key, scope_test_case_id=test_case_id,
        timeout_s=gi.timeout_s, python_env=gi.python_env, ci_event_id=ci_event_id[:128],
        ci_run_url=ci_run_url[:512], created_by=created_by, total=len(scripts))
    if not scripts:
        run.status, run.quality_gate = "ERROR", "FAILED"
        run.message = "No approved test scripts to execute"
        run.finished_at = datetime.now(timezone.utc)
    db.add(run)
    db.flush()
    for s in scripts:  # snapshot the exact revisions that this run will execute
        req = s.test_case.requirement
        db.add(TestExecution(run_id=run.id, test_case_id=s.test_case_id, script_revision_id=s.id,
                             requirement_id=req.id, requirement_revision=req.revision, status="QUEUED"))
    db.commit()
    db.refresh(run)
    return run, True


def finalize_run(db: Session, run: ValidationRun, message: str = "") -> ValidationRun:
    ex = run.executions
    run.total = len(ex)
    run.passed = sum(e.status == "PASS" for e in ex)
    run.failed = sum(e.status == "FAIL" for e in ex)
    run.errored = sum(e.status == "ERROR" for e in ex)
    if run.total == 0:
        run.status = "ERROR"
    elif run.failed:
        run.status = "FAIL"
    elif run.errored:
        run.status = "ERROR"
    else:
        run.status = "PASS"
    gi = db.scalar(select(GitIntegration).where(GitIntegration.project_id == run.project_id))
    rate = 100.0 * run.passed / run.total if run.total else 0.0
    if run.total == 0:
        ok = False
    elif run.gate_policy == "all_pass" or gi is None:
        ok = run.passed == run.total
    else:
        ok = rate >= gi.gate_threshold
    run.quality_gate = "PASSED" if ok else "FAILED"
    if message:
        run.message = message
    run.finished_at = datetime.now(timezone.utc)
    db.commit()
    return run
