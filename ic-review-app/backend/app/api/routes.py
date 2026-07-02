import asyncio
import json
import queue
import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app import db as db_module
from app.config import get_settings
from app.services.clause_excerpt import pick_clause_excerpt
from app.services.text_normalize import (
    cjk_ratio,
    is_low_quality_clause,
    normalize_extracted_text,
)
from app.utils.timeutil import as_utc, utc_now
from app.db import get_db
from app.models import (
    Clause,
    ControlPoint,
    Difference,
    DiffClauseMapping,
    Document,
    ExemptionRule,
    PipelineRunLog,
    ReviewLog,
    ReviewTask,
    StandardControlPoint,
    SupplementRequest,
    TaskCheckpoint,
    TaskExecutionEvent,
)
from app.pipeline.events import publish_event, subscribe, unsubscribe
from app.pipeline.orchestrator import PipelineOrchestrator
from app.schemas import (
    DashboardOut,
    DifferenceDetailOut,
    DifferenceOut,
    DocumentMetaUpdate,
    DocumentOut,
    DocumentPreviewOut,
    ExemptionCreate,
    ExemptionOut,
    HealthResponse,
    PipelineLogOut,
    ReviewLogOut,
    ReviewRequest,
    SeedResponse,
    SingleAuditCreate,
    StandardControlPointOut,
    SupplementCreate,
    SupplementOut,
    SupplementSubmit,
    TaskCreate,
    TaskOut,
)
from app.seed import seed_demo
from app.services.export import export_task_docx, export_task_html, export_task_xlsx
from app.services.llm import LLMClient
from app.services.parser import (
    ParseError,
    detect_pdf_complex_table_pages,
    extract_text_from_file,
    render_pdf_page_snapshot,
)
from app.services.clause_splitter import split_clauses_local
from app.services.control_heuristic import extract_control_points_local
from app.services.delta_pollution import scan_delta_pollution
from app.services.match_prefilter import text_overlap_score
from app.services.standard_control_library import infer_standard_domains, load_standard_controls
from app.services.template_library import (
    add_template_coverage_differences,
    auto_match_template,
    get_template,
    list_templates,
)
from app.services.upload_utils import MAX_RAW_TEXT_CHARS, MAX_UPLOAD_BYTES, safe_storage_name
from app.services.task_executor import submit_pipeline

router = APIRouter(prefix="/api")
SERVER_BOOT_UTC = datetime.now(timezone.utc)


@router.get("/standard-controls", response_model=list[StandardControlPointOut])
def list_standard_controls(
    business_domain: str = "",
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    load_standard_controls(db, [], include_general=True)
    query = db.query(StandardControlPoint)
    if business_domain:
        query = query.filter(StandardControlPoint.business_domain == business_domain)
    if active_only:
        query = query.filter(StandardControlPoint.is_active.is_(True))
    return query.order_by(StandardControlPoint.business_domain.asc(), StandardControlPoint.id.asc()).all()


def _govern_exemptions_after_group_upgrade(db: Session, new_doc: Document) -> None:
    """Carry forward unchanged exceptions and suspend those whose base semantics changed."""
    if new_doc.document_level != "group" or not new_doc.raw_text:
        return
    rows = db.query(ExemptionRule).filter(ExemptionRule.status.in_(("active", "inherited"))).all()
    new_text = normalize_extracted_text(new_doc.raw_text)
    for row in rows:
        old_task = db.get(ReviewTask, row.task_id)
        old_base = db.get(Document, old_task.group_document_id) if old_task else None
        if not old_base or old_base.business_domain != new_doc.business_domain or old_base.id == new_doc.id:
            continue
        fingerprint = normalize_extracted_text(row.base_control_fingerprint or row.semantic_fingerprint)
        # 例外继承必须保守：仅高相似度或原控制表达仍完整存在时继承。
        # 主题词相同但审批主体、金额阈值或强制程度变化时应暂停重审。
        unchanged = bool(fingerprint and (fingerprint in new_text or text_overlap_score(fingerprint, new_text) >= 0.65))
        row.status = "inherited" if unchanged else "suspended_by_base_upgrade"
        row.base_document_id = new_doc.id
        row.base_version = new_doc.version
        row.governance_note = (
            f"集团基准升级至 {new_doc.version or new_doc.document_name}，关联控制点语义未发生实质变化，例外继承生效。"
            if unchanged
            else f"集团基准升级至 {new_doc.version or new_doc.document_name}，关联控制点可能强化、修改或废除，例外已暂停，需双人重新审计或收回。"
        )
        row.updated_at = utc_now()


def _task_stats(db: Session, task: ReviewTask) -> TaskOut:
    _recover_stale_running_task(db, task)
    diffs = db.query(Difference).filter(Difference.task_id == task.id).all()
    pending_like_statuses = {
        "pending",
        "pending_evidence",
        "need_supplement",
        "exemption_pending",
        "delta_reviewing",
    }
    return TaskOut(
        id=task.id,
        task_name=task.task_name,
        business_domain=task.business_domain,
        description=task.description,
        group_document_id=task.group_document_id,
        subsidiary_document_id=task.subsidiary_document_id,
        status=task.status,
        execution_mode=task.execution_mode,
        executor_backend=task.executor_backend,
        prompt_bundle_version=task.prompt_bundle_version,
        core_model_version=task.core_model_version,
        expert_model_version=task.expert_model_version,
        result_version=task.result_version,
        degradation_reason=task.degradation_reason,
        current_step=task.current_step,
        pipeline_error=task.pipeline_error,
        report_summary=task.report_summary,
        created_at=task.created_at,
        completed_at=task.completed_at,
        diff_count=len(diffs),
        high_risk_count=sum(1 for d in diffs if d.risk_level == "高"),
        pending_review_count=sum(1 for d in diffs if d.review_status in pending_like_statuses),
        reference_template_id=getattr(task, "reference_template_id", "") or "",
        reference_template_title=getattr(task, "reference_template_title", "") or "",
    )


def _is_unreadable_for_pipeline(doc: Document) -> tuple[bool, dict]:
    raw = doc.raw_text or ""
    ratio = cjk_ratio(raw)
    ext = ""
    if doc.file_path:
        ext = Path(doc.file_path).suffix.lower()
    low_clause_like = is_low_quality_clause(raw[:1200] if raw else "")
    # 针对中文制度审查场景：PDF 若几乎无中文，视为解析失败，禁止进入流水线。
    unreadable = (ext == ".pdf") and len(raw) >= 200 and ratio < 0.05
    return unreadable, {
        "doc_id": doc.id,
        "ext": ext,
        "raw_len": len(raw),
        "cjk_ratio": round(ratio, 4),
        "low_clause_like": low_clause_like,
    }


def _recover_stale_running_task(db: Session, task: ReviewTask) -> None:
    if task.status != "running":
        return
    now = datetime.now(timezone.utc)
    stale_minutes = 45
    task_created_at = as_utc(task.created_at)
    recent_log = (
        db.query(PipelineRunLog)
        .filter(PipelineRunLog.task_id == task.id)
        .filter(PipelineRunLog.created_at >= task.created_at)
        .order_by(PipelineRunLog.created_at.desc())
        .first()
    )
    # 无日志：按任务创建时间判断；有日志：按最后日志时间判断
    recent_log_created_at = as_utc(recent_log.created_at) if recent_log else None
    ref_time = recent_log_created_at or task_created_at
    if not ref_time:
        return

    # 服务重启后，历史 running 任务不会自动恢复执行；若无“重启后日志”，直接判定为失效任务。
    no_log_after_boot = (recent_log is None) or (
        recent_log_created_at is not None and recent_log_created_at < SERVER_BOOT_UTC
    )
    if task_created_at is not None and task_created_at < SERVER_BOOT_UTC and no_log_after_boot:
        task.status = "failed"
        task.pipeline_error = (
            "服务已重启，历史运行任务未继续执行，已自动终止。"
            "请点击重试或新建任务重新执行。"
        )
        db.commit()
        return

    age_minutes = (now - ref_time).total_seconds() / 60.0
    if age_minutes < stale_minutes:
        return

    task.status = "failed"
    task.pipeline_error = (
        "任务长时间运行且无新进度，系统已自动终止。"
        "请点击重试或新建任务重新执行。"
    )
    db.commit()


def _invalidate_tasks_for_document(db: Session, doc_id: int, reason: str) -> None:
    task_ids = [
        r[0]
        for r in db.query(ReviewTask.id)
        .filter(
            (ReviewTask.group_document_id == doc_id) | (ReviewTask.subsidiary_document_id == doc_id)
        )
        .all()
    ]
    if not task_ids:
        return
    diff_ids = [r[0] for r in db.query(Difference.id).filter(Difference.task_id.in_(task_ids)).all()]
    if diff_ids:
        db.query(ReviewLog).filter(ReviewLog.difference_id.in_(diff_ids)).delete(
            synchronize_session=False
        )
    db.query(ReviewLog).filter(ReviewLog.task_id.in_(task_ids)).delete(synchronize_session=False)
    db.query(Difference).filter(Difference.task_id.in_(task_ids)).delete(synchronize_session=False)
    db.query(PipelineRunLog).filter(PipelineRunLog.task_id.in_(task_ids)).delete(
        synchronize_session=False
    )
    tasks = db.query(ReviewTask).filter(ReviewTask.id.in_(task_ids)).all()
    for t in tasks:
        t.status = "failed"
        t.current_step = 0
        t.pipeline_error = reason
        t.report_summary = None
    db.commit()


@router.get("/health", response_model=HealthResponse)
def health():
    s = get_settings()
    msg = "就绪" if s.llm_configured else "请在 .env 配置 LLM_API_KEY"
    return HealthResponse(status="ok", llm_configured=s.llm_configured, llm_model=s.llm_model, message=msg)


@router.get("/robustness/status")
def robustness_status():
    settings = get_settings()
    return {
        "async_mode": settings.task_executor,
        "queue_enabled": settings.gpu_queue_enabled,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "fallback_model_configured": bool(settings.llm_fallback_model),
        "max_agent_turns": settings.max_agent_turns,
        "low_confidence_threshold": 0.60,
        "checkpoint_mode": "pipeline_step_logs",
        "production_upgrade_required": [
            "GPU gateway load metrics and queue position",
            "independent OCR worker",
        ],
    }


@router.get("/runtime/status")
def runtime_status():
    settings = get_settings()
    return {
        "pipeline_mode": "hybrid",
        "accepted_legacy_modes": ["fast", "full"],
        "legacy_modes_deprecated": True,
        "executor_requested": settings.task_executor,
        "redis_url_configured": bool(settings.redis_url),
        "core_analyser_model": settings.resolved_core_model,
        "soe_expert_model": settings.resolved_expert_model,
        "dual_model_configured": settings.dual_model_configured,
        "core_endpoint_dedicated": bool(settings.core_analyser_base_url),
        "expert_endpoint_dedicated": bool(settings.soe_expert_base_url),
        "core_fallback_model": settings.core_analyser_fallback_model or settings.llm_fallback_model,
        "expert_fallback_model": settings.soe_expert_fallback_model or settings.llm_fallback_model,
        "model_routing": {
            "CoreAnalyser": "medium_model",
            "SOEExpertAgent": "large_model",
        },
        "map_workers": settings.hybrid_map_workers,
        "production_path": [
            "StructureEngine",
            "CoreAnalyser(Map)",
            "SOEExpertAgent(Reduce)",
            "EvidenceRules",
            "ReportBuilder",
        ],
    }


@router.get("/tasks/{task_id}/execution")
def task_execution(task_id: int, db: Session = Depends(get_db)):
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    checkpoints = (
        db.query(TaskCheckpoint).filter(TaskCheckpoint.task_id == task_id)
        .order_by(TaskCheckpoint.id.desc()).limit(20).all()
    )
    return {
        "task_id": task.id,
        "status": task.status,
        "mode": task.execution_mode,
        "executor_backend": task.executor_backend,
        "degradation_reason": task.degradation_reason,
        "prompt_bundle_version": task.prompt_bundle_version,
        "checkpoints": [
            {"node_key": c.node_key, "status": c.status, "created_at": c.created_at}
            for c in checkpoints
        ],
    }


@router.post("/seed/demo", response_model=SeedResponse)
def seed(db: Session = Depends(get_db)):
    result = seed_demo(db)
    return SeedResponse(
        message="演示数据已写入",
        group_document_id=result["group_document_id"],
        subsidiary_document_id=result["subsidiary_document_id"],
        task_id=result["task_id"],
    )


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(db: Session = Depends(get_db)):
    tasks = db.query(ReviewTask).order_by(ReviewTask.created_at.desc()).all()
    pending_reviews = (
        db.query(Difference)
        .filter(Difference.review_status.in_(("pending", "pending_evidence")))
        .count()
    )

    def pending_count_for(task: ReviewTask) -> int:
        return (
            db.query(Difference)
            .filter(
                Difference.task_id == task.id,
                Difference.review_status.in_(("pending", "pending_evidence")),
            )
            .count()
        )

    active = [t for t in tasks if t.status in ("reviewing", "running", "failed", "draft")]
    pending: ReviewTask | None = None
    if active:
        # 优先展示最新运行中的任务，避免历史旧任务（含旧快照）干扰当前调试。
        running_or_reviewing = [t for t in active if t.status in ("running", "reviewing")]
        scope = running_or_reviewing or active
        pending = max(scope, key=lambda t: (t.created_at or datetime.min, pending_count_for(t)))

    recent = [_task_stats(db, t) for t in tasks[:12]]
    return DashboardOut(
        pending_task=_task_stats(db, pending) if pending else None,
        total_tasks=len(tasks),
        pending_reviews=pending_reviews,
        recent_tasks=recent,
    )


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    business_domain: str | None = None,
    document_level: str | None = None,
    include_templates: bool = False,
    db: Session = Depends(get_db),
):
    q = db.query(Document).order_by(Document.created_at.desc())
    if not include_templates:
        # 脱敏范本库（org_id=deidentified）仅作单制度体检的后台参考，不在制度列表/选择中展示。
        q = q.filter((Document.org_id != "deidentified") | (Document.org_id.is_(None)))
    if business_domain:
        q = q.filter(Document.business_domain == business_domain)
    if document_level:
        q = q.filter(Document.document_level == document_level)
    return q.all()


