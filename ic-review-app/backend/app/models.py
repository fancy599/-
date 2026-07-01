from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy import event
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.db import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_name: Mapped[str] = mapped_column(String(255))
    unit_name: Mapped[str] = mapped_column(String(128))
    document_level: Mapped[str] = mapped_column(String(32))  # group | subsidiary
    business_domain: Mapped[str] = mapped_column(String(64), default="采购")
    version: Mapped[str] = mapped_column(String(64), default="")
    parse_status: Mapped[str] = mapped_column(String(32), default="pending")
    tenant_id: Mapped[str] = mapped_column(String(64), default="default")
    org_id: Mapped[str] = mapped_column(String(64), default="default")
    lock_status: Mapped[str] = mapped_column(String(32), default="unlocked")
    quality_status: Mapped[str] = mapped_column(String(32), default="normal")
    parse_error_code: Mapped[str] = mapped_column(String(64), default="")
    parse_error_detail: Mapped[str] = mapped_column(Text, default="")
    degradation_notes: Mapped[str] = mapped_column(Text, default="")
    table_review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    complex_table_pages: Mapped[str] = mapped_column(String(255), default="")
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    file_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    clauses: Mapped[list["Clause"]] = relationship(back_populates="document")


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    chapter_title: Mapped[str] = mapped_column(String(255), default="")
    clause_no: Mapped[str] = mapped_column(String(64), default="")
    clause_text: Mapped[str] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    paragraph_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_label: Mapped[str] = mapped_column(String(255), default="")

    document: Mapped["Document"] = relationship(back_populates="clauses")
    control_points: Mapped[list["ControlPoint"]] = relationship(back_populates="clause")


class ControlPoint(Base):
    __tablename__ = "control_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clause_id: Mapped[int] = mapped_column(ForeignKey("clauses.id"))
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    business_domain: Mapped[str] = mapped_column(String(64), default="")
    control_topic: Mapped[str] = mapped_column(String(128), default="")
    subject_role: Mapped[str] = mapped_column(String(128), default="")
    action: Mapped[str] = mapped_column(String(128), default="")
    object: Mapped[str] = mapped_column(String(128), default="")
    threshold: Mapped[str] = mapped_column(String(128), default="")
    requirement: Mapped[str] = mapped_column(Text, default="")

    clause: Mapped["Clause"] = relationship(back_populates="control_points")


class StandardControlPoint(Base):
    __tablename__ = "standard_control_points"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    standard_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    business_domain: Mapped[str] = mapped_column(String(64), index=True)
    control_topic: Mapped[str] = mapped_column(String(128))
    standard_requirement: Mapped[str] = mapped_column(Text)
    importance: Mapped[str] = mapped_column(String(32), default="required")
    industry_tags: Mapped[str] = mapped_column(String(255), default="")
    source_basis: Mapped[str] = mapped_column(Text, default="")
    # 外规出处：该标准控制点对应的外部法规名称与条款/依据要点。
    external_regulation: Mapped[str] = mapped_column(Text, default="")
    external_basis: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(64), default="V1.0")
    tenant_id: Mapped[str] = mapped_column(String(64), default="system", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_name: Mapped[str] = mapped_column(String(255))
    business_domain: Mapped[str] = mapped_column(String(64), default="采购")
    description: Mapped[str] = mapped_column(Text, default="")
    group_document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    subsidiary_document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    # PRD 11.5：显式建模任务类型，避免用 group==subsidiary 隐式判定单制度体检。
    task_type: Mapped[str] = mapped_column(String(32), default="group_vs_subsidiary")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    execution_mode: Mapped[str] = mapped_column(String(32), default="hybrid")
    executor_backend: Mapped[str] = mapped_column(String(32), default="local_thread")
    prompt_bundle_version: Mapped[str] = mapped_column(String(64), default="Hybrid_V1.0")
    core_model_version: Mapped[str] = mapped_column(String(128), default="")
    expert_model_version: Mapped[str] = mapped_column(String(128), default="")
    result_version: Mapped[int] = mapped_column(Integer, default=1)
    degradation_reason: Mapped[str] = mapped_column(Text, default="")
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    pipeline_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 单制度体检参考的范本（脱敏制度资产库 policy_id 与标题）。
    reference_template_id: Mapped[str] = mapped_column(String(64), default="")
    reference_template_title: Mapped[str] = mapped_column(String(255), default="")

    differences: Mapped[list["Difference"]] = relationship(back_populates="task")
    pipeline_logs: Mapped[list["PipelineRunLog"]] = relationship(back_populates="task")


class Difference(Base):
    __tablename__ = "differences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"))
    diff_type: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(16))
    control_topic: Mapped[str] = mapped_column(String(128), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    group_clause_id: Mapped[int | None] = mapped_column(ForeignKey("clauses.id"), nullable=True)
    subsidiary_clause_id: Mapped[int | None] = mapped_column(ForeignKey("clauses.id"), nullable=True)
    group_excerpt: Mapped[str] = mapped_column(Text, default="")
    subsidiary_excerpt: Mapped[str] = mapped_column(Text, default="")
    group_location: Mapped[str] = mapped_column(String(255), default="")
    subsidiary_location: Mapped[str] = mapped_column(String(255), default="")
    # 左侧标准控制点对应的外规出处（法规名称、条款/依据要点），用于单制度体检结果展示。
    group_external_regulation: Mapped[str] = mapped_column(Text, default="")
    group_external_basis: Mapped[str] = mapped_column(Text, default="")
    ai_reason: Mapped[str] = mapped_column(Text, default="")
    suggestion: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    original_ai_reason: Mapped[str] = mapped_column(Text, default="")
    fallback_reason: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(String(64), default="CoreAnalyser_V1.0")
    model_version: Mapped[str] = mapped_column(String(128), default="")

    task: Mapped["ReviewTask"] = relationship(back_populates="differences")
    review_logs: Mapped[list["ReviewLog"]] = relationship(back_populates="difference")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    difference_id: Mapped[int] = mapped_column(ForeignKey("differences.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"))
    action: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str] = mapped_column(Text, default="")
    reviewer: Mapped[str] = mapped_column(String(64), default="审查人员")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    difference: Mapped["Difference"] = relationship(back_populates="review_logs")


