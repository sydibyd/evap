"""Projects, Git integration, requirements, test cases and the script registry."""
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import serialize as S
from ..config import get_settings
from ..db import get_db
from ..models import (GitIntegration, Project, Requirement, RequirementRevision, TestCase,
                      TestScriptRevision, User)
from ..security import any_user, hash_token, new_ci_token, reviewer, writer
from ..services import excel
from ..services.validation import GATE_POLICIES, check_script, executable_scripts, sha256_text

router = APIRouter(prefix="/api", tags=["design"])

CODE_RE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$"
PY_ENVS = ("python3.11",)
# https://, ssh (git@host:owner/repo.git) — no local paths, no shell metacharacters.
REPO_RE = re.compile(r"^(https://[A-Za-z0-9.-]+/[A-Za-z0-9._/-]+|git@[A-Za-z0-9.-]+:[A-Za-z0-9._/-]+)$")


def _get(db: Session, model, obj_id: int, what: str):
    obj = db.get(model, obj_id)
    if not obj:
        raise HTTPException(404, f"{what} not found")
    return obj


# --- Projects ---------------------------------------------------------------
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4000)


@router.get("/projects")
def list_projects(db: Session = Depends(get_db), _: User = Depends(any_user)):
    return [S.project(p) for p in db.scalars(select(Project).order_by(Project.id))]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), _: User = Depends(writer)):
    if db.scalar(select(Project).where(Project.name == body.name)):
        raise HTTPException(409, "Project name already exists")
    p = Project(name=body.name.strip(), description=body.description)
    db.add(p)
    db.commit()
    return S.project(p)


@router.get("/projects/{pid}")
def get_project(pid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    return S.project(_get(db, Project, pid, "Project"))


@router.patch("/projects/{pid}")
def update_project(pid: int, body: ProjectIn, db: Session = Depends(get_db), _: User = Depends(writer)):
    p = _get(db, Project, pid, "Project")
    other = db.scalar(select(Project).where(Project.name == body.name, Project.id != pid))
    if other:
        raise HTTPException(409, "Project name already exists")
    p.name, p.description = body.name.strip(), body.description
    db.commit()
    return S.project(p)


# --- Git / CI integration ----------------------------------------------------
class GitIn(BaseModel):
    repo_url: str = Field(max_length=512)
    branch: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]{1,128}$")
    auto_validation: bool = False
    python_env: str = "python3.11"
    timeout_s: int = Field(default=60, ge=5, le=1800)
    gate_policy: str = "all_pass"
    gate_threshold: float = Field(default=100.0, ge=0, le=100)

    @field_validator("repo_url")
    @classmethod
    def _repo(cls, v: str) -> str:
        v = v.strip()
        if not REPO_RE.match(v) or ".." in v:
            raise ValueError("Repository URL must be https://host/owner/repo(.git) or git@host:owner/repo.git")
        return v

    @field_validator("python_env")
    @classmethod
    def _env(cls, v: str) -> str:
        if v not in PY_ENVS:
            raise ValueError(f"python_env must be one of {PY_ENVS}")
        return v

    @field_validator("gate_policy")
    @classmethod
    def _gate(cls, v: str) -> str:
        if v not in GATE_POLICIES:
            raise ValueError(f"gate_policy must be one of {GATE_POLICIES}")
        return v


@router.get("/projects/{pid}/git")
def get_git(pid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    p = _get(db, Project, pid, "Project")
    return S.git(p.git) if p.git else None


@router.put("/projects/{pid}/git")
def put_git(pid: int, body: GitIn, db: Session = Depends(get_db), _: User = Depends(reviewer)):
    p = _get(db, Project, pid, "Project")
    gi = p.git or GitIntegration(project_id=p.id, repo_url=body.repo_url)
    for k, v in body.model_dump().items():
        setattr(gi, k, v)
    db.add(gi)
    db.commit()
    db.refresh(gi)
    return S.git(gi)


@router.post("/projects/{pid}/git/ci-token")
def rotate_ci_token(pid: int, db: Session = Depends(get_db), _: User = Depends(reviewer)):
    p = _get(db, Project, pid, "Project")
    if not p.git:
        raise HTTPException(400, "Configure the Git integration first")
    token = new_ci_token()
    p.git.ci_token_hash = hash_token(token)
    p.git.ci_token_hint = token[-4:]
    db.commit()
    return {"token": token, "note": "Store this token as the EVAP_CI_TOKEN repository secret. "
                                    "It is shown only once."}


# --- Requirements ------------------------------------------------------------
class RequirementIn(BaseModel):
    req_id: str = Field(pattern=CODE_RE)
    subsystem: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=10000)
    priority: str = Field(default="", max_length=32)
    status: str = Field(default="", max_length=32)