@router.post("/documents/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile = File(...),
    document_name: str = Form(""),
    unit_name: str = Form(""),
    document_level: str = Form("subsidiary"),
    business_domain: str = Form("采购"),
    version: str = Form(""),
    db: Session = Depends(get_db),
):
    # 合并后的上传界面允许“所属单位/名称”留空，这里做服务端兜底，避免必填校验直接 422。
    document_level = (document_level or "").strip() or "subsidiary"
    business_domain = (business_domain or "").strip() or "采购"
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "document.txt"
    suffix = Path(original_name).suffix.lower()
    if suffix not in (".txt", ".doc", ".docx", ".pdf"):
        raise HTTPException(400, "仅支持 .txt / .doc / .docx / .pdf")

    try:
        content = await file.read()
        if not content:
            raise HTTPException(400, "文件为空")
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 限制")

        dest = upload_dir / safe_storage_name(original_name, suffix)
        dest.write_bytes(content)
        complex_table_pages = detect_pdf_complex_table_pages(str(dest)) if suffix == ".pdf" else []
        complex_table_note = (
            f"检测到 PDF 第 {', '.join(map(str, complex_table_pages))} 页可能包含复杂嵌套权责矩阵；"
            "AI 解析可能局部错位，请结合原始页面快照人工核验，或转换为 Word 后重新上传。"
            if complex_table_pages else ""
        )

        try:
            raw = extract_text_from_file(str(dest))
        except ParseError as e:
            low_quality = e.code == "ERR_DOC_LOW_QUALITY"
            doc = Document(
                document_name=((document_name or "").strip() or Path(original_name).stem)[:255],
                unit_name=unit_name.strip()[:128],
                document_level=document_level,
                business_domain=business_domain,
                version=(version or "")[:64],
                parse_status="low_quality_text" if low_quality else "parse_failed",
                quality_status="low_quality_text" if low_quality else "unavailable",
                parse_error_code=e.code,
                parse_error_detail=e.message,
                degradation_notes=(
                    "OCR 不可靠区域已保留为不确定内容，禁止作为正式差异证据。 " + complex_table_note
                    if low_quality else ""
                ),
                table_review_required=bool(complex_table_pages),
                complex_table_pages=",".join(map(str, complex_table_pages)),
                file_path=str(dest.resolve()),
                raw_text="[无法可靠识别：OCR质量低，原文不可作为正式审计证据]" if low_quality else None,
                file_size=len(content),
                content_hash=hashlib.sha256(content).hexdigest(),
            )
            db.add(doc)
            db.commit()
            db.refresh(doc)
            return doc
        except Exception as e:
            if dest.exists():
                dest.unlink(missing_ok=True)
            raise HTTPException(400, f"解析文件失败: {e}") from e

        if len(raw) > MAX_RAW_TEXT_CHARS:
            raw = raw[:MAX_RAW_TEXT_CHARS]
        name = (document_name or "").strip() or Path(original_name).stem
        doc = Document(
            document_name=name[:255],
            unit_name=unit_name.strip()[:128],
            document_level=document_level,
            business_domain=business_domain,
            version=(version or "")[:64],
            parse_status="parsed",
            quality_status="normal",
            degradation_notes=complex_table_note,
            table_review_required=bool(complex_table_pages),
            complex_table_pages=",".join(map(str, complex_table_pages)),
            file_path=str(dest.resolve()),
            raw_text=raw,
            file_size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        db.add(doc)
        db.flush()
        _govern_exemptions_after_group_upgrade(db, doc)
        db.commit()
        db.refresh(doc)
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"上传失败: {e}") from e


