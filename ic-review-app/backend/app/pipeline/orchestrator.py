import json
import hashlib
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AnalysisCache, Clause, ControlPoint, Difference, DiffClauseMapping, Document,
    PipelineRunLog, ReviewTask, TaskCheckpoint,
)
from app.pipeline.agents import STEPS, Agents
from app.services.clause_excerpt import pick_clause_excerpt
from app.services.clause_splitter import split_clauses_local
from app.services.control_heuristic import extract_control_points_local
from app.services.dependency_scope import cache_dependency_scope, global_context_hash
from app.services.evidence_verify import verify_diff_drafts
from app.services.llm import LLMClient
from app.services.standard_control_library import infer_standard_domains, load_standard_controls
from app.services.text_normalize import cjk_ratio


EventCallback = Callable[[int, str, str, str, str, float], None]
logger = logging.getLogger(__name__)


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    logger.debug("%s %s %s %s %s", run_id, hypothesis_id, location, message, data)


def _build_missing_summary(group_clause: Clause | None, topic: str) -> tuple[str, str, str]:
    """返回 (summary, ai_reason, suggestion)，按控制点语义覆盖描述缺口。"""
    clause_no = group_clause.clause_no if group_clause else ""
    chapter = group_clause.chapter_title if group_clause else ""
    location_parts = [p for p in (chapter, clause_no) if p]
    location_str = " ".join(location_parts) if location_parts else ""

    is_vague = not topic or topic in ("制度控制要求", "一般控制")
    if topic and not is_vague:
        summary = f"子公司制度对「{topic}」的控制覆盖不足或待确认"
    else:
        summary = "子公司制度存在控制覆盖不足或待确认事项"

    evidence_label = f"集团依据位置：{location_str}。" if location_str else ""
    if location_str and topic and not is_vague:
        ai_reason = (
            f"{evidence_label}系统按「{topic}」控制点语义在子公司全文中检索，"
            "未发现足以证明已覆盖的责任主体、控制动作、触发条件、审批/监督或留痕要求。"
            "该判断不是条款编号逐条对应，需结合子公司业务适用性及其他配套制度复核。"
        )
    elif location_str:
        ai_reason = (
            f"{evidence_label}系统未在子公司全文中发现足以证明该集团要求已被实质覆盖的制度表达。"
            "该判断不是条款编号逐条对应，需结合业务适用性及其他配套制度复核。"
        )
    else:
        ai_reason = (
            "系统未在子公司全文中发现足以证明该集团控制要求已被实质覆盖的制度表达。"
            "该判断基于控制点语义覆盖，需结合业务适用性及其他配套制度复核。"
        )

    suggestion = (
        "建议先确认该控制点是否适用于本子公司，以及是否已由其他专项制度覆盖；"
        "如适用且未覆盖，应补充责任主体、控制动作、触发条件、记录留痕和问责要求。"
    )
    if location_str:
        suggestion += f" 集团制度可作为依据参考：{location_str}。"
    return summary, ai_reason, suggestion


def _cp_entry(row: ControlPoint, clause: dict) -> dict:
    return {
        "id": row.id,
        "clause_id": row.clause_id,
        "control_topic": row.control_topic,
        "subject_role": row.subject_role,
        "action": row.action,
        "threshold": row.threshold,
        "requirement": row.requirement,
        "clause_text": (clause.get("clause_text") or row.requirement or "")[:800],
        "location_label": clause.get("location_label") or "",
        "clause_no": clause.get("clause_no") or "",
    }