class RequirementPatch(BaseModel):
    subsystem: str = Field(max_length=128)
    description: str = Field(max_length=10000)
    priority: str = Field(max_length=32)
    status: str = Field(max_length=32)


@router.get("/requirements/template.xlsx")
def requirements_template(_: User = Depends(any_user)):
    return Response(excel.build_template(), headers={
        "Content-Disposition": 'attachment; filename="EVAP_SRS_template.xlsx"'},
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.get("/projects/{pid}/requirements")
def list_requirements(pid: int, q: str = "", status: str = "", priority: str = "", subsystem: str = "",
                      db: Session = Depends(get_db), _: User = Depends(any_user)):
    stmt = select(Requirement).where(Requirement.project_id == pid)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Requirement.req_id.ilike(like), Requirement.description.ilike(like),
                              Requirement.subsystem.ilike(like)))
    if status:
        stmt = stmt.where(Requirement.status == status)
    if priority:
        stmt = stmt.where(Requirement.priority == priority)
    if subsystem:
        stmt = stmt.where(Requirement.subsystem == subsystem)
    return [S.requirement(r) for r in db.scalars(stmt.order_by(Requirement.req_id))]


@router.post("/projects/{pid}/requirements", status_code=201)
def create_requirement(pid: int, body: RequirementIn, db: Session = Depends(get_db),
                       user: User = Depends(writer)):
    _get(db, Project, pid, "Project")
    if db.scalar(select(Requirement).where(Requirement.project_id == pid, Requirement.req_id == body.req_id)):
        raise HTTPException(409, f"Requirement {body.req_id} already exists")
    r = Requirement(project_id=pid, revision=1, **body.model_dump())
    db.add(r)
    db.flush()
    fields = body.model_dump(exclude={"req_id"})
    db.add(RequirementRevision(requirement_id=r.id, revision=1, source="manual", author=user.username, **fields))
    db.commit()
    return S.requirement(r)