@router.get("/documents/{doc_id}/table-snapshot")
def document_table_snapshot(doc_id: int, page: int = Query(..., ge=1), db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc or not doc.file_path:
        raise HTTPException(404, "文档或原文件不存在")
    warned_pages = {int(x) for x in doc.complex_table_pages.split(",") if x.strip().isdigit()}
    if page not in warned_pages:
        raise HTTPException(404, "该页未标记为复杂表格核验区域")
    try:
        return Response(content=render_pdf_page_snapshot(doc.file_path, page), media_type="image/png")
    except ParseError as e:
        raise HTTPException(400, e.message) from e


@router.post("/documents/{doc_id}/reparse", response_model=DocumentOut)
def reparse_document(doc_id: int, db: Session = Depends(get_db)):
    """重新解析原文（修复 PDF 页码碎片等），不删除已上传文件。"""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(400, "原文件不存在，请重新上传")
    if doc.lock_status == "locked":
        raise HTTPException(409, "文档正在被审查任务使用，当前只读锁定")
    try:
        raw = extract_text_from_file(doc.file_path)
    except ParseError as e:
        raise HTTPException(400, str(e)) from e
    if len(raw) > MAX_RAW_TEXT_CHARS:
        raw = raw[:MAX_RAW_TEXT_CHARS]
    doc.raw_text = raw
    doc.parse_status = "parsed"
    db.query(Clause).filter(Clause.document_id == doc.id).delete()
    db.commit()
    _invalidate_tasks_for_document(
        db,
        doc.id,
        "关联制度已重新解析，历史差异快照已失效。请基于最新文本重新运行任务。",
    )
    db.refresh(doc)
    return doc


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    """删除制度及其条款/控制点。若已被审查任务引用则拒绝删除。"""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")

    task_refs = (
        db.query(ReviewTask)
        .filter(
            (ReviewTask.group_document_id == doc_id) | (ReviewTask.subsidiary_document_id == doc_id)
        )
        .count()
    )
    if task_refs:
        raise HTTPException(
            400,
            f"该制度已被 {task_refs} 个审查任务引用，请先在任务列表中删除相关任务后再删制度",
        )

    clause_ids = [r[0] for r in db.query(Clause.id).filter(Clause.document_id == doc_id).all()]
    if clause_ids:
        diff_refs = (
            db.query(Difference)
            .filter(
                (Difference.group_clause_id.in_(clause_ids))
                | (Difference.subsidiary_clause_id.in_(clause_ids))
            )
            .count()
        )
        if diff_refs:
            raise HTTPException(400, "该制度的条款仍被历史差异记录引用，请先删除相关审查任务")

    db.query(ControlPoint).filter(ControlPoint.document_id == doc_id).delete(synchronize_session=False)
    db.query(Clause).filter(Clause.document_id == doc_id).delete(synchronize_session=False)
    if doc.file_path:
        Path(doc.file_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return {"ok": True, "message": "制度已删除"}


@router.get("/documents/{doc_id}/preview", response_model=DocumentPreviewOut)
def preview_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    file_ext = None
    has_file = False
    if doc.file_path and Path(doc.file_path).exists():
        has_file = True
        file_ext = Path(doc.file_path).suffix.lower().lstrip(".")
    clause_count = db.query(Clause).filter(Clause.document_id == doc.id).count()
    text = doc.raw_text or ""
    if not text and doc.file_path:
        try:
            text = extract_text_from_file(doc.file_path)
        except ParseError:
            text = ""
    return DocumentPreviewOut(
        id=doc.id,
        document_name=doc.document_name,
        unit_name=doc.unit_name,
        document_level=doc.document_level,
        business_domain=doc.business_domain,
        version=doc.version,
        parse_status=doc.parse_status,
        lock_status=doc.lock_status,
        quality_status=doc.quality_status,
        parse_error_code=doc.parse_error_code,
        parse_error_detail=doc.parse_error_detail,
        degradation_notes=doc.degradation_notes,
        table_review_required=doc.table_review_required,
        complex_table_pages=doc.complex_table_pages,
        ocr_confidence=doc.ocr_confidence,
        page_count=doc.page_count,
        file_size=doc.file_size,
        file_ext=file_ext,
        has_original_file=has_file,
        text_content=text[:80000],
        clause_count=clause_count,
        created_at=doc.created_at,
    )


@router.post("/documents/{doc_id}/ai-reformat", response_model=DocumentPreviewOut)
def ai_reformat_document(doc_id: int, db: Session = Depends(get_db)):
    """对已解析文档手动执行 AI 排版整理（仅整理空格/换行、不改文字）。未配置 Key 时报错。"""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if not doc.raw_text:
        raise HTTPException(400, "该文档暂无可整理的文本")
    if doc.lock_status == "locked":
        raise HTTPException(409, "文档正在被审查任务使用，当前只读锁定")
    if not get_settings().llm_configured:
        raise HTTPException(400, "未配置大模型 API Key，无法进行 AI 排版整理")
    from app.services.text_reformat import ai_reformat_text

    new_text = ai_reformat_text(doc.raw_text, force=True)
    doc.raw_text = new_text[:MAX_RAW_TEXT_CHARS]
    db.query(Clause).filter(Clause.document_id == doc.id).delete()
    db.commit()
    return preview_document(doc_id, db)


@router.get("/documents/{doc_id}/file")
def document_file(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(404, "原文件不存在，仅可预览文本内容")
    path = Path(doc.file_path)
    media = {
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(path.suffix.lower(), "application/octet-stream")
    # 用上传时的可读名（制度名称 + 原扩展名），并按 RFC 5987 编码中文，避免文件名乱码；
    # inline 让浏览器内预览（尤其 PDF），不直接触发下载。
    display_name = (doc.document_name or path.stem).strip() or path.stem
    if not display_name.lower().endswith(path.suffix.lower()):
        display_name = f"{display_name}{path.suffix}"
    ascii_name = display_name.encode("ascii", "ignore").decode().strip() or f"document{path.suffix}"
    disposition = f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(display_name)}"
    return FileResponse(path, media_type=media, headers={"Content-Disposition": disposition})


@router.patch("/documents/{doc_id}", response_model=DocumentOut)
def update_document_meta(doc_id: int, body: DocumentMetaUpdate, db: Session = Depends(get_db)):
    """更新制度元数据（业务领域、所属单位、级别、版本）。自动识别可能出错，允许人工修正。"""
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if body.business_domain is not None:
        doc.business_domain = body.business_domain.strip()[:64]
    if body.unit_name is not None:
        doc.unit_name = body.unit_name.strip()[:128]
    if body.document_level is not None and body.document_level in ("group", "subsidiary"):
        doc.document_level = body.document_level
    if body.version is not None:
        doc.version = body.version.strip()[:64]
    db.commit()
    db.refresh(doc)
    return doc


@router.post("/documents/{doc_id}/parse", response_model=DocumentOut)
def parse_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc.lock_status == "locked":
        raise HTTPException(409, "文档正在被审查任务使用，当前只读锁定")
    if doc.file_path:
        try:
            doc.raw_text = extract_text_from_file(doc.file_path)
            doc.parse_status = "parsed"
            db.query(Clause).filter(Clause.document_id == doc.id).delete()
            db.commit()
            _invalidate_tasks_for_document(
                db,
                doc.id,
                "关联制度已重新解析，历史差异快照已失效。请基于最新文本重新运行任务。",
            )
        except ParseError as e:
            doc.parse_status = "failed"
            raise HTTPException(400, str(e)) from e
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(ReviewTask).order_by(ReviewTask.created_at.desc()).all()
    return [_task_stats(db, t) for t in tasks]


@router.post("/tasks", response_model=TaskOut)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    g = db.get(Document, body.group_document_id)
    s = db.get(Document, body.subsidiary_document_id)
    if not g or not s:
        raise HTTPException(400, "制度文档不存在")
    unusable = [d.document_name for d in (g, s) if d.parse_status != "parsed" or not d.raw_text]
    if unusable:
        raise HTTPException(400, f"以下制度尚不可审查，请先修复解析质量：{'、'.join(unusable)}")
    task = ReviewTask(
        task_name=body.task_name,
        business_domain=body.business_domain,
        description=body.description,
        group_document_id=body.group_document_id,
        subsidiary_document_id=body.subsidiary_document_id,
        task_type="group_vs_subsidiary",
        status="draft",
        execution_mode="hybrid",
        prompt_bundle_version="Hybrid_V1.0",
        core_model_version=get_settings().resolved_core_model,
        expert_model_version=get_settings().resolved_expert_model,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    # 防御 task_id 复用导致的历史脏数据污染（旧差异/旧日志）。
    stale_diff_ids = [r[0] for r in db.query(Difference.id).filter(Difference.task_id == task.id).all()]
    if stale_diff_ids:
        db.query(ReviewLog).filter(ReviewLog.difference_id.in_(stale_diff_ids)).delete(
            synchronize_session=False
        )
        db.query(Difference).filter(Difference.task_id == task.id).delete(synchronize_session=False)
    db.query(ReviewLog).filter(ReviewLog.task_id == task.id).delete(synchronize_session=False)
    db.query(PipelineRunLog).filter(PipelineRunLog.task_id == task.id).delete(
        synchronize_session=False
    )
    db.commit()
    return _task_stats(db, task)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return _task_stats(db, task)


_DESIGN_DEFECT_RULES: list[dict[str, Any]] = [
    {
        "topic": "制度目的与适用范围",
        "risk": "中",
        "keywords": ("适用范围", "适用于", "本办法适用", "本制度适用"),
        "criterion": "制度应明确适用组织、人员、事项和业务边界。",
        "suggestion": "补充适用范围条款，明确适用单位、人员、业务事项以及不适用或例外情形。",
    },
    {
        "topic": "职责分工与归口管理",
        "risk": "高",
        "keywords": ("职责", "负责", "归口", "责任部门", "责任人"),
        "criterion": "制度应明确归口部门、执行部门、审批主体和监督主体的职责分工。",
        "suggestion": "增加职责分工章节，逐项明确归口、申请、审核、审批、执行和监督责任。",
    },
    {
        "topic": "审批授权与决策机制",
        "risk": "高",
        "keywords": ("审批", "审核", "批准", "报批", "授权", "决策"),
        "criterion": "关键事项应明确审批层级、授权边界、触发条件和决策程序。",
        "suggestion": "补充审批授权矩阵，明确事项类型、金额或条件阈值、审批层级和禁止越权要求。",
    },
    {
        "topic": "不相容职责分离",
        "risk": "高",
        "keywords": ("不相容", "职责分离", "岗位分离", "不得兼任", "相互制约"),
        "criterion": "申请、审核、审批、执行、验收、记账和监督等不相容职责应适当分离。",
        "suggestion": "明确不相容岗位和职责分离要求，并设置复核或交叉监督机制。",
    },
    {
        "topic": "流程记录与档案留痕",
        "risk": "中",
        "keywords": ("记录", "台账", "归档", "档案", "留存", "留痕"),
        "criterion": "关键流程应形成记录、台账或档案，并明确保管责任和期限。",
        "suggestion": "补充申请、审批、执行、复核、异常处理等环节的记录留痕和归档要求。",
    },
    {
        "topic": "监督检查与整改闭环",
        "risk": "高",
        "keywords": ("监督", "检查", "审计", "稽核", "整改", "复核"),
        "criterion": "制度应设置监督检查、问题反馈、整改和复核闭环。",
        "suggestion": "增加监督检查和整改闭环章节，明确检查频次、问题报告、整改期限和复核责任。",
    },
    {
        "topic": "异常与例外处理",
        "risk": "中",
        "keywords": ("异常", "例外", "特殊情况", "紧急情况", "应急", "补批"),
        "criterion": "制度应明确异常、紧急和例外事项的处理及补充审批要求。",
        "suggestion": "补充异常和例外处理机制，明确适用条件、审批权限、补批时限和留痕要求。",
    },
    {
        "topic": "违规责任与问责机制",
        "risk": "高",
        "keywords": ("问责", "责任追究", "违规责任", "处罚", "处分", "追责"),
        "criterion": "制度应明确违规行为、责任认定、处理程序和问责措施。",
        "suggestion": "增加违规责任章节，明确违规情形、责任主体、处理权限和追责程序。",
    },
    {
        "topic": "制度解释、修订与生效机制",
        "risk": "低",
        "keywords": ("解释权", "负责解释", "修订", "废止", "生效", "施行", "实施日期"),
        "criterion": "制度应明确解释部门、修订机制、生效日期以及旧制度废止关系。",
        "suggestion": "在附则中明确解释部门、生效日期、修订条件和原制度废止安排。",
    },
]


def _single_audit_standards(
    db: Session,
    doc: Document,
    business_domain: str = "",
) -> list[dict[str, Any]]:
    text = f"{doc.document_name} {doc.business_domain} {doc.raw_text or ''}"
    domains = infer_standard_domains(text, preferred_domain=business_domain or doc.business_domain)
    return load_standard_controls(
        db,
        domains,
        include_general=False,
        context_text=doc.document_name,
    )


def _ensure_clause_rows(db: Session, doc: Document) -> list[dict[str, Any]]:
    rows = db.query(Clause).filter(Clause.document_id == doc.id).order_by(Clause.id.asc()).all()
    if not rows:
        for item in split_clauses_local(doc.raw_text or ""):
            row = Clause(
                document_id=doc.id,
                chapter_title=item.get("chapter_title", ""),
                clause_no=item.get("clause_no", ""),
                clause_text=item.get("clause_text", ""),
                page_no=item.get("page_no"),
                location_label=item.get("location_label", ""),
            )
            db.add(row)
        db.flush()
        rows = db.query(Clause).filter(Clause.document_id == doc.id).order_by(Clause.id.asc()).all()
    return [
        {
            "id": c.id,
            "chapter_title": c.chapter_title,
            "clause_no": c.clause_no,
            "clause_text": c.clause_text,
            "location_label": c.location_label,
        }
        for c in rows
    ]


def _coverage_score(standard: dict[str, str], cp: dict[str, Any]) -> float:
    topic = standard.get("control_topic", "")
    requirement = standard.get("key_requirement", "")
    cp_text = f"{cp.get('control_topic', '')} {cp.get('requirement', '')} {cp.get('clause_text', '')}"
    score = text_overlap_score(f"{topic} {requirement}", cp_text)
    if topic and topic == cp.get("control_topic"):
        score += 0.45
    if topic and topic[:4] in cp_text:
        score += 0.15
    return score


def _add_design_defect_differences(db: Session, task: ReviewTask, doc: Document) -> int:
    full_text = normalize_extracted_text(doc.raw_text or "")
    created = 0
    for rule in _DESIGN_DEFECT_RULES:
        if any(keyword in full_text for keyword in rule["keywords"]):
            continue
        topic = rule["topic"]
        db.add(
            Difference(
                task_id=task.id,
                diff_type="设计缺陷",
                risk_level=rule["risk"],
                control_topic=topic,
                summary=f"{topic}：制度结构中未发现该设计要素",
                group_clause_id=None,
                subsidiary_clause_id=None,
                group_excerpt=f"制度设计标准：{rule['criterion']}",
                subsidiary_excerpt="经全文检索，未发现能够证明该制度设计要素已被明确规定的内容。",
                group_location="制度设计检查规则",
                subsidiary_location="全文结构检查",
                ai_reason=(
                    f"系统检查了制度全文的章节结构和关键表述，未发现「{topic}」相关设计。"
                    "该缺陷可能导致制度责任不清、执行标准不统一或监督整改无法闭环。"
                ),
                suggestion=rule["suggestion"],
                confidence=0.88,
                evidence_ok=True,
                review_status="pending",
            )
        )
        created += 1
    return created


def _run_single_document_audit(db: Session, task: ReviewTask, doc: Document) -> None:
    clauses = _ensure_clause_rows(db, doc)
    standards = _single_audit_standards(db, doc, task.business_domain)
    cps_raw = extract_control_points_local(clauses, standard_cps=standards)
    db.query(ControlPoint).filter(ControlPoint.document_id == doc.id).delete(synchronize_session=False)
    cps: list[dict[str, Any]] = []
    for cp in cps_raw:
        idx = cp["clause_index"]
        if idx < 0 or idx >= len(clauses):
            continue
        row = ControlPoint(
            clause_id=clauses[idx]["id"],
            document_id=doc.id,
            business_domain=task.business_domain,
            control_topic=cp["control_topic"],
            subject_role=cp["subject_role"],
            action=cp["action"],
            object=cp["object"],
            threshold=cp["threshold"],
            requirement=cp["requirement"],
        )
        db.add(row)
        db.flush()
        item = dict(cp)
        item["id"] = row.id
        item["clause_id"] = row.clause_id
        item["clause_text"] = clauses[idx]["clause_text"]
        item["location_label"] = clauses[idx]["location_label"]
        cps.append(item)

    db.query(Difference).filter(Difference.task_id == task.id).delete(synchronize_session=False)
    created = 0
    for standard in standards:
        best = max(
            ((_coverage_score(standard, cp), cp) for cp in cps),
            key=lambda item: item[0],
            default=(0.0, None),
        )
        if best[0] >= 0.28:
            continue
        topic = standard["control_topic"]
        requirement = standard["key_requirement"]
        standard_code = standard["standard_code"]
        db.add(
            Difference(
                task_id=task.id,
                diff_type="控制缺失",
                risk_level="高" if standard.get("importance") in ("required", "high") else "中",
                control_topic=topic,
                summary=f"{topic}：制度未发现充分覆盖该控制要求",
                group_clause_id=None,
                subsidiary_clause_id=None,
                group_excerpt=f"标准控制点 {standard_code}：{topic}。{requirement}",
                subsidiary_excerpt="未在该制度全文中发现足以证明已覆盖的责任主体、控制动作、审批/监督或留痕要求。",
                group_location=f"标准控制点库/{standard_code}",
                group_external_regulation=standard.get("external_regulation", ""),
                group_external_basis=standard.get("external_basis", ""),
                subsidiary_location="全文覆盖判断",
                ai_reason=(
                    f"系统依据内置标准控制点 {standard_code} 审查全文，未发现对「{topic}」的实质覆盖。"
                    f"标准依据：{standard.get('source_basis') or '产品内置标准控制点库'}。"
                ),
                suggestion=f"建议结合标准要求补充「{topic}」相关条款：{requirement}",
                confidence=0.82,
                evidence_ok=True,
                review_status="pending",
            )
        )
        created += 1

    created += _add_design_defect_differences(db, task, doc)

    vague_terms = ("原则上", "必要时", "适时", "视情况", "一般应", "可根据")
    for c in clauses:
        text = c.get("clause_text", "")
        hit = next((term for term in vague_terms if term in text), "")
        if not hit:
            continue
        excerpt, _ = pick_clause_excerpt(text, hint=hit, topic="表述不清", max_len=300)
        db.add(
            Difference(
                task_id=task.id,
                diff_type="表述不清",
                risk_level="低",
                control_topic="制度表述清晰度",
                summary=f"制度表述清晰度：存在“{hit}”等弹性表述",
                group_clause_id=None,
                subsidiary_clause_id=c["id"],
                group_excerpt="标准控制点：关键控制要求应具备可执行、可检查、可追责的明确标准。",
                subsidiary_excerpt=excerpt,
                group_location="标准控制点库",
                subsidiary_location=c.get("location_label", ""),
                ai_reason=f"该条款使用“{hit}”等弹性措辞，可能导致执行条件、审批边界或监督标准不清。",
                suggestion="建议将弹性表述改为明确触发条件、审批层级、办理时限、记录材料和责任后果。",
                confidence=0.74,
                evidence_ok=True,
                review_status="pending",
            )
        )
        created += 1
        if created >= 30:
            break

    db.flush()
    high = db.query(Difference).filter(Difference.task_id == task.id, Difference.risk_level == "高").count()
    task.status = "reviewing"
    task.current_step = 6
    task.completed_at = utc_now()
    task.report_summary = (
        f"【单制度设计缺陷检查】系统基于「{task.business_domain}」领域的 {len(standards)} 项内置标准控制点"
        f"和 {len(_DESIGN_DEFECT_RULES)} 项制度设计规则审查《{doc.document_name}》，"
        f"识别 {created} 项制度缺陷，其中高风险 {high} 项。"
        " 本模块不依赖集团制度，适用于单份制度的结构完整性、权责设计、可执行性和内控缺口检查。"
    )
    for step, agent, message in [
        (1, "StructureEngine", f"单制度拆条完成：{len(clauses)} 条"),
        (2, "StandardControlLibrary", f"标准控制点清单：{len(standards)} 项"),
        (2, "ControlRuleEngine", f"本制度控制点抽取：{len(cps)} 项"),
        (4, "DesignDefectRules", f"单制度设计缺陷识别完成：{created} 项"),
        (6, "ReportBuilder", "单制度设计缺陷检查报告已生成"),
    ]:
        db.add(PipelineRunLog(task_id=task.id, step=step, agent_name=agent, status="completed", message=message))
    db.commit()


@router.post("/single-audits/run", response_model=TaskOut)
def run_single_audit(body: SingleAuditCreate, db: Session = Depends(get_db)):
    doc = db.get(Document, body.document_id)
    if not doc:
        raise HTTPException(404, "制度不存在")
    if not doc.raw_text:
        raise HTTPException(400, "该制度没有可审查文本，请先上传并解析文件")
    # 参考范本：显式选择优先；为空按领域自动匹配；"__none__" 表示不参考范本。
    requested = (body.template_id or "").strip()
    template_id = ""
    if requested == "__none__":
        template_id = ""
    elif requested and get_template(requested):
        template_id = requested
    else:
        domains = infer_standard_domains(
            f"{doc.document_name} {doc.business_domain} {doc.raw_text or ''}",
            preferred_domain=body.business_domain or doc.business_domain,
        )
        template_id = auto_match_template(doc.document_name, doc.raw_text or "", domains) or ""
    ref_tpl = get_template(template_id) if template_id else None
    task = ReviewTask(
        task_name=body.task_name or f"单制度设计缺陷检查：{doc.document_name}",
        business_domain=body.business_domain or doc.business_domain or "内控",
        description="单制度设计缺陷检查（无集团制度基准）",
        group_document_id=doc.id,
        subsidiary_document_id=doc.id,
        task_type="single",
        status="running",
        current_step=0,
        reference_template_id=template_id,
        reference_template_title=ref_tpl["title"] if ref_tpl else "",
    )
    db.add(task)
    db.commit()  # 立即提交：任务以 running 入库并释放写锁，体检改到后台线程执行（不阻塞请求与其它写操作）
    db.refresh(task)
    _SINGLE_AUDIT_POOL.submit(
        _single_audit_run_worker, task.id, doc.id, (body.mode or "fast"), template_id
    )
    return _task_stats(db, task)


SINGLE_AUDIT_AI_SYSTEM = (
    "你是企业内控审查专家。下面给你一份制度的正文，以及若干条来自同一业务领域的标准控制点。"
    "重要前提：一份制度只就其自身【主题与适用范围】负责，专项制度无需覆盖本领域的全部控制点。"
    "请对每条控制点分两步判断："
    "①适用性 applicable：该控制点是否落在本制度的主题与适用范围之内。"
    "若与本制度主题无关（例如本制度只讲资产减值准备的核销，而控制点讲的是无形资产的注册登记），"
    "则 applicable=false，不得作为缺陷。"
    "②覆盖性 covered：仅对适用的控制点，判断本制度是否实质覆盖其要求（关注责任主体、控制动作、"
    "审批/授权、记录留痕、监督问责等，不要求字面一致，可跨章节理解）。"
    "严格基于给定正文判断，正文中没有的不要臆测。"
    "只对【适用且未实质覆盖或明显弱化】的控制点给出风险与整改建议。"
    '返回 JSON：{"items":[{"code":"标准编号","applicable":true或false,"covered":true或false,'
    '"risk":"高或中或低","reason":"判断理由","suggestion":"整改建议"}]}'
)


def _run_single_document_audit_ai(db: Session, task: ReviewTask, doc: Document) -> None:
    """单制度深度体检：对每条标准控制点用大模型做全文语义覆盖判断（分批并行）。"""
    clauses = _ensure_clause_rows(db, doc)
    standards = _single_audit_standards(db, doc)
    full_text = normalize_extracted_text(doc.raw_text or "")[:7000]
    # 释放拆条/标准库 seed 产生的写锁：LLM 判断期间不持有 SQLite 写锁，避免阻塞上传与其它体检。
    db.commit()

    client = LLMClient(timeout=45)
    batches = [standards[i:i + 8] for i in range(0, len(standards), 8)]

    def judge(batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = {
            "document_text": full_text,
            "standards": [
                {"code": s["standard_code"], "topic": s["control_topic"], "requirement": s["key_requirement"]}
                for s in batch
            ],
        }
        try:
            data = client.complete_json(
                SINGLE_AUDIT_AI_SYSTEM, json.dumps(payload, ensure_ascii=False), max_retries=1
            )
            return data.get("items", []) if isinstance(data, dict) else []
        except Exception:
            return []

    items_all: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for items in pool.map(judge, batches):
            items_all.extend(items)
    by_code = {it.get("code"): it for it in items_all if isinstance(it, dict)}

    # —— 写阶段：到这里才开始写库，事务很短且无网络调用，写锁仅持有毫秒级 ——
    db.query(Difference).filter(Difference.task_id == task.id).delete(synchronize_session=False)
    created = 0
    applicable_total = 0
    for s in standards:
        it = by_code.get(s["standard_code"])
        if it is None:
            continue
        # 适用范围之外的控制点不算缺陷（避免专项制度被要求覆盖本领域无关控制点）。
        if it.get("applicable") is False:
            continue
        applicable_total += 1
        if it.get("covered") is True:
            continue
        risk = it.get("risk")
        if risk not in ("高", "中", "低"):
            risk = "高" if s.get("importance") == "required" else "中"
        db.add(
            Difference(
                task_id=task.id,
                diff_type="控制缺失",
                risk_level=risk,
                control_topic=s["control_topic"],
                summary=f"{s['control_topic']}：AI 判断未实质覆盖该控制要求",
                group_clause_id=None,
                subsidiary_clause_id=None,
                group_excerpt=f"标准控制点：{s['control_topic']}。{s['key_requirement']}",
                subsidiary_excerpt="（AI 深度体检：基于本制度全文语义判断）",
                group_location="标准控制点库",
                group_external_regulation=s.get("external_regulation", ""),
                group_external_basis=s.get("external_basis", ""),
                subsidiary_location="全文语义覆盖判断",
                ai_reason=(it.get("reason") or "")[:1000],
                suggestion=(it.get("suggestion") or f"建议补充「{s['control_topic']}」相关条款。")[:1000],
                confidence=0.7,
                evidence_ok=True,
                review_status="pending",
            )
        )
        created += 1

    db.flush()
    high = db.query(Difference).filter(Difference.task_id == task.id, Difference.risk_level == "高").count()
    task.status = "reviewing"
    task.current_step = 6
    task.completed_at = utc_now()
    scope_note = ""
    if applicable_total == 0:
        scope_note = (
            " ⚠ 注意：标准控制点库未匹配到适用于本制度主题的控制点"
            "（可能业务领域选择不当、本制度主题超出标准库覆盖范围，或被判定为全部不适用），"
            "本次标准库检查未实质覆盖，请确认“标准控制点领域”是否选对，并以范本缺口和人工复核为准。"
        )
    task.report_summary = (
        f"【单制度深度体检·AI】基于 {len(standards)} 项标准控制点（适用 {applicable_total} 项），"
        f"对《{doc.document_name}》全文做语义覆盖判断，识别 {created} 项控制缺失，其中高风险 {high} 项。"
        f"该模式由大模型逐条判断，较慢但更贴近语义。{scope_note}"
    )
    for step, agent, message in [
        (1, "StructureEngine", f"单制度拆条完成：{len(clauses)} 条"),
        (2, "StandardControlLibrary", f"标准控制点：{len(standards)} 项"),
        (4, "CoreAnalyser", f"AI 语义覆盖判断完成：{created} 项缺失"),
        (6, "ReportBuilder", "单制度深度体检报告已生成"),
    ]:
        db.add(PipelineRunLog(task_id=task.id, step=step, agent_name=agent, status="completed", message=message))
    db.commit()


UNIVERSAL_REVIEW_SYSTEM = (
    "你是企业内控审查专家。下面给你一份制度正文 document_text，以及可选的联网检索摘要 web_context（可能为空）。"
    "该制度未匹配到系统内置的领域标准控制点与同领域范本，请改为按《企业内部控制基本规范》的通用结构性要求，"
    "对它做「通用内控设计体检」。逐一判断该制度是否实质具备以下设计要素（covered=true或false）："
    "①制度目的、适用范围与业务边界是否清晰完整；②归口/执行/审批/监督职责是否明确；"
    "③授权审批、不相容职责分离与决策机制是否健全；④关键流程的控制活动与记录留痕是否完备；"
    "⑤监督检查、整改闭环与例外处理是否健全；⑥问责机制是否明确；⑦解释/修订/生效机制与弹性表述是否合理。"
    "若提供了 web_context，可据其补充该制度所属业务可能适用的外部监管要求，并在 reason 说明、在 source 填对应链接。"
    "严格基于正文判断，正文没有的不臆测。只对 covered=false 的要素给出风险与整改建议。"
    '返回 JSON：{"items":[{"dimension":"要素名","covered":true或false,'
    '"risk":"高或中或低","reason":"判断理由","suggestion":"整改建议","source":"参考链接或空"}]}'
)


def _run_universal_design_review(db: Session, task: ReviewTask, doc: Document) -> None:
    """兜底：标准控制点与范本均零命中时，按内控基本规范做通用结构性体检（可联网检索外部要求）。"""
    full_text = normalize_extracted_text(doc.raw_text or "")[:7000]
    web_context = ""
    web_sources: list[str] = []
    try:
        from app.services.web_search import search as _web_search, format_for_prompt

        if get_settings().web_search_configured:
            results = _web_search(f"{doc.document_name} {task.business_domain} 内控 管理 监管要求 规定")
            web_context = format_for_prompt(results)
            web_sources = [r.get("url", "") for r in results if r.get("url")]
    except Exception:  # noqa: BLE001
        web_context, web_sources = "", []

    items: list[dict[str, Any]] = []
    try:
        client = LLMClient(timeout=45)
        user = json.dumps({"document_text": full_text, "web_context": web_context}, ensure_ascii=False)
        data = client.complete_json(UNIVERSAL_REVIEW_SYSTEM, user, max_retries=1)
        items = data.get("items", []) if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001
        items = []

    created = 0
    for it in items:
        if not isinstance(it, dict) or it.get("covered") is True:
            continue
        topic = (it.get("dimension") or "内控设计要素").strip()[:128]
        risk = it.get("risk") if it.get("risk") in ("高", "中", "低") else "中"
        reason = (it.get("reason") or f"未发现「{topic}」相关的明确设计。")[:1000]
        src = (it.get("source") or "").strip()
        if src:
            reason = f"{reason}\n参考：{src}"
        db.add(
            Difference(
                task_id=task.id,
                diff_type="设计缺陷",
                risk_level=risk,
                control_topic=topic,
                summary=f"{topic}：通用内控设计体检发现该要素可能不完备",
                group_clause_id=None,
                subsidiary_clause_id=None,
                group_excerpt=f"通用内控设计要素：{topic}（依据《企业内部控制基本规范》）",
                subsidiary_excerpt="（通用内控设计体检：对照内控基本规范的结构性要求做全文判断）",
                group_location="通用内控设计体检",
                subsidiary_location="全文结构判断",
                ai_reason=reason,
                suggestion=(it.get("suggestion") or f"建议补充「{topic}」相关条款。")[:1000],
                confidence=0.6,
                evidence_ok=True,
                review_status="pending",
            )
        )
        created += 1

    db.flush()
    web_note = "（联网检索辅助）" if web_context else ""
    src_note = ("　参考来源：" + "；".join(web_sources[:3])) if web_sources else ""
    task.report_summary = (
        (task.report_summary or "")
        + f" ⓘ 未匹配到领域标准控制点与范本，已执行【通用内控设计体检】{web_note}："
        f"对照《企业内部控制基本规范》的结构性要求识别 {created} 项设计缺口。"
        f"本结果为通用兜底、置信度较低，建议人工补充领域专项要求并复核。{src_note}"
    )
    db.add(PipelineRunLog(task_id=task.id, step=6, agent_name="UniversalDesignReview",
                          status="completed", message=f"通用内控设计体检完成：{created} 项（联网检索：{'是' if web_context else '否'}）"))
    db.commit()


# 单制度体检为纯确定性逻辑（不调用大模型），瓶颈在文档解析，适合并行。
_SINGLE_AUDIT_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="single-audit")


def _single_audit_worker(task_id: int, document_id: int) -> None:
    """后台并行执行一份单制度体检：解析 + 确定性缺陷检查，全程独立 DB 会话。"""
    db = db_module.SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        doc = db.get(Document, document_id)
        if not task or not doc:
            return
        try:
            if not doc.raw_text:
                raw = extract_text_from_file(doc.file_path or "")
                if len(raw) > MAX_RAW_TEXT_CHARS:
                    raw = raw[:MAX_RAW_TEXT_CHARS]
                doc.raw_text = raw
                doc.parse_status = "parsed"
                doc.quality_status = "normal"
                db.commit()
            _run_single_document_audit(db, task, doc)
        except ParseError as e:
            task.status = "failed"
            task.pipeline_error = e.message
            doc.parse_status = "low_quality_text" if e.code == "ERR_DOC_LOW_QUALITY" else "parse_failed"
            doc.parse_error_code = e.code
            doc.parse_error_detail = e.message
            db.commit()
        except Exception as e:  # noqa: BLE001
            task.status = "failed"
            task.pipeline_error = str(e)
            db.commit()
    finally:
        db.close()


def _single_audit_run_worker(task_id: int, document_id: int, mode: str, template_id: str) -> None:
    """后台执行单制度体检（AI 或确定性）+ 范本缺口；独立 DB 会话，避免占用请求线程与长写锁。"""
    db = db_module.SessionLocal()
    try:
        task = db.get(ReviewTask, task_id)
        doc = db.get(Document, document_id)
        if not task or not doc:
            return
        try:
            if (mode or "fast") == "ai" and get_settings().llm_configured:
                _run_single_document_audit_ai(db, task, doc)
            else:
                _run_single_document_audit(db, task, doc)
            if template_id:
                add_template_coverage_differences(db, task, doc, template_id)
                db.commit()
            # 兜底：标准控制点与范本都未产出任何发现 → 通用内控设计体检（可联网检索外部要求）。
            if db.query(Difference).filter(Difference.task_id == task.id).count() == 0:
                _run_universal_design_review(db, task, doc)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            task = db.get(ReviewTask, task_id)
            if task:
                task.status = "failed"
                task.pipeline_error = str(e)[:500]
                db.commit()
    finally:
        db.close()


@router.post("/single-audits/batch")
async def run_single_audit_batch(
    files: list[UploadFile] = File(...),
    business_domain: str = Form("内控"),
    db: Session = Depends(get_db),
):
    """批量上传多份制度并并行体检，立即返回任务列表供前端轮询。并发上限由线程池控制。"""
    if not files:
        raise HTTPException(400, "请至少选择一个制度文件")
    if len(files) > 20:
        raise HTTPException(400, "单次批量最多 20 份，请分批提交")
    settings = get_settings()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    domain = (business_domain or "内控").strip() or "内控"

    results: list[dict[str, Any]] = []
    pending: list[tuple[int, int]] = []
    for file in files:
        original_name = file.filename or "document.txt"
        suffix = Path(original_name).suffix.lower()
        if suffix not in (".txt", ".doc", ".docx", ".pdf"):
            results.append({"file": original_name, "ok": False, "error": "仅支持 .txt/.doc/.docx/.pdf"})
            continue
        content = await file.read()
        if not content:
            results.append({"file": original_name, "ok": False, "error": "文件为空"})
            continue
        if len(content) > MAX_UPLOAD_BYTES:
            results.append({"file": original_name, "ok": False, "error": f"超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 限制"})
            continue
        dest = upload_dir / safe_storage_name(original_name, suffix)
        dest.write_bytes(content)
        name = Path(original_name).stem
        doc = Document(
            document_name=name[:255],
            unit_name=name[:128],
            document_level="subsidiary",
            business_domain=domain,
            parse_status="pending",
            quality_status="normal",
            file_path=str(dest.resolve()),
            file_size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        db.add(doc)
        db.flush()
        task = ReviewTask(
            task_name=f"单份制度体检：{name}",
            business_domain=domain,
            description="单制度设计缺陷检查（批量并行）",
            group_document_id=doc.id,
            subsidiary_document_id=doc.id,
            task_type="single",
            status="queued",
            current_step=0,
        )
        db.add(task)
        db.flush()
        results.append({
            "file": original_name,
            "ok": True,
            "task_id": task.id,
            "document_id": doc.id,
            "task_name": task.task_name,
        })
        pending.append((task.id, doc.id))
    db.commit()

    for task_id, document_id in pending:
        _SINGLE_AUDIT_POOL.submit(_single_audit_worker, task_id, document_id)

    return {
        "submitted": len(pending),
        "total": len(results),
        "max_parallel": 4,
        "tasks": results,
    }


@router.get("/tasks/{task_id}/parse-preview")
def task_parse_preview(
    task_id: int,
    limit: int = Query(20, ge=1, le=100),
    excerpt_len: int = Query(300, ge=80, le=1200),
    db: Session = Depends(get_db),
):
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")

    def _clauses_for_doc(doc_id: int) -> list[dict]:
        rows = (
            db.query(Clause)
            .filter(Clause.document_id == doc_id)
            .order_by(Clause.id.asc())
            .limit(limit)
            .all()
        )
        items = []
        for c in rows:
            text = c.clause_text or ""
            items.append(
                {
                    "id": c.id,
                    "chapter_title": c.chapter_title or "",
                    "clause_no": c.clause_no or "",
                    "location_label": c.location_label or "",
                    "excerpt": text[:excerpt_len],
                    "text_len": len(text),
                }
            )
        return items

    group_doc = db.get(Document, task.group_document_id)
    sub_doc = db.get(Document, task.subsidiary_document_id)
    group_items = _clauses_for_doc(task.group_document_id)
    sub_items = _clauses_for_doc(task.subsidiary_document_id)
    return {
        "task_id": task.id,
        "group_document_name": group_doc.document_name if group_doc else "",
        "sub_document_name": sub_doc.document_name if sub_doc else "",
        "group_clauses": group_items,
        "sub_clauses": sub_items,
    }


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    """删除审查任务及其差异、复核记录、流水线日志。"""
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status == "running":
        raise HTTPException(400, "任务流水线运行中，请等待完成后再删除")

    diff_ids = [r[0] for r in db.query(Difference.id).filter(Difference.task_id == task_id).all()]
    if diff_ids:
        db.query(DiffClauseMapping).filter(DiffClauseMapping.difference_id.in_(diff_ids)).delete(
            synchronize_session=False
        )
        db.query(ReviewLog).filter(ReviewLog.difference_id.in_(diff_ids)).delete(synchronize_session=False)
        db.query(ExemptionRule).filter(ExemptionRule.difference_id.in_(diff_ids)).delete(synchronize_session=False)
        db.query(SupplementRequest).filter(SupplementRequest.difference_id.in_(diff_ids)).delete(synchronize_session=False)
    db.query(ReviewLog).filter(ReviewLog.task_id == task_id).delete(synchronize_session=False)
    db.query(Difference).filter(Difference.task_id == task_id).delete(synchronize_session=False)
    db.query(PipelineRunLog).filter(PipelineRunLog.task_id == task_id).delete(synchronize_session=False)
    db.query(TaskCheckpoint).filter(TaskCheckpoint.task_id == task_id).delete(synchronize_session=False)
    db.query(TaskExecutionEvent).filter(TaskExecutionEvent.task_id == task_id).delete(synchronize_session=False)
    for doc_id in {task.group_document_id, task.subsidiary_document_id}:
        doc = db.get(Document, doc_id)
        if doc:
            doc.lock_status = "unlocked"
    db.delete(task)
    db.commit()
    return {"ok": True, "message": "任务已删除"}


def _run_pipeline_thread(task_id: int, from_step: int = 1, mode: str | None = None) -> None:
    db = db_module.SessionLocal()
    try:
        def on_event(tid, step, agent, status, message, progress):
            publish_event(tid, step, agent, status, message, progress)

        orch = PipelineOrchestrator(db, mode=mode)
        orch.set_event_callback(on_event)
        orch.run(task_id, from_step=from_step)
        publish_event(task_id, 6, "Orchestrator", "done", "流水线全部完成", 1.0)
    except Exception as e:
        publish_event(task_id, 0, "Orchestrator", "failed", str(e), 0)
    finally:
        task = db.get(ReviewTask, task_id)
        if task:
            for doc_id in {task.group_document_id, task.subsidiary_document_id}:
                doc = db.get(Document, doc_id)
                if doc:
                    doc.lock_status = "unlocked"
            db.commit()
        db.close()


@router.post("/tasks/{task_id}/run")
def run_task(
    task_id: int,
    mode: str | None = Query(None, description="hybrid；fast/full 仅作为弃用兼容参数"),
    db: Session = Depends(get_db),
):
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    g_doc = db.get(Document, task.group_document_id)
    s_doc = db.get(Document, task.subsidiary_document_id)
    if not g_doc or not s_doc:
        raise HTTPException(400, "关联制度不存在")
    if g_doc.parse_status != "parsed" or s_doc.parse_status != "parsed":
        raise HTTPException(400, "关联制度存在解析失败或低质量状态，请先重新上传或解析")
    g_bad, _ = _is_unreadable_for_pipeline(g_doc)
    s_bad, _ = _is_unreadable_for_pipeline(s_doc)
    if g_bad or s_bad:
        bad_name = s_doc.document_name if s_bad else g_doc.document_name
        raise HTTPException(
            400,
            f"文档《{bad_name}》解析结果质量过低（疑似OCR乱码），已阻止运行。请先在制度库重新解析或上传OCR质量更高的PDF。",
        )
    if task.status == "running":
        raise HTTPException(400, "该任务流水线正在运行中，请稍候完成后再操作")
    if not get_settings().llm_configured:
        raise HTTPException(400, "LLM_API_KEY 未配置")
    requested_mode = (mode or get_settings().pipeline_mode or "hybrid").lower()
    if requested_mode not in ("fast", "full", "hybrid"):
        raise HTTPException(400, "mode 必须是 hybrid；fast/full 仅作为兼容参数")
    pipeline_mode = "hybrid"
    deprecation_notice = (
        f"参数 {requested_mode} 已弃用并映射至 Hybrid Pipeline。"
        if requested_mode in ("fast", "full") else ""
    )
    task.status = "running"
    task.current_step = 0
    g_doc.lock_status = "locked"
    s_doc.lock_status = "locked"
    db.commit()
    submission = submit_pipeline(_run_pipeline_thread, task_id, 1, pipeline_mode)
    task.execution_mode = pipeline_mode
    task.executor_backend = submission.backend
    task.degradation_reason = submission.notice
    db.add(
        TaskExecutionEvent(
            task_id=task.id,
            event_type="pipeline_submitted",
            severity="warning" if submission.degraded or deprecation_notice else "info",
            error_code="EXECUTOR_DEGRADED" if submission.degraded else "",
            message=deprecation_notice or submission.notice or "Hybrid Pipeline 已提交",
            detail_json=json.dumps(
                {"requested_mode": requested_mode, "actual_mode": pipeline_mode, "executor": submission.backend},
                ensure_ascii=False,
            ),
        )
    )
    db.commit()
    return {
        "message": "Hybrid Pipeline 已启动",
        "task_id": task_id,
        "mode": pipeline_mode,
        "deprecated_notice": deprecation_notice,
        "executor_backend": submission.backend,
        "degradation_notice": submission.notice,
        "eta_hint": "约 1–2 分钟（结构化工程流水线 + Core Analyser + 国企专家仲裁）",
    }


def _clear_retry_state(db: Session, task: ReviewTask, from_step: int) -> None:
    db.query(PipelineRunLog).filter(
        PipelineRunLog.task_id == task.id,
        PipelineRunLog.step >= from_step,
    ).delete(synchronize_session=False)
    task.pipeline_error = None
    task.current_step = max(0, from_step - 1)
    if from_step <= 4:
        diff_ids = [
            r[0]
            for r in db.query(Difference.id)
            .filter(Difference.task_id == task.id)
            .all()
        ]
        if diff_ids:
            db.query(DiffClauseMapping).filter(DiffClauseMapping.difference_id.in_(diff_ids)).delete(
                synchronize_session=False
            )
            db.query(ExemptionRule).filter(ExemptionRule.difference_id.in_(diff_ids)).delete(
                synchronize_session=False
            )
            db.query(SupplementRequest).filter(SupplementRequest.difference_id.in_(diff_ids)).delete(
                synchronize_session=False
            )
            db.query(ReviewLog).filter(ReviewLog.difference_id.in_(diff_ids)).delete(
                synchronize_session=False
            )
        db.query(ReviewLog).filter(ReviewLog.task_id == task.id).delete(
            synchronize_session=False
        )
        db.query(Difference).filter(Difference.task_id == task.id).delete(
            synchronize_session=False
        )
        task.report_summary = None
    if from_step <= 1:
        db.query(TaskCheckpoint).filter(TaskCheckpoint.task_id == task.id).delete(
            synchronize_session=False
        )
        task.result_version += 1


@router.post("/tasks/{task_id}/retry")
def retry_task(
    task_id: int,
    from_step: int = Query(1, ge=1, le=6),
    mode: str | None = Query(None),
    db: Session = Depends(get_db),
):
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status == "running":
        raise HTTPException(400, "该任务流水线正在运行中")
    requested_mode = (mode or get_settings().pipeline_mode or "hybrid").lower()
    if requested_mode not in ("fast", "full", "hybrid"):
        raise HTTPException(400, "mode 必须是 hybrid；fast/full 仅作为兼容参数")
    pipeline_mode = "hybrid"
    _clear_retry_state(db, task, from_step)
    task.status = "running"
    db.commit()
    submission = submit_pipeline(_run_pipeline_thread, task_id, from_step, pipeline_mode)
    task.execution_mode = pipeline_mode
    task.executor_backend = submission.backend
    task.degradation_reason = submission.notice
    db.add(
        TaskExecutionEvent(
            task_id=task.id,
            event_type="pipeline_resumed",
            severity="warning" if submission.degraded else "info",
            error_code="EXECUTOR_DEGRADED" if submission.degraded else "",
            message=submission.notice or f"从步骤 {from_step} 继续 Hybrid Pipeline",
        )
    )
    db.commit()
    return {
        "message": f"Hybrid Pipeline 从步骤 {from_step} 重试",
        "task_id": task_id,
        "mode": pipeline_mode,
        "deprecated_notice": f"参数 {requested_mode} 已弃用并映射至 Hybrid Pipeline。" if requested_mode in ("fast", "full") else "",
    }


@router.get("/tasks/{task_id}/pipeline/logs", response_model=list[PipelineLogOut])
def pipeline_logs(task_id: int, db: Session = Depends(get_db)):
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return (
        db.query(PipelineRunLog)
        .filter(PipelineRunLog.task_id == task_id)
        .filter(PipelineRunLog.created_at >= task.created_at)
        .order_by(PipelineRunLog.id)
        .all()
    )


@router.get("/tasks/{task_id}/pipeline/stream")
async def pipeline_stream(task_id: int):
    q = subscribe(task_id)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'task_id': task_id}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    payload = await asyncio.to_thread(q.get, True, 90.0)
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'ping'}, ensure_ascii=False)}\n\n"
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload.get("status") in ("done", "failed") or (
                    payload.get("agent_name") == "Orchestrator"
                    and payload.get("status") in ("done", "failed")
                ):
                    break
        finally:
            unsubscribe(task_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/tasks/{task_id}/diffs", response_model=list[DifferenceOut])
def list_diffs(
    task_id: int,
    risk_level: str | None = None,
    diff_type: str | None = None,
    review_status: str | None = None,
    db: Session = Depends(get_db),
):
    q = db.query(Difference).filter(Difference.task_id == task_id)
    if risk_level:
        q = q.filter(Difference.risk_level == risk_level)
    if diff_type:
        q = q.filter(Difference.diff_type == diff_type)
    if review_status:
        if review_status == "pending":
            q = q.filter(Difference.review_status.in_(("pending", "pending_evidence")))
        else:
            q = q.filter(Difference.review_status == review_status)
    rows = q.order_by(
        Difference.group_clause_id.is_(None),
        Difference.group_clause_id.asc(),
        Difference.id.asc(),
    ).all()
    return rows


def _split_expert_review(ai_reason: str) -> tuple[str, str]:
    prefix = "【国企内控专家复核】"
    text = (ai_reason or "").strip()
    if not text.startswith(prefix):
        return text, ""
    first_line, _, remaining = text.partition("\n")
    expert_note = first_line.removeprefix(prefix).strip()
    return (remaining.strip() or text), expert_note


@router.get("/diffs/{diff_id}", response_model=DifferenceDetailOut)
def get_diff(diff_id: int, db: Session = Depends(get_db)):
    d = db.get(Difference, diff_id)
    if not d:
        raise HTTPException(404, "差异不存在")
    gc = db.get(Clause, d.group_clause_id) if d.group_clause_id else None
    sc = db.get(Clause, d.subsidiary_clause_id) if d.subsidiary_clause_id else None
    task = db.get(ReviewTask, d.task_id)
    # 优先用显式 task_type（PRD 11.5）；旧数据无 task_type 时回退到原启发式。
    single_document_audit = bool(
        task
        and (
            getattr(task, "task_type", "") == "single"
            or task.group_document_id == task.subsidiary_document_id
        )
    )
    base = DifferenceOut.model_validate(d)
    base_data = base.model_dump()
    ai_reason, expert_note = _split_expert_review(d.ai_reason)
    base_data["ai_reason"] = ai_reason
    g_full = normalize_extracted_text(gc.clause_text if gc else d.group_excerpt)
    s_full = normalize_extracted_text(sc.clause_text if sc else d.subsidiary_excerpt)
    table_review_documents: list[dict[str, Any]] = []
    if task:
        group_doc = db.get(Document, task.group_document_id)
        sub_doc = db.get(Document, task.subsidiary_document_id)
        for side, doc in (("集团制度", group_doc), ("子公司制度", sub_doc)):
            if doc and doc.table_review_required:
                table_review_documents.append(
                    {"side": side, "document_id": doc.id, "pages": doc.complex_table_pages}
                )
        # 对照详情直接展示完整原文（前端加滚动条），确保判断理由引用的任何条款都在可见范围内，
        # 不再截成片段。单制度体检左栏是“标准控制点依据”，保持不变；其余一律贴整份原文。
        if not single_document_audit and not gc and group_doc and group_doc.raw_text:
            g_full = normalize_extracted_text(group_doc.raw_text)
        if not sc and sub_doc and sub_doc.raw_text:
            s_full = normalize_extracted_text(sub_doc.raw_text)

    _detail_limit = 40000
    group_text = (g_full or "")[:_detail_limit]
    group_trunc = len(g_full or "") > _detail_limit
    sub_text = (s_full or "")[:_detail_limit]
    sub_trunc = len(s_full or "") > _detail_limit
    return DifferenceDetailOut(
        **base_data,
        group_clause_text=group_text,
        subsidiary_clause_text=sub_text,
        group_clause_truncated=group_trunc,
        subsidiary_clause_truncated=sub_trunc,
        group_external_regulation=getattr(d, "group_external_regulation", "") or "",
        group_external_basis=getattr(d, "group_external_basis", "") or "",
        expert_reviewed=bool(expert_note),
        expert_review_note=expert_note,
        semantic_review=not bool(d.subsidiary_clause_id),
        single_document_audit=single_document_audit,
        table_review_required=bool(table_review_documents),
        table_review_documents=table_review_documents,
    )


@router.post("/diffs/{diff_id}/review", response_model=DifferenceOut)
def review_diff(diff_id: int, body: ReviewRequest, db: Session = Depends(get_db)):
    d = db.get(Difference, diff_id)
    if not d:
        raise HTTPException(404, "差异不存在")
    new_status = "confirmed" if body.action == "confirmed" else "rejected"
    latest = (
        db.query(ReviewLog)
        .filter(ReviewLog.difference_id == d.id)
        .order_by(ReviewLog.id.desc())
        .first()
    )
    if d.review_status == new_status and latest and latest.action == body.action and latest.comment == body.comment:
        return d
    d.review_status = new_status
    log = ReviewLog(
        difference_id=d.id,
        task_id=d.task_id,
        action=body.action,
        comment=body.comment,
        created_at=utc_now(),
    )
    db.add(log)
    db.commit()
    db.refresh(d)
    return d


@router.post("/diffs/{diff_id}/exemptions", response_model=ExemptionOut)
def create_exemption(diff_id: int, body: ExemptionCreate, db: Session = Depends(get_db)):
    d = db.get(Difference, diff_id)
    if not d:
        raise HTTPException(404, "差异不存在")
    active = (
        db.query(ExemptionRule)
        .filter(
            ExemptionRule.difference_id == diff_id,
            ExemptionRule.status.in_(("pending_approval", "active")),
        )
        .first()
    )
    if active:
        raise HTTPException(400, "该差异已存在待审批或已生效的例外")
    fingerprint = normalize_extracted_text(
        f"{d.control_topic} {d.group_excerpt} {d.subsidiary_excerpt}"
    )[:1200]
    row = ExemptionRule(
        difference_id=d.id,
        task_id=d.task_id,
        control_topic=d.control_topic,
        org_scope=body.org_scope,
        semantic_fingerprint=fingerprint,
        justification=body.justification,
        policy_basis=body.policy_basis,
        base_document_id=(db.get(ReviewTask, d.task_id).group_document_id if db.get(ReviewTask, d.task_id) else None),
        base_version=(
            db.get(Document, db.get(ReviewTask, d.task_id).group_document_id).version
            if db.get(ReviewTask, d.task_id) and db.get(Document, db.get(ReviewTask, d.task_id).group_document_id)
            else ""
        ),
        base_control_fingerprint=normalize_extracted_text(f"{d.control_topic} {d.group_excerpt}")[:1200],
        status="pending_approval",
        expires_at=body.expires_at,
    )
    d.review_status = "exemption_pending"
    db.add(row)
    db.add(
        ReviewLog(
            difference_id=d.id,
            task_id=d.task_id,
            action="exemption_requested",
            comment=f"{body.justification}\n依据：{body.policy_basis}".strip(),
            created_at=utc_now(),
        )
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/exemptions", response_model=list[ExemptionOut])
def list_exemptions(db: Session = Depends(get_db)):
    return db.query(ExemptionRule).order_by(ExemptionRule.id.desc()).all()


@router.post("/exemptions/{exemption_id}/approve", response_model=ExemptionOut)
def approve_exemption(exemption_id: int, db: Session = Depends(get_db)):
    row = db.get(ExemptionRule, exemption_id)
    if not row:
        raise HTTPException(404, "例外申请不存在")
    row.status = "active"
    row.approved_by = "审查负责人"
    row.effective_from = utc_now()
    row.updated_at = utc_now()
    diff = db.get(Difference, row.difference_id)
    if diff:
        diff.review_status = "exempted"
    db.commit()
    db.refresh(row)
    return row


@router.post("/exemptions/{exemption_id}/revoke", response_model=ExemptionOut)
def revoke_exemption(exemption_id: int, db: Session = Depends(get_db)):
    row = db.get(ExemptionRule, exemption_id)
    if not row:
        raise HTTPException(404, "例外申请不存在")
    row.status = "revoked"
    row.updated_at = utc_now()
    diff = db.get(Difference, row.difference_id)
    if diff and diff.review_status in ("exempted", "exemption_pending"):
        diff.review_status = "pending"
    db.commit()
    db.refresh(row)
    return row


@router.post("/diffs/{diff_id}/supplements", response_model=SupplementOut)
def create_supplement(diff_id: int, body: SupplementCreate, db: Session = Depends(get_db)):
    d = db.get(Difference, diff_id)
    if not d:
        raise HTTPException(404, "差异不存在")
    open_request = (
        db.query(SupplementRequest)
        .filter(
            SupplementRequest.difference_id == diff_id,
            SupplementRequest.status.in_(("pending", "submitted", "delta_reviewing")),
        )
        .first()
    )
    if open_request:
        raise HTTPException(400, "该差异已有进行中的材料补正任务")
    row = SupplementRequest(
        difference_id=d.id,
        task_id=d.task_id,
        assignee=body.assignee,
        requirement=body.requirement,
        due_at=body.due_at,
        status="pending",
    )
    d.review_status = "need_supplement"
    db.add(row)
    db.add(
        ReviewLog(
            difference_id=d.id,
            task_id=d.task_id,
            action="need_supplement",
            comment=f"经办人：{body.assignee}；材料要求：{body.requirement}",
            created_at=utc_now(),
        )
    )
    db.commit()
    db.refresh(row)
    return row


@router.get("/supplements", response_model=list[SupplementOut])
def list_supplements(db: Session = Depends(get_db)):
    return db.query(SupplementRequest).order_by(SupplementRequest.id.desc()).all()


@router.post("/supplements/{supplement_id}/submit", response_model=SupplementOut)
def submit_supplement(supplement_id: int, body: SupplementSubmit, db: Session = Depends(get_db)):
    row = db.get(SupplementRequest, supplement_id)
    if not row:
        raise HTTPException(404, "材料补正任务不存在")
    if row.status not in ("pending", "rejected"):
        raise HTTPException(400, "当前状态不允许再次提交材料")
    diff = db.get(Difference, row.difference_id)
    if not diff:
        raise HTTPException(404, "关联差异不存在")

    row.submitted_text = normalize_extracted_text(body.submitted_text)[:8000]
    row.submitted_at = utc_now()
    row.status = "delta_reviewing"
    diff.review_status = "delta_reviewing"
    db.flush()

    target = f"{diff.control_topic} {diff.group_excerpt} {diff.summary}"
    score = text_overlap_score(target, row.submitted_text)
    topic_hit = bool(diff.control_topic and diff.control_topic in row.submitted_text)
    covered = topic_hit or score >= 0.12
    pollution_hits = scan_delta_pollution(row.submitted_text)
    derived_ids: list[int] = []
    for hit in pollution_hits:
        derived = Difference(
            task_id=diff.task_id,
            diff_type="待确认",
            risk_level="中",
            control_topic=hit.topic,
            summary=f"补充材料可能引入新风险：{hit.topic}",
            group_excerpt="控制点规则预筛红线",
            subsidiary_excerpt=row.submitted_text[:300],
            group_location="控制点规则引擎",
            subsidiary_location="补充材料",
            ai_reason=hit.reason,
            suggestion=hit.suggestion,
            confidence=0.75,
            evidence_ok=True,
            review_status="pending",
            fallback_reason="delta_pollution_scan",
        )
        db.add(derived)
        db.flush()
        derived_ids.append(derived.id)
    row.pollution_scan_result = (
        f"二次污染审查命中 {len(pollution_hits)} 项红线，已衍生待确认差异。"
        if pollution_hits else "二次污染审查未命中其他控制点红线。"
    )
    row.derived_difference_ids = ",".join(map(str, derived_ids))
    if covered:
        row.status = "accepted"
        row.result = "compliant_by_supplement"
        row.result_reason = (
            f"局部增量审查通过：补充材料对「{diff.control_topic}」形成了可定位的语义覆盖，"
            f"无需重新运行整套制度审查。{row.pollution_scan_result}"
        )
        diff.review_status = "compliant_by_supplement"
    else:
        row.status = "rejected"
        row.result = "still_deficient"
        row.result_reason = (
            f"局部增量审查未通过：补充材料尚不足以证明「{diff.control_topic}」已被实质覆盖。"
            f"{row.pollution_scan_result}"
        )
        diff.review_status = "need_supplement"
    row.closed_at = utc_now()
    db.add(
        ReviewLog(
            difference_id=diff.id,
            task_id=diff.task_id,
            action="delta_audit",
            comment=row.result_reason,
            created_at=utc_now(),
        )
    )
    db.commit()
    db.refresh(row)
    return row


@router.delete("/reviews/{log_id}")
def undo_review(log_id: int, db: Session = Depends(get_db)):
    log = db.get(ReviewLog, log_id)
    if not log:
        raise HTTPException(404, "记录不存在")
    diff_id = log.difference_id
    removed = (
        db.query(ReviewLog)
        .filter(ReviewLog.difference_id == diff_id)
        .delete(synchronize_session=False)
    )
    diff = db.get(Difference, diff_id)
    if diff:
        diff.review_status = "pending"
    db.commit()
    return {"ok": True, "difference_id": diff_id, "removed_count": removed}


@router.get("/reviews", response_model=list[ReviewLogOut])
def list_reviews(task_id: int | None = None, db: Session = Depends(get_db)):
    q = db.query(ReviewLog).order_by(ReviewLog.id.desc())
    if task_id:
        q = q.filter(ReviewLog.task_id == task_id)
    logs = q.limit(200).all()
    seen_diff: set[int] = set()
    result = []
    for log in logs:
        if log.difference_id in seen_diff:
            continue
        seen_diff.add(log.difference_id)
        d = db.get(Difference, log.difference_id)
        result.append(
            ReviewLogOut(
                id=log.id,
                difference_id=log.difference_id,
                task_id=log.task_id,
                action=log.action,
                comment=log.comment,
                reviewer=log.reviewer,
                created_at=log.created_at,
                diff_summary=d.summary if d else "",
                risk_level=d.risk_level if d else "",
                diff_type=d.diff_type if d else "",
            )
        )
        if len(result) >= 100:
            break
    return result


@router.get("/tasks/{task_id}/export")
def export_task(task_id: int, format: str = Query("xlsx", pattern="^(xlsx|docx|html)$"), db: Session = Depends(get_db)):
    task = db.get(ReviewTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if format == "xlsx":
        data = export_task_xlsx(db, task)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="task_{task_id}.xlsx"'},
        )
    if format == "docx":
        data = export_task_docx(db, task)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="task_{task_id}.docx"'},
        )
    html = export_task_html(db, task)
    return HTMLResponse(content=html)


@router.get("/policy-templates")
def list_policy_templates(domain: str | None = Query(None)):
    """脱敏制度范本列表（供单制度体检选择参考范本）。"""
    items = list_templates()
    if domain:
        items = [t for t in items if t["standard_domain"] == domain or t["domain"] == domain]
    return items


@router.get("/policy-templates/{policy_id}")
def get_policy_template(policy_id: str):
    """范本详情：标准控制点与正文摘录。"""
    tpl = get_template(policy_id)
    if not tpl:
        raise HTTPException(404, "范本不存在")
    return tpl
