"""Database model.

Traceability chain:
Requirement -> TestCase -> TestScriptRevision -> TestExecution -> ValidationRun (commit SHA) -> verdict
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # engineer | reviewer | admin
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    git: Mapped["GitIntegration | None"] = relationship(back_populates="project", uselist=False)


class GitIntegration(Base):
    __tablename__ = "git_integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    branch: Mapped[str] = mapped_column(String(128), default="main", nullable=False)
    auto_validation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    python_env: Mapped[str] = mapped_column(String(32), default="python3.11", nullable=False)
    timeout_s: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    gate_policy: Mapped[str] = mapped_column(String(32), default="all_pass", nullable=False)
    gate_threshold: Mapped[float] = mapped_column(Float, default=100.0, nullable=False)
    ci_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ci_token_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    project: Mapped[Project] = relationship(back_populates="git")


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("project_id", "req_id", name="uq_requirement_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    req_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subsystem: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    revisions: Mapped[list["RequirementRevision"]] = relationship(
        back_populates="requirement", order_by="RequirementRevision.revision")
    test_cases: Mapped[list["TestCase"]] = relationship(back_populates="requirement")


class RequirementRevision(Base):
    __tablename__ = "requirement_revisions"
    __table_args__ = (UniqueConstraint("requirement_id", "revision", name="uq_requirement_revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    subsystem: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(256), default="manual")
    author: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    requirement: Mapped[Requirement] = relationship(back_populates="revisions")


class TestCase(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_cases"
    __table_args__ = (UniqueConstraint("project_id", "tc_id", name="uq_testcase_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    tc_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), default="")
    preconditions: Mapped[str] = mapped_column(Text, default="")
    inputs: Mapped[str] = mapped_column(Text, default="")
    expected_results: Mapped[str] = mapped_column(Text, default="")
    sil_environment: Mapped[str] = mapped_column(String(32), default="python3.11")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    requirement: Mapped[Requirement] = relationship(back_populates="test_cases")
    scripts: Mapped[list["TestScriptRevision"]] = relationship(
        back_populates="test_case", order_by="TestScriptRevision.revision")


class TestScriptRevision(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_script_revisions"
    __table_args__ = (UniqueConstraint("test_case_id", "revision", name="uq_script_revision"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    # draft | approved | rejected
    approval_status: Mapped[str] = mapped_column(String(16), default="draft", nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    review_comment: Mapped[str] = mapped_column(Text, default="")
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    test_case: Mapped[TestCase] = relationship(back_populates="scripts")
    author: Mapped[User] = relationship(foreign_keys=[author_id])
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewer_id])


class ValidationRun(Base):
    __tablename__ = "validation_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    repo_url: Mapped[str] = mapped_column(String(512), nullable=False)
    branch: Mapped[str] = mapped_column(String(128), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # manual | ci
    # QUEUED | RUNNING | PASS | FAIL | ERROR
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False, index=True)
    quality_gate: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    gate_policy: Mapped[str] = mapped_column(String(64), default="all_pass")
    baseline_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    scope_test_case_id: Mapped[int | None] = mapped_column(ForeignKey("test_cases.id"), nullable=True)
    timeout_s: Mapped[int] = mapped_column(Integer, default=60)
    python_env: Mapped[str] = mapped_column(String(32), default="python3.11")
    ci_event_id: Mapped[str] = mapped_column(String(128), default="")
    ci_run_url: Mapped[str] = mapped_column(String(512), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errored: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executions: Mapped[list["TestExecution"]] = relationship(back_populates="run", order_by="TestExecution.id")


class TestExecution(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_executions"
    __table_args__ = (UniqueConstraint("run_id", "script_revision_id", name="uq_execution_script"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("validation_runs.id", ondelete="CASCADE"), index=True)
    test_case_id: Mapped[int] = mapped_column(ForeignKey("test_cases.id"), index=True)
    script_revision_id: Mapped[int] = mapped_column(ForeignKey("test_script_revisions.id"))
    requirement_id: Mapped[int] = mapped_column(ForeignKey("requirements.id"), index=True)
    requirement_revision: Mapped[int] = mapped_column(Integer, default=1)
    # QUEUED | RUNNING | PASS | FAIL | ERROR
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    log: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run: Mapped[ValidationRun] = relationship(back_populates="executions")
    test_case: Mapped[TestCase] = relationship()
    script_revision: Mapped[TestScriptRevision] = relationship()
    requirement: Mapped[Requirement] = relationship()