class PipelineOrchestrator:
    def __init__(
        self,
        db: Session,
        llm: Any | None = None,
        expert_llm: Any | None = None,
        mode: str | None = None,
    ):
        self.db = db
        if llm is not None:
            core_client = llm
            expert_client = expert_llm if expert_llm is not None else llm
        else:
            settings = get_settings()
            core_client = LLMClient(
                api_key=settings.core_analyser_api_key or settings.llm_api_key,
                base_url=settings.core_analyser_base_url or settings.llm_base_url,
                model=settings.resolved_core_model,
                fallback_model=settings.core_analyser_fallback_model or settings.llm_fallback_model,
            )
            expert_client = LLMClient(
                api_key=settings.soe_expert_api_key or settings.llm_api_key,
                base_url=settings.soe_expert_base_url or settings.llm_base_url,
                model=settings.resolved_expert_model,
                fallback_model=settings.soe_expert_fallback_model or settings.llm_fallback_model,
            )
        self.agents = Agents(core_client, expert_client)
        self.mode = "hybrid"
        self._on_event: EventCallback | None = None

    def set_event_callback(self, cb: EventCallback) -> None:
        self._on_event = cb

    def _emit(self, task_id: int, step: int, agent: str, status: str, message: str) -> None:
        if self._on_event:
            progress = step / 6.0
            self._on_event(task_id, step, agent, status, message, progress)

    def _warn_empty(self, task: ReviewTask, step: int, agent: str, message: str, detail: dict[str, Any]) -> None:
        warn = f"[空结果告警] {message}"
        task.pipeline_error = warn
        self.db.commit()
        self._emit(task.id, step, agent, "warning", warn)
        _debug_log(
            "pre-fix",
            "H18",
            "orchestrator.py:_warn_empty",
            "empty result warning emitted",
            {"task_id": task.id, "step": step, "agent": agent, "message": message, **detail},
        )

    def _log_step(
        self,
        task: ReviewTask,
        step: int,
        agent: str,
        status: str,
        message: str,
        output: dict | None = None,
        duration_ms: int = 0,
    ) -> None:
        log = PipelineRunLog(
            task_id=task.id,
            step=step,
            agent_name=agent,
            status=status,
            message=message,
            output_json=json.dumps(output, ensure_ascii=False) if output else None,
            duration_ms=duration_ms,
        )
        self.db.add(log)
        payload = json.dumps(output or {"message": message}, ensure_ascii=False, sort_keys=True)
        checkpoint = TaskCheckpoint(
            task_id=task.id,
            node_key=f"step-{step}-{agent}",
            input_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            status=status,
            output_json=payload,
            prompt_version="Hybrid_V1.0",
            model_version=get_settings().llm_model,
        )
        self.db.add(checkpoint)
        self.db.commit()

    def _sync_diff_clause_mappings(self, task_id: int) -> None:
        diff_ids = [r[0] for r in self.db.query(Difference.id).filter(Difference.task_id == task_id).all()]
        if diff_ids:
            self.db.query(DiffClauseMapping).filter(
                DiffClauseMapping.difference_id.in_(diff_ids)
            ).delete(synchronize_session=False)
        for diff in self.db.query(Difference).filter(Difference.task_id == task_id).all():
            if diff.group_clause_id:
                self.db.add(DiffClauseMapping(difference_id=diff.id, source_type="group", clause_id=diff.group_clause_id))
            if diff.subsidiary_clause_id:
                self.db.add(DiffClauseMapping(difference_id=diff.id, source_type="subsidiary", clause_id=diff.subsidiary_clause_id))
        self.db.commit()

    def _log_diff_excerpt_quality(self, task_id: int, stage: str) -> None:
        rows = (
            self.db.query(Difference.id, Difference.group_excerpt, Difference.subsidiary_excerpt)
            .filter(Difference.task_id == task_id)
            .order_by(Difference.id.asc())
            .limit(3)
            .all()
        )
        _debug_log(
            "pre-fix",
            "H43",
            "orchestrator.py:_log_diff_excerpt_quality",
            "diff excerpt quality sample",
            {
                "task_id": task_id,
                "stage": stage,
                "total_diffs": self.db.query(Difference).filter(Difference.task_id == task_id).count(),
                "sample": [
                    {
                        "id": rid,
                        "group_len": len(g or ""),
                        "group_cjk_ratio": round(cjk_ratio(g or ""), 4),
                        "sub_len": len(s or ""),
                        "sub_cjk_ratio": round(cjk_ratio(s or ""), 4),
                    }
                    for rid, g, s in rows
                ],
            },
        )

    def run(self, task_id: int, from_step: int = 1) -> None:
        task = self.db.get(ReviewTask, task_id)
        if not task:
            raise ValueError("任务不存在")

        group_doc = self.db.get(Document, task.group_document_id)
        sub_doc = self.db.get(Document, task.subsidiary_document_id)
        if not group_doc or not sub_doc:
            raise ValueError("关联制度不存在")

        task.status = "running"
        task.pipeline_error = None
        settings = get_settings()
        task.core_model_version = settings.resolved_core_model
        task.expert_model_version = settings.resolved_expert_model
        self.db.commit()

        ctx: dict = {
            "group_clauses": [],
            "sub_clauses": [],
            "group_cps": [],
            "sub_cps": [],
            "pairs": [],
            "diffs_draft": [],
        }

        try:
            self._run_hybrid_pipeline(task, group_doc, sub_doc, ctx, from_step)

            # region agent log
            _debug_log(
                "pre-fix",
                "H26",
                "orchestrator.py:run",
                "final status update start",
                {"task_id": task.id, "mode": self.mode, "current_step_before_finalize": task.current_step},
            )
            # endregion
            task.status = "reviewing"
            task.current_step = 6
            task.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            self._sync_diff_clause_mappings(task.id)
            # region agent log
            _debug_log(
                "pre-fix",
                "H26",
                "orchestrator.py:run",
                "final status update end",
                {"task_id": task.id, "status": task.status, "current_step": task.current_step},
            )
            # endregion
            self._emit(task.id, 6, "ReportBuilder", "completed", "流水线完成，进入待复核")
        except Exception as e:
            # region agent log
            _debug_log(
                "pre-fix",
                "H26",
                "orchestrator.py:run",
                "run exception caught",
                {"task_id": task.id, "error": str(e), "step": task.current_step},
            )
            # endregion
            task.status = "failed"
            task.pipeline_error = str(e)
            try:
                self.db.commit()
                # region agent log
                _debug_log(
                    "pre-fix",
                    "H26",
                    "orchestrator.py:run",
                    "failed status persisted",
                    {"task_id": task.id, "status": task.status, "step": task.current_step},
                )
                # endregion
            except Exception as commit_err:
                # region agent log
                _debug_log(
                    "pre-fix",
                    "H26",
                    "orchestrator.py:run",
                    "failed status persist error",
                    {"task_id": task.id, "error": str(commit_err)},
                )
                # endregion
            self._emit(task.id, task.current_step or 1, "Orchestrator", "failed", str(e))
            raise

    def _run_hybrid_pipeline(
        self, task: ReviewTask, group_doc: Document, sub_doc: Document, ctx: dict, from_step: int
    ) -> None:
        if from_step <= 1:
            self._step_parse_local(task, group_doc, sub_doc, ctx)
        if from_step <= 2:
            self._step_standard_controls(task, group_doc, sub_doc, ctx)
            self._step_control_points_local(task, ctx)
        if from_step <= 4:
            self._step_diff_combined(task, ctx)
            self._step_expert_review(task, ctx)
        if from_step <= 5:
            self._step_evidence_local(task, ctx)
        if from_step <= 6:
            self._step_report_local(task, ctx)

    def _persist_clauses(self, doc: Document, items: list[dict], ctx_key: str, ctx: dict) -> None:
        clauses_data = []
        self.db.query(Clause).filter(Clause.document_id == doc.id).delete()
        for item in items:
            c = Clause(
                document_id=doc.id,
                chapter_title=item.get("chapter_title", ""),
                clause_no=item.get("clause_no", ""),
                clause_text=item["clause_text"],
                page_no=item.get("page_no"),
                location_label=item.get("location_label", ""),
            )
            self.db.add(c)
            self.db.flush()
            clauses_data.append({
                "id": c.id,
                "chapter_title": c.chapter_title,
                "clause_no": c.clause_no,
                "clause_text": c.clause_text,
                "location_label": c.location_label,
            })
        ctx[ctx_key] = clauses_data
        doc.parse_status = "parsed"

    def _step_parse_local(self, task: ReviewTask, group_doc: Document, sub_doc: Document, ctx: dict) -> None:
        step, agent, title, _ = STEPS[0]
        agent = "StructureEngine"
        task.current_step = step
        self.db.commit()
        self._emit(task.id, step, "StructureEngine", "running", f"{title}（确定性结构化解析，无需 LLM）")
        t0 = time.time()
        for doc, key in [(group_doc, "group_clauses"), (sub_doc, "sub_clauses")]:
            if not doc.raw_text:
                raise ValueError(f"文档 {doc.document_name} 无文本")
            label = "集团制度" if key == "group_clauses" else "子公司制度"
            items = split_clauses_local(doc.raw_text)
            # region agent log
            _debug_log(
                "pre-fix",
                "H2",
                "orchestrator.py:_step_parse_local",
                "local parse clauses",
                {"task_id": task.id, "side": key, "raw_len": len(doc.raw_text or ""), "clauses": len(items)},
            )
            # endregion
            self._emit(task.id, step, agent, "running", f"{label} 本地拆条完成，{len(items)} 条")
            self._persist_clauses(doc, items, key, ctx)
        if not ctx.get("group_clauses") or not ctx.get("sub_clauses"):
            self._warn_empty(
                task,
                step,
                agent,
                "文件解析后条款为空，请检查上传文件是否可提取文本（扫描件需 OCR）。",
                {"group_clauses": len(ctx.get("group_clauses", [])), "sub_clauses": len(ctx.get("sub_clauses", []))},
            )
        self.db.commit()
        ms = int((time.time() - t0) * 1000)
        self._log_step(task, step, "StructureEngine", "completed", "结构化解析完成", {"mode": "hybrid"}, ms)
        self._emit(task.id, step, agent, "completed", "文件解析完成（本地）")

    def _step_standard_controls(
        self,
        task: ReviewTask,
        group_doc: Document,
        sub_doc: Document,
        ctx: dict,
    ) -> None:
        """准备标准控制点上下文；不得为此额外调用认知模型。"""
        if ctx.get("standard_cps") is not None:
            return
        step, agent, title, _ = STEPS[1]
        self._emit(task.id, step, "ControlRuleEngine", "running", "正在加载标准控制点与确定性规则…")
        t0 = time.time()
        # 集团制度仍是对子公司审查的直接基准；数据库标准库用于控制主题归一与规则上下文补充。
        domain_text = " ".join(
            [
                task.business_domain or "",
                group_doc.business_domain or "",
                sub_doc.business_domain or "",
                group_doc.document_name or "",
                sub_doc.document_name or "",
            ]
        )
        ctx["standard_cps"] = load_standard_controls(
            self.db,
            infer_standard_domains(domain_text, preferred_domain=task.business_domain),
            include_general=False,
            context_text=f"{group_doc.document_name or ''} {sub_doc.document_name or ''}",
        )
        ctx["standard_domain"] = task.business_domain or ""
        self._emit(task.id, step, "ControlRuleEngine", "running", "标准控制点与确定性规则加载完成")
        ms = int((time.time() - t0) * 1000)
        self._log_step(
            task,
            step,
            "ControlRuleEngine",
            "completed",
            f"规则上下文已加载：{ctx.get('standard_domain', '') or '通用'}",
            {"standard_control_count": len(ctx.get("standard_cps", [])), "source": "configured_library"},
            ms,
        )

    def _step_control_points_local(self, task: ReviewTask, ctx: dict) -> None:
        step, agent, title, _ = STEPS[1]
        agent = "ControlRuleEngine"
        task.current_step = step
        self.db.commit()
        self._emit(task.id, step, "ControlRuleEngine", "running", f"{title}（确定性规则抽取）")
        t0 = time.time()
        standard_cps = ctx.get("standard_cps")
        for key, doc_id in [("group_cps", task.group_document_id), ("sub_cps", task.subsidiary_document_id)]:
            clauses = ctx["group_clauses"] if key == "group_cps" else ctx["sub_clauses"]
            cps_raw = extract_control_points_local(clauses, standard_cps=standard_cps)
            self.db.query(ControlPoint).filter(ControlPoint.document_id == doc_id).delete()
            cps = []
            for cp in cps_raw:
                idx = cp["clause_index"]
                if idx < 0 or idx >= len(clauses):
                    continue
                row = ControlPoint(
                    clause_id=clauses[idx]["id"],
                    document_id=doc_id,
                    business_domain=task.business_domain,
                    control_topic=cp["control_topic"],
                    subject_role=cp["subject_role"],
                    action=cp["action"],
                    object=cp["object"],
                    threshold=cp["threshold"],
                    requirement=cp["requirement"],
                )
                self.db.add(row)
                self.db.flush()
                cps.append(_cp_entry(row, clauses[idx]))
            ctx[key] = cps
            # region agent log
            _debug_log(
                "pre-fix",
                "H2",
                "orchestrator.py:_step_control_points_local",
                "local control points extracted",
                {"task_id": task.id, "side": key, "clause_count": len(clauses), "cp_count": len(cps)},
            )
            # endregion
        if not ctx.get("group_cps") or not ctx.get("sub_cps"):
            self._warn_empty(
                task,
                step,
                agent,
                "控制点抽取为空，请检查制度正文结构与章节完整性。",
                {"group_cps": len(ctx.get("group_cps", [])), "sub_cps": len(ctx.get("sub_cps", []))},
            )
        self.db.commit()
        ms = int((time.time() - t0) * 1000)
        self._log_step(task, step, agent, "completed", "控制点抽取完成（本地）", {}, ms)
        self._emit(task.id, step, agent, "completed", "控制点抽取完成")

    def _step_diff_combined(self, task: ReviewTask, ctx: dict) -> None:
        step, agent, title, _ = STEPS[3]
        agent = "CoreAnalyser"
        task.current_step = step
        self.db.commit()
        self._emit(task.id, step, agent, "running", "全文语义差异判断（结合候选控制点与制度全文）")
        t0 = time.time()
        timeout_sec = 75
        timed_out = False
        settings = get_settings()
        global_hash = global_context_hash(ctx["group_clauses"], ctx["sub_clauses"])
        dependency_scope = cache_dependency_scope(ctx["group_clauses"], ctx["sub_clauses"])
        cache_payload = json.dumps(
            {
                "group_clauses": ctx["group_clauses"],
                "sub_clauses": ctx["sub_clauses"],
                "group_cps": ctx["group_cps"],
                "sub_cps": ctx["sub_cps"],
                "prompt": "CoreAnalyser_V1.0",
                "model": settings.resolved_core_model,
                "global_context_hash": global_hash,
                "dependency_scope": dependency_scope,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        cache_key = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()
        cached = self.db.query(AnalysisCache).filter(AnalysisCache.cache_key == cache_key).first()
        if cached:
            from app.pipeline.agent_schemas import CoreAnalyserOutput

            cached_data = json.loads(cached.result_json)
            out = CoreAnalyserOutput.model_validate({"differences": cached_data["differences"]})
            pairs = [tuple(pair) for pair in cached_data["pairs"]]
            self._emit(task.id, step, "CoreAnalyser", "running", "命中章节 Hash 缓存，复用未变化内容的分析结果")
        else:
            ex = ThreadPoolExecutor(max_workers=1)
            fut = ex.submit(
                self.agents.analyze_diffs_map_reduce,
                ctx["group_clauses"],
                ctx["sub_clauses"],
                ctx["group_cps"],
                ctx["sub_cps"],
                max_workers=settings.hybrid_map_workers,
            )
            try:
                out, pairs = fut.result(timeout=timeout_sec)
                self.db.add(
                    AnalysisCache(
                        cache_key=cache_key,
                        chapter_hash=cache_key,
                        global_context_hash=global_hash,
                        dependency_scope=dependency_scope,
                        prompt_version="CoreAnalyser_V1.0",
                        model_version=settings.resolved_core_model,
                        result_json=json.dumps(
                            {"differences": [d.model_dump() for d in out.differences], "pairs": pairs},
                            ensure_ascii=False,
                        ),
                    )
                )
                self.db.commit()
            except FuturesTimeoutError:
                timed_out = True
                fut.cancel()
                from app.pipeline.agent_schemas import CoreAnalyserOutput

                out, pairs = CoreAnalyserOutput(differences=[]), []
                _debug_log(
                    "pre-fix", "H45", "orchestrator.py:_step_diff_combined",
                    "combined llm timed out, force fallback",
                    {"task_id": task.id, "timeout_sec": timeout_sec},
                )
            finally:
                ex.shutdown(wait=False, cancel_futures=True)
        # region agent log
        _debug_log(
            "pre-fix",
            "H3",
            "orchestrator.py:_step_diff_combined",
            "combined diff inputs/outputs",
            {
                "task_id": task.id,
                "group_cps": len(ctx["group_cps"]),
                "sub_cps": len(ctx["sub_cps"]),
                "pair_candidates": len(pairs),
                "diffs_returned": len(out.differences),
                "timed_out": timed_out,
            },
        )
        # endregion
        # region agent log
        _debug_log(
            "pre-fix",
            "H48",
            "orchestrator.py:_step_diff_combined",
            "begin write phase after llm",
            {"task_id": task.id, "timed_out": timed_out},
        )
        # endregion
        # 仅在 LLM 返回后再写库，避免长调用期间持有 SQLite 写锁。
        self.db.query(Difference).filter(Difference.task_id == task.id).delete()
        if len(ctx.get("group_cps", [])) > 0 and len(ctx.get("sub_cps", [])) > 0 and len(out.differences) == 0:
            self._warn_empty(
                task,
                step,
                "CoreAnalyser",
                "Core Analyser 返回 0 条，请人工复核控制点质量。",
                {
                    "group_cps": len(ctx.get("group_cps", [])),
                    "sub_cps": len(ctx.get("sub_cps", [])),
                    "pair_candidates": len(pairs),
                    "diffs_returned": len(out.differences),
                },
            )

        clause_cache: dict[int, Clause] = {}

        def get_clause(cid: int) -> Clause | None:
            if cid not in clause_cache:
                clause_cache[cid] = self.db.get(Clause, cid)
            return clause_cache[cid]

        for d in out.differences:
            pi = d.pair_index
            if pi < 0 or pi >= len(pairs):
                continue
            gi, si = pairs[pi]
            gc = ctx["group_cps"][gi]
            g_clause = get_clause(gc["clause_id"])
            g_excerpt = g_clause.clause_text[:500] if g_clause else ""

            if si is None:
                pair = {"group_clause_id": gc["clause_id"], "subsidiary_clause_id": None}
                diff_type = d.diff_type if d.diff_type else "缺失"
                risk_level = d.risk_level if d.risk_level else "高"
                draft = {
                    "pair": pair,
                    "diff_type": diff_type,
                    "group_excerpt": g_excerpt,
                    "subsidiary_excerpt": "",
                    "group_location": g_clause.location_label if g_clause else "",
                    "subsidiary_location": "",
                }
                ev = verify_diff_drafts([draft], ctx["group_clauses"], ctx["sub_clauses"])[0]
                # 若 LLM 返回的 summary 过于笼统，用更具体的描述替换
                summary = d.summary
                ai_reason = d.ai_reason
                suggestion = d.suggestion
                generated_summary, generated_reason, generated_suggestion = _build_missing_summary(
                    g_clause, gc.get("control_topic", "")
                )
                if not summary or len(summary) < 10 or "一般控制" in summary or "制度控制要求" in summary or "对应" in summary:
                    summary = generated_summary
                if (
                    not ai_reason
                    or "匹配阶段" in ai_reason
                    or "对应控制点" in ai_reason
                    or "对应的控制点" in ai_reason
                    or "对应条款" in ai_reason
                ):
                    ai_reason = generated_reason
                if not suggestion or "对应" in suggestion or "先核查该控制点" in suggestion:
                    suggestion = generated_suggestion
                self.db.add(
                    Difference(
                        task_id=task.id,
                        diff_type=diff_type,
                        risk_level=risk_level,
                        control_topic=gc.get("control_topic", ""),
                        summary=summary,
                        group_clause_id=gc["clause_id"],
                        subsidiary_clause_id=None,
                        group_excerpt=g_excerpt,
                        subsidiary_excerpt="",
                        group_location=ev["group_location"] or (g_clause.location_label if g_clause else ""),
                        subsidiary_location="",
                        ai_reason=ai_reason,
                        suggestion=suggestion,
                        confidence=d.confidence,
                        evidence_ok=ev["evidence_ok"],
                        review_status="pending" if ev["evidence_ok"] else "pending_evidence",
                    )
                )
                continue

            sc = ctx["sub_cps"][si]
            g_clause = get_clause(gc["clause_id"])
            s_clause = get_clause(sc["clause_id"])
            g_excerpt = g_clause.clause_text[:500] if g_clause else ""
            s_excerpt = s_clause.clause_text[:500] if s_clause else ""
            if s_clause and len(s_clause.clause_text) > 500:
                s_excerpt, _ = pick_clause_excerpt(
                    s_clause.clause_text,
                    hint=d.summary,
                    topic=gc.get("control_topic", ""),
                )
            pair = {
                "group_clause_id": gc["clause_id"],
                "subsidiary_clause_id": sc["clause_id"],
            }
            draft = {
                "pair": pair,
                "diff_type": d.diff_type,
                "group_excerpt": g_excerpt,
                "subsidiary_excerpt": s_excerpt,
                "group_location": g_clause.location_label if g_clause else "",
                "subsidiary_location": s_clause.location_label if s_clause else "",
            }
            ev = verify_diff_drafts([draft], ctx["group_clauses"], ctx["sub_clauses"])[0]
            self.db.add(
                Difference(
                    task_id=task.id,
                    diff_type=d.diff_type,
                    risk_level=d.risk_level,
                    control_topic=gc.get("control_topic", ""),
                    summary=d.summary,
                    group_clause_id=gc["clause_id"],
                    subsidiary_clause_id=sc["clause_id"],
                    group_excerpt=g_excerpt,
                    subsidiary_excerpt=s_excerpt,
                    group_location=ev["group_location"] or (g_clause.location_label if g_clause else ""),
                    subsidiary_location=ev["subsidiary_location"] or (s_clause.location_label if s_clause else ""),
                    ai_reason=d.ai_reason,
                    suggestion=d.suggestion,
                    confidence=d.confidence,
                    evidence_ok=ev["evidence_ok"],
                    review_status="pending" if ev["evidence_ok"] else "pending_evidence",
                )
            )
        self.db.commit()
        self._log_diff_excerpt_quality(task.id, "fast_step_diff_combined")
        diffs_now = self.db.query(Difference).filter(Difference.task_id == task.id).count()
        should_fallback = (
            len(ctx.get("group_cps", [])) > 0
            and len(ctx.get("sub_cps", [])) > 0
            and diffs_now == 0
        )
        if should_fallback:
            # region agent log
            _debug_log(
                "pre-fix",
                "H51",
                "orchestrator.py:_step_diff_combined",
                "skip fast completed log because fallback required",
                {
                    "task_id": task.id,
                    "timed_out": timed_out,
                    "group_cps": len(ctx.get("group_cps", [])),
                    "sub_cps": len(ctx.get("sub_cps", [])),
                    "diffs_now": diffs_now,
                },
            )
            # endregion
            self._emit(task.id, 4, "CoreAnalyser", "warning", "未识别到差异，已保留过程证据供人工复核")
        ms = int((time.time() - t0) * 1000)
        self._log_step(
            task,
            step,
            "CoreAnalyser",
            "completed",
            f"识别 {len(out.differences)} 条差异",
            {"cache_key": cache_key, "global_context_hash": global_hash, "dependency_scope": dependency_scope},
            ms,
        )
        self._emit(task.id, 4, "CoreAnalyser", "completed", f"章节并行分析完成，{len(out.differences)} 条")
        task.current_step = 4
        self.db.commit()
        self._log_diff_excerpt_quality(task.id, "full_internal_persist")

    def _step_expert_review(self, task: ReviewTask, ctx: dict) -> None:
        diffs = (
            self.db.query(Difference)
            .filter(Difference.task_id == task.id)
            .order_by(Difference.id)
            .all()
        )
        if not diffs:
            return

        # 置信度/风险门控：只把不确定或高风险的差异升级给强模型仲裁；高置信低风险的直接采纳 Core 初判。
        # 这样强模型只跑刀刃上的少数项，既省成本又聚焦；高风险/关键差异一个不漏。
        settings = get_settings()
        conf_threshold = settings.expert_review_confidence_threshold
        high_stakes_types = {"缺失", "越权", "冲突"}
        to_expert = [
            d
            for d in diffs
            if (d.confidence is None or d.confidence < conf_threshold)
            or d.risk_level == "高"
            or d.diff_type in high_stakes_types
        ]
        accepted = len(diffs) - len(to_expert)
        if not to_expert:
            self._log_step(
                task,
                4,
                "SOEExpertAgent",
                "completed",
                f"全部 {len(diffs)} 条为高置信低风险结论，采纳 Core Analyser 初判，未触发专家仲裁。",
                {"escalated": 0, "accepted": accepted},
                0,
            )
            self._emit(
                task.id, 4, "SOEExpertAgent", "completed",
                f"采纳 Core 初判 {accepted} 条，无需专家仲裁",
            )
            return

        self._emit(
            task.id, 4, "SOEExpertAgent", "running",
            f"国企内控专家正在仲裁 {len(to_expert)} 条高风险/低置信结论（采纳 Core 初判 {accepted} 条）…",
        )
        payload = [
            {
                "diff_index": i,
                "diff_type": d.diff_type,
                "risk_level": d.risk_level,
                "control_topic": d.control_topic,
                "summary": d.summary,
                "ai_reason": d.ai_reason,
                "suggestion": d.suggestion,
                "confidence": d.confidence,
                "group_location": d.group_location,
                "subsidiary_location": d.subsidiary_location,
                "group_excerpt": d.group_excerpt,
                "subsidiary_excerpt": d.subsidiary_excerpt,
            }
            for i, d in enumerate(to_expert)
        ]

        t0 = time.time()
        try:
            out = self.agents.review_diffs_by_expert(
                payload,
            )
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            self._log_step(
                task,
                4,
                "SOEExpertAgent",
                "warning",
                f"专家仲裁失败，保留 Core Analyser 原结果：{e}",
                {},
                ms,
            )
            self._emit(task.id, 4, "SOEExpertAgent", "warning", "专家仲裁失败，已保留 Core Analyser 原结果")
            return

        by_index = {item.diff_index: item for item in out.items}
        removed = 0
        updated = 0
        for i, diff in enumerate(to_expert):
            item = by_index.get(i)
            if item is None:
                continue
            if not item.keep:
                self.db.delete(diff)
                removed += 1
                continue
            if item.diff_type:
                diff.diff_type = item.diff_type
            if item.risk_level:
                diff.risk_level = item.risk_level
            if item.summary:
                diff.summary = item.summary
            if item.ai_reason:
                diff.ai_reason = item.ai_reason
            if item.suggestion:
                diff.suggestion = item.suggestion
            if item.confidence is not None:
                diff.confidence = item.confidence
            expert_note = (
                item.audit_comment
                or out.review_summary
                or "已结合集团制度、子公司制度全文和国企内控管控逻辑进行二次复核。"
            )
            prefix = f"【国企内控专家复核】{expert_note}"
            if not diff.ai_reason.startswith("【国企内控专家复核】"):
                diff.ai_reason = f"{prefix}\n{diff.ai_reason}".strip()
            updated += 1

        self.db.commit()
        ms = int((time.time() - t0) * 1000)
        self._log_step(
            task,
            4,
            "SOEExpertAgent",
            "completed",
            f"专家复核完成：升级 {len(to_expert)} 条、采纳 Core {accepted} 条；修正 {updated} 条，剔除 {removed} 条",
            {"review_summary": out.review_summary, "escalated": len(to_expert), "accepted": accepted, "updated": updated, "removed": removed},
            ms,
        )
        self._emit(task.id, 4, "SOEExpertAgent", "completed", f"专家复核完成，剔除 {removed} 条低质量结论")

    def _step_evidence_local(self, task: ReviewTask, ctx: dict) -> None:
        step, agent, title, _ = STEPS[4]
        agent = "EvidenceRules"
        task.current_step = step
        self.db.commit()
        self._emit(task.id, step, agent, "running", f"{title}（确定性规则校验）")
        diffs = self.db.query(Difference).filter(Difference.task_id == task.id).all()
        for d in diffs:
            draft = {
                "pair": {
                    "group_clause_id": d.group_clause_id,
                    "subsidiary_clause_id": d.subsidiary_clause_id,
                },
                "diff_type": d.diff_type,
                "group_excerpt": d.group_excerpt,
                "subsidiary_excerpt": d.subsidiary_excerpt,
                "group_location": d.group_location,
                "subsidiary_location": d.subsidiary_location,
            }
            ev = verify_diff_drafts([draft], ctx["group_clauses"], ctx["sub_clauses"])[0]
            d.evidence_ok = ev["evidence_ok"]
            if ev["group_location"]:
                d.group_location = ev["group_location"]
            if ev["subsidiary_location"]:
                d.subsidiary_location = ev["subsidiary_location"]
            d.review_status = "pending" if d.evidence_ok else "pending_evidence"
        self.db.commit()
        self._emit(task.id, step, agent, "completed", "证据校验完成（规则引擎）")
        self._log_step(task, step, agent, "completed", "确定性证据校验", {"count": len(diffs)}, 0)

    def _step_report_local(self, task: ReviewTask, ctx: dict) -> None:
        step, agent, title, _ = STEPS[5]
        agent = "ReportBuilder"
        task.current_step = step
        self.db.commit()
        diffs = self.db.query(Difference).filter(Difference.task_id == task.id).all()
        high = sum(1 for d in diffs if d.risk_level == "高")
        process_proof = (
            f"【过程证明】条款（集团/子公司）：{len(ctx.get('group_clauses', []))}/{len(ctx.get('sub_clauses', []))}；"
            f"控制点：{len(ctx.get('group_cps', []))}/{len(ctx.get('sub_cps', []))}。"
        )
        task.report_summary = (
            f"【Hybrid Pipeline】共识别 {len(diffs)} 条差异，其中高风险 {high} 条。"
            f" {process_proof}"
            " 解析、控制点预筛、证据校验和报告统计由确定性代码执行。"
        )
        self.db.commit()
        self._emit(task.id, step, agent, "completed", "报告摘要已生成")
        self._log_step(task, step, agent, "completed", task.report_summary or "", {}, 0)