class PipelineRunLog(Base):
    __tablename__ = "pipeline_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"))
    step: Mapped[int] = mapped_column(Integer)
    agent_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)

    task: Mapped["ReviewTask"] = relationship(back_populates="pipeline_logs")


class DiffClauseMapping(Base):
    __tablename__ = "diff_clause_mappings"
    __table_args__ = (UniqueConstraint("difference_id", "source_type", "clause_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    difference_id: Mapped[int] = mapped_column(ForeignKey("differences.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))
    clause_id: Mapped[int] = mapped_column(ForeignKey("clauses.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class TaskCheckpoint(Base):
    __tablename__ = "task_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    node_key: Mapped[str] = mapped_column(String(128))
    input_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    output_json: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(String(64), default="")
    model_version: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class TaskExecutionEvent(Base):
    __tablename__ = "task_execution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16), default="info")
    error_code: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    detail_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    chapter_hash: Mapped[str] = mapped_column(String(64), index=True)
    global_context_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    dependency_scope: Mapped[str] = mapped_column(String(32), default="document")
    prompt_version: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(128))
    result_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class ExemptionRule(Base):
    __tablename__ = "exemption_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    difference_id: Mapped[int] = mapped_column(ForeignKey("differences.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"))
    control_topic: Mapped[str] = mapped_column(String(128), default="")
    org_scope: Mapped[str] = mapped_column(String(128), default="")
    semantic_fingerprint: Mapped[str] = mapped_column(Text, default="")
    justification: Mapped[str] = mapped_column(Text, default="")
    policy_basis: Mapped[str] = mapped_column(Text, default="")
    base_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
    base_version: Mapped[str] = mapped_column(String(64), default="")
    base_control_fingerprint: Mapped[str] = mapped_column(Text, default="")
    governance_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending_approval")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[str] = mapped_column(String(64), default="")
    created_by: Mapped[str] = mapped_column(String(64), default="审查人员")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class SupplementRequest(Base):
    __tablename__ = "supplement_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    difference_id: Mapped[int] = mapped_column(ForeignKey("differences.id"))
    task_id: Mapped[int] = mapped_column(ForeignKey("review_tasks.id"))
    assignee: Mapped[str] = mapped_column(String(128), default="子公司经办人")
    requirement: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="pending")
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_text: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(64), default="")
    result_reason: Mapped[str] = mapped_column(Text, default="")
    pollution_scan_result: Mapped[str] = mapped_column(Text, default="")
    derived_difference_ids: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


@event.listens_for(Session, "before_flush")
def _apply_difference_safety_rails(session: Session, _flush_context, _instances) -> None:
    from app.services.robustness import apply_low_confidence_fallback

    for obj in session.new.union(session.dirty):
        if isinstance(obj, Difference):
            apply_low_confidence_fallback(obj)
