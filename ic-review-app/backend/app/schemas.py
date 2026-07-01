from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_serializer

from app.utils.timeutil import to_local_iso


class HealthResponse(BaseModel):
    status: str
    llm_configured: bool
    llm_model: str
    message: str = ""


class DocumentMetaUpdate(BaseModel):
    business_domain: str | None = None
    unit_name: str | None = None
    document_level: str | None = None
    version: str | None = None


class DocumentCreateMeta(BaseModel):
    document_name: str
    unit_name: str
    document_level: str
    business_domain: str = "采购"
    version: str = ""


class DocumentOut(BaseModel):
    id: int
    document_name: str
    unit_name: str
    document_level: str
    business_domain: str
    version: str
    parse_status: str
    lock_status: str = "unlocked"
    quality_status: str = "normal"
    parse_error_code: str = ""
    degradation_notes: str = ""
    table_review_required: bool = False
    complex_table_pages: str = ""
    ocr_confidence: float | None = None
    page_count: int | None = None
    file_size: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentPreviewOut(BaseModel):
    id: int
    document_name: str
    unit_name: str
    document_level: str
    business_domain: str
    version: str
    parse_status: str
    lock_status: str = "unlocked"
    quality_status: str = "normal"
    parse_error_code: str = ""
    parse_error_detail: str = ""
    degradation_notes: str = ""
    table_review_required: bool = False
    complex_table_pages: str = ""
    ocr_confidence: float | None = None
    page_count: int | None = None
    file_size: int = 0
    file_ext: str | None = None
    has_original_file: bool = False
    text_content: str = ""
    clause_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ClauseOut(BaseModel):
    id: int
    document_id: int
    chapter_title: str
    clause_no: str
    clause_text: str
    page_no: int | None
    location_label: str

    model_config = {"from_attributes": True}


class StandardControlPointOut(BaseModel):
    id: int
    standard_code: str
    business_domain: str
    control_topic: str
    standard_requirement: str
    importance: str
    industry_tags: str
    source_basis: str
    version: str
    tenant_id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    task_name: str
    business_domain: str = "采购"
    description: str = ""
    group_document_id: int
    subsidiary_document_id: int


class SingleAuditCreate(BaseModel):
    mode: str = "fast"
    document_id: int
    task_name: str = ""
    business_domain: str = "内控"
    # 参考范本 policy_id：留空=按领域自动匹配；"__none__"=不参考范本。
    template_id: str = ""


class TaskOut(BaseModel):
    id: int
    task_name: str
    business_domain: str
    description: str
    group_document_id: int
    subsidiary_document_id: int
    task_type: str = "group_vs_subsidiary"
    status: str
    execution_mode: str = "hybrid"
    executor_backend: str = "local_thread"
    prompt_bundle_version: str = "Hybrid_V1.0"
    core_model_version: str = ""
    expert_model_version: str = ""
    result_version: int = 1
    degradation_reason: str = ""
    current_step: int
    pipeline_error: str | None
    report_summary: str | None
    created_at: datetime
    completed_at: datetime | None
    reference_template_id: str = ""
    reference_template_title: str = ""
    diff_count: int = 0
    high_risk_count: int = 0
    pending_review_count: int = 0

    model_config = {"from_attributes": True}


class DashboardOut(BaseModel):
    pending_task: TaskOut | None
    total_tasks: int
    pending_reviews: int  # 全库待复核差异条数
    recent_tasks: list[TaskOut] = Field(default_factory=list)


class DifferenceOut(BaseModel):
    id: int
    task_id: int
    diff_type: str
    risk_level: str
    control_topic: str
    summary: str
    group_excerpt: str
    subsidiary_excerpt: str
    group_location: str
    subsidiary_location: str
    ai_reason: str
    suggestion: str
    confidence: float
    evidence_ok: bool
    review_status: str

    model_config = {"from_attributes": True}


class DifferenceDetailOut(DifferenceOut):
    group_clause_text: str = ""
    subsidiary_clause_text: str = ""
    # 左侧标准控制点的外规出处（法规名称、条款/依据要点）。
    group_external_regulation: str = ""
    group_external_basis: str = ""
    group_clause_truncated: bool = False
    subsidiary_clause_truncated: bool = False
    expert_reviewed: bool = False
    expert_review_note: str = ""
    semantic_review: bool = False
    single_document_audit: bool = False
    table_review_required: bool = False
    table_review_documents: list[dict[str, Any]] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    action: str = Field(pattern="^(confirmed|rejected)$")
    comment: str = ""


class ExemptionCreate(BaseModel):
    justification: str = Field(min_length=5)
    policy_basis: str = ""
    org_scope: str = "本机构"
    expires_at: datetime | None = None


class ExemptionOut(BaseModel):
    id: int
    difference_id: int
    task_id: int
    control_topic: str
    org_scope: str
    justification: str
    policy_basis: str
    base_version: str = ""
    governance_note: str = ""
    status: str
    effective_from: datetime | None
    expires_at: datetime | None
    approved_by: str
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SupplementCreate(BaseModel):
    assignee: str = "子公司经办人"
    requirement: str = Field(min_length=3)
    due_at: datetime | None = None


class SupplementSubmit(BaseModel):
    submitted_text: str = Field(min_length=5)


class SupplementOut(BaseModel):
    id: int
    difference_id: int
    task_id: int
    assignee: str
    requirement: str
    status: str
    due_at: datetime | None
    submitted_text: str
    result: str
    result_reason: str
    pollution_scan_result: str = ""
    derived_difference_ids: str = ""
    created_at: datetime
    submitted_at: datetime | None
    closed_at: datetime | None

    model_config = {"from_attributes": True}


class ReviewLogOut(BaseModel):
    id: int
    difference_id: int
    task_id: int
    action: str
    comment: str
    reviewer: str
    created_at: datetime
    diff_summary: str = ""
    risk_level: str = ""
    diff_type: str = ""

    model_config = {"from_attributes": True}

    @field_serializer("created_at")
    @classmethod
    def serialize_created_at(cls, v: datetime) -> str:
        return to_local_iso(v)


class PipelineEvent(BaseModel):
    task_id: int
    step: int
    step_name: str
    agent_name: str
    status: str
    message: str
    progress: float


class PipelineLogOut(BaseModel):
    id: int
    step: int
    agent_name: str
    status: str
    message: str
    duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class SeedResponse(BaseModel):
    message: str
    group_document_id: int
    subsidiary_document_id: int
    task_id: int


class MatchPairStored(BaseModel):
    group_control_id: int
    subsidiary_control_id: int
    group_clause_id: int
    subsidiary_clause_id: int
    control_topic: str


class TaskContext(BaseModel):
    """Passed between pipeline steps."""
    task_id: int
    group_document_id: int
    subsidiary_document_id: int
    clauses_group: list[dict[str, Any]] = []
    clauses_sub: list[dict[str, Any]] = []
    control_points_group: list[dict[str, Any]] = []
    control_points_sub: list[dict[str, Any]] = []
    match_pairs: list[dict[str, Any]] = []
    differences_draft: list[dict[str, Any]] = []
