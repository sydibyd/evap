"""Plain-dict serializers (kept explicit to avoid leaking secrets such as token hashes)."""
from .models import (GitIntegration, Project, Requirement, RequirementRevision, TestCase,
                     TestExecution, TestScriptRevision, User, ValidationRun)


def _dt(v):
    return v.isoformat() if v else None


def user(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "active": u.active,
            "created_at": _dt(u.created_at)}


def project(p: Project) -> dict:
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": _dt(p.created_at),
            "git": git(p.git) if p.git else None}


def git(g: GitIntegration) -> dict:
    return {"repo_url": g.repo_url, "branch": g.branch, "auto_validation": g.auto_validation,
            "python_env": g.python_env, "timeout_s": g.timeout_s, "gate_policy": g.gate_policy,
            "gate_threshold": g.gate_threshold, "ci_token_configured": bool(g.ci_token_hash),
            "ci_token_hint": g.ci_token_hint, "updated_at": _dt(g.updated_at)}


def requirement(r: Requirement, with_children: bool = False) -> dict:
    d = {"id": r.id, "project_id": r.project_id, "req_id": r.req_id, "subsystem": r.subsystem,
         "description": r.description, "priority": r.priority, "status": r.status,
         "revision": r.revision, "created_at": _dt(r.created_at), "updated_at": _dt(r.updated_at),
         "test_case_count": len(r.test_cases)}
    if with_children:
        d["revisions"] = [requirement_revision(x) for x in reversed(r.revisions)]
        d["test_cases"] = [test_case(t) for t in r.test_cases]
    return d


def requirement_revision(x: RequirementRevision) -> dict:
    return {"revision": x.revision, "subsystem": x.subsystem, "description": x.description,
            "priority": x.priority, "status": x.status, "source": x.source, "author": x.author,
            "created_at": _dt(x.created_at)}


def test_case(t: TestCase) -> dict:
    latest = t.scripts[-1] if t.scripts else None
    approved = [s for s in t.scripts if s.approval_status == "approved"]
    return {"id": t.id, "project_id": t.project_id, "tc_id": t.tc_id, "title": t.title,
            "requirement_id": t.requirement_id, "requirement_code": t.requirement.req_id,
            "preconditions": t.preconditions, "inputs": t.inputs,
            "expected_results": t.expected_results, "sil_environment": t.sil_environment,
            "latest_revision": latest.revision if latest else None,
            "latest_status": latest.approval_status if latest else None,
            "approved_revision": approved[-1].revision if approved else None,
            "created_at": _dt(t.created_at), "updated_at": _dt(t.updated_at)}


def script(s: TestScriptRevision, with_source: bool = True) -> dict:
    d = {"id": s.id, "test_case_id": s.test_case_id, "tc_id": s.test_case.tc_id, "revision": s.revision,
         "sha256": s.sha256, "author": s.author.username if s.author else None,
         "approval_status": s.approval_status,
         "reviewer": s.reviewer.username if s.reviewer else None,
         "review_comment": s.review_comment, "reviewed_at": _dt(s.reviewed_at),
         "created_at": _dt(s.created_at)}
    if with_source:
        d["source"] = s.source
    return d


def run(r: ValidationRun, with_executions: bool = False, with_logs: bool = False) -> dict:
    d = {"id": r.id, "project_id": r.project_id, "repo_url": r.repo_url, "branch": r.branch,
         "commit_sha": r.commit_sha, "trigger": r.trigger, "status": r.status,
         "quality_gate": r.quality_gate, "gate_policy": r.gate_policy, "baseline_hash": r.baseline_hash,
         "scope_test_case_id": r.scope_test_case_id, "timeout_s": r.timeout_s,
         "python_env": r.python_env, "ci_event_id": r.ci_event_id, "ci_run_url": r.ci_run_url,
         "message": r.message, "created_by": r.created_by, "total": r.total, "passed": r.passed,
         "failed": r.failed, "errored": r.errored, "created_at": _dt(r.created_at),
         "started_at": _dt(r.started_at), "finished_at": _dt(r.finished_at)}
    if with_executions:
        d["executions"] = [execution(e, with_logs) for e in r.executions]
    return d


def execution(e: TestExecution, with_log: bool = True) -> dict:
    d = {"id": e.id, "run_id": e.run_id, "test_case_id": e.test_case_id, "tc_id": e.test_case.tc_id,
         "requirement_id": e.requirement_id, "requirement_code": e.requirement.req_id,
         "requirement_revision": e.requirement_revision, "script_revision_id": e.script_revision_id,
         "script_revision": e.script_revision.revision, "script_sha256": e.script_revision.sha256,
         "status": e.status, "duration_s": e.duration_s, "started_at": _dt(e.started_at),
         "finished_at": _dt(e.finished_at)}
    if with_log:
        d["log"] = e.log
    return d