@router.get("/requirements/{rid}")
def get_requirement(rid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    return S.requirement(_get(db, Requirement, rid, "Requirement"), with_children=True)


@router.patch("/requirements/{rid}")
def update_requirement(rid: int, body: RequirementPatch, db: Session = Depends(get_db),
                       user: User = Depends(writer)):
    r = _get(db, Requirement, rid, "Requirement")
    fields = body.model_dump()
    if all(getattr(r, k) == v for k, v in fields.items()):
        return S.requirement(r, with_children=True)
    for k, v in fields.items():
        setattr(r, k, v)
    r.revision += 1
    db.add(RequirementRevision(requirement_id=r.id, revision=r.revision, source="manual",
                               author=user.username, **fields))
    db.commit()
    db.refresh(r)
    return S.requirement(r, with_children=True)


@router.post("/projects/{pid}/requirements/import")
async def import_requirements(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                              user: User = Depends(writer)):
    _get(db, Project, pid, "Project")
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Upload an .xlsx file")
    data = await file.read(get_settings().max_upload_bytes + 1)
    if len(data) > get_settings().max_upload_bytes:
        raise HTTPException(413, "File too large")
    try:
        return excel.import_requirements(db, pid, data, file.filename or "upload.xlsx", user.username)
    except excel.ImportError_ as exc:
        db.rollback()
        raise HTTPException(400, str(exc))


# --- Test cases --------------------------------------------------------------
class TestCaseIn(BaseModel):
    tc_id: str = Field(pattern=CODE_RE)
    requirement_id: int
    title: str = Field(default="", max_length=256)
    preconditions: str = Field(default="", max_length=10000)
    inputs: str = Field(default="", max_length=10000)
    expected_results: str = Field(default="", max_length=10000)
    sil_environment: str = "python3.11"


class TestCasePatch(BaseModel):
    requirement_id: int
    title: str = Field(default="", max_length=256)
    preconditions: str = Field(default="", max_length=10000)
    inputs: str = Field(default="", max_length=10000)
    expected_results: str = Field(default="", max_length=10000)
    sil_environment: str = "python3.11"


def _check_req(db: Session, pid: int, rid: int) -> Requirement:
    r = db.get(Requirement, rid)
    if not r or r.project_id != pid:
        raise HTTPException(400, "Requirement does not belong to this project")
    return r


@router.get("/projects/{pid}/testcases")
def list_testcases(pid: int, requirement_id: int | None = None, db: Session = Depends(get_db),
                   _: User = Depends(any_user)):
    stmt = select(TestCase).where(TestCase.project_id == pid)
    if requirement_id:
        stmt = stmt.where(TestCase.requirement_id == requirement_id)
    return [S.test_case(t) for t in db.scalars(stmt.order_by(TestCase.tc_id))]


@router.post("/projects/{pid}/testcases", status_code=201)
def create_testcase(pid: int, body: TestCaseIn, db: Session = Depends(get_db), _: User = Depends(writer)):
    _get(db, Project, pid, "Project")
    _check_req(db, pid, body.requirement_id)
    if body.sil_environment not in PY_ENVS:
        raise HTTPException(422, f"sil_environment must be one of {PY_ENVS}")
    if db.scalar(select(TestCase).where(TestCase.project_id == pid, TestCase.tc_id == body.tc_id)):
        raise HTTPException(409, f"Test case {body.tc_id} already exists")
    t = TestCase(project_id=pid, **body.model_dump())
    db.add(t)
    db.commit()
    db.refresh(t)
    return S.test_case(t)


@router.get("/testcases/{tid}")
def get_testcase(tid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    t = _get(db, TestCase, tid, "Test case")
    d = S.test_case(t)
    d["scripts"] = [S.script(s, with_source=False) for s in reversed(t.scripts)]
    return d


@router.patch("/testcases/{tid}")
def update_testcase(tid: int, body: TestCasePatch, db: Session = Depends(get_db), _: User = Depends(writer)):
    t = _get(db, TestCase, tid, "Test case")
    _check_req(db, t.project_id, body.requirement_id)
    if body.sil_environment not in PY_ENVS:
        raise HTTPException(422, f"sil_environment must be one of {PY_ENVS}")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return S.test_case(t)


# --- Script registry -----------------------------------------------------------
class ScriptIn(BaseModel):
    source: str = Field(min_length=1)


class ReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    comment: str = Field(default="", max_length=4000)


def _limit(source: str) -> None:
    if len(source.encode()) > get_settings().max_script_bytes:
        raise HTTPException(413, "Script too large")


@router.post("/scripts/validate")
def validate_script(body: ScriptIn, _: User = Depends(any_user)):
    _limit(body.source)
    return check_script(body.source)


@router.post("/testcases/{tid}/scripts", status_code=201)
def save_script(tid: int, body: ScriptIn, db: Session = Depends(get_db), user: User = Depends(writer)):
    t = _get(db, TestCase, tid, "Test case")
    _limit(body.source)
    chk = check_script(body.source)
    if not chk["ok"]:
        raise HTTPException(422, "; ".join(chk["errors"]))
    digest = sha256_text(body.source)
    if t.scripts and t.scripts[-1].sha256 == digest:
        raise HTTPException(409, f"Identical to revision {t.scripts[-1].revision}; nothing to save")
    rev = (t.scripts[-1].revision + 1) if t.scripts else 1
    s = TestScriptRevision(test_case_id=t.id, revision=rev, source=body.source, sha256=digest,
                           author_id=user.id, approval_status="draft")
    db.add(s)
    db.commit()
    db.refresh(s)
    return {**S.script(s), "check": chk}


@router.get("/testcases/{tid}/scripts")
def list_scripts(tid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    t = _get(db, TestCase, tid, "Test case")
    return [S.script(s, with_source=False) for s in reversed(t.scripts)]


@router.get("/scripts/{sid}")
def get_script(sid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    s = _get(db, TestScriptRevision, sid, "Script revision")
    return {**S.script(s), "check": check_script(s.source)}


@router.post("/scripts/{sid}/review")
def review_script(sid: int, body: ReviewIn, db: Session = Depends(get_db), user: User = Depends(reviewer)):
    s = _get(db, TestScriptRevision, sid, "Script revision")
    if s.approval_status != "draft":
        raise HTTPException(409, f"Revision already {s.approval_status}")
    if s.author_id == user.id:
        raise HTTPException(403, "Four-eyes rule: you cannot review your own script")
    if sha256_text(s.source) != s.sha256:
        raise HTTPException(409, "Checksum mismatch — script integrity compromised")
    if body.decision == "approve" and not check_script(s.source)["ok"]:
        raise HTTPException(422, "Script fails validation and cannot be approved")
    s.approval_status = "approved" if body.decision == "approve" else "rejected"
    s.reviewer_id, s.review_comment = user.id, body.comment
    s.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(s)
    return S.script(s, with_source=False)


@router.get("/projects/{pid}/registry")
def registry(pid: int, db: Session = Depends(get_db), _: User = Depends(any_user)):
    """The dynamic test registry: what an automatic validation would execute right now."""
    return [S.script(s, with_source=False) | {"requirement_code": s.test_case.requirement.req_id}
            for s in executable_scripts(db, pid)]
