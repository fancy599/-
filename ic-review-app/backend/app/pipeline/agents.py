import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app.pipeline.agent_schemas import (
    CoreAnalyserOutput,
    ExpertReviewOutput,
)
from app.pipeline.prompts import (
    CORE_ANALYSER_SYSTEM,
    SOE_EXPERT_REVIEW_SYSTEM,
)
from app.services.llm import LLMClient
from app.services.match_prefilter import (
    attach_clause_to_cps,
    build_match_views,
    cp_for_llm,
    prefilter_match_candidates,
    remap_match_pair_indices,
)

logger = logging.getLogger(__name__)


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    logger.debug("%s %s %s %s %s", run_id, hypothesis_id, location, message, data)

STEPS = [
    (1, "StructureEngine", "文件解析", "章节条款定位"),
    (2, "ControlRuleEngine", "控制点抽取", "角色、动作、阈值"),
    (3, "CandidatePairing", "候选配对", "语义与主题预筛"),
    (4, "CoreAnalyser", "差异判断", "风险等级分类"),
    (5, "EvidenceRules", "证据校验", "原文来源检查"),
    (6, "ReportBuilder", "报告生成", "建议与结论"),
]


class Agents:
    """Hybrid Pipeline 当前生产路径使用的认知模型封装。"""

    def __init__(self, llm: LLMClient | Any, expert_llm: LLMClient | Any | None = None):
        self.llm = llm
        self.core_llm = llm
        self.expert_llm = expert_llm if expert_llm is not None else llm

    def analyze_diffs_combined(
        self,
        group_clauses: list[dict[str, Any]],
        sub_clauses: list[dict[str, Any]],
        group_cps: list[dict[str, Any]],
        sub_cps: list[dict[str, Any]],
    ) -> tuple[CoreAnalyserOutput, list[tuple[int, int | None]]]:
        group_e = attach_clause_to_cps(group_cps, group_clauses)
        sub_e = attach_clause_to_cps(sub_cps, sub_clauses)
        candidates = prefilter_match_candidates(group_e, sub_e)
        g_view, s_view, hints, gi_orig, si_orig = build_match_views(group_e, sub_e, candidates)

        pairs_for_llm = []
        pair_indices: list[tuple[int, int | None]] = []
        matched_group: set[int] = set()
        for i, h in enumerate(hints):
            mapped = remap_match_pair_indices(
                h["group_control_index"], h["subsidiary_control_index"], gi_orig, si_orig
            )
            if not mapped:
                continue
            gi, si = mapped
            matched_group.add(gi)
            pairs_for_llm.append({
                "pair_index": i,
                "group_index": gi,
                "sub_index": si,
                "control_topic": h.get("control_topic", ""),
                "prefilter_score": h.get("prefilter_score", 0),
                "group_cp": cp_for_llm(group_e[gi]),
                "sub_cp": cp_for_llm(sub_e[si]),
            })
            pair_indices.append((gi, si))

        for gi, gcp in enumerate(group_e):
            if gi in matched_group:
                continue
            pairs_for_llm.append({
                "pair_index": len(pair_indices),
                "group_index": gi,
                "sub_index": None,
                "missing_subsidiary": True,
                "control_topic": gcp.get("control_topic", ""),
                "group_cp": cp_for_llm(gcp),
            })
            pair_indices.append((gi, None))

        group_full_text = "\n".join(
            f"{c.get('location_label') or c.get('clause_no')}: {c.get('clause_text', '')}"
            for c in group_clauses[:35]
        )[:8000]
        sub_full_text = "\n".join(
            f"{c.get('location_label') or c.get('clause_no')}: {c.get('clause_text', '')}"
            for c in sub_clauses[:35]
        )[:8000]
        user = json.dumps(
            {
                "group_full_text_excerpt": group_full_text,
                "sub_full_text_excerpt": sub_full_text,
                "pairs": pairs_for_llm[:12],
            },
            ensure_ascii=False,
        )[:18000]
        t0 = time.time()
        _debug_log(
            "pre-fix",
            "H21",
            "agents.py:analyze_diffs_combined",
            "llm call start",
            {"pairs_for_llm": len(pairs_for_llm[:12])},
        )
        data = self.core_llm.complete_json(CORE_ANALYSER_SYSTEM, user)
        _debug_log(
            "pre-fix",
            "H21",
            "agents.py:analyze_diffs_combined",
            "llm call end",
            {"duration_ms": int((time.time() - t0) * 1000), "diffs_raw": len(data.get("differences", []))},
        )
        out = CoreAnalyserOutput.model_validate(data)
        return out, pair_indices

    def analyze_diffs_map_reduce(
        self,
        group_clauses: list[dict[str, Any]],
        sub_clauses: list[dict[str, Any]],
        group_cps: list[dict[str, Any]],
        sub_cps: list[dict[str, Any]],
        *,
        max_workers: int = 3,
    ) -> tuple[CoreAnalyserOutput, list[tuple[int, int | None]]]:
        """Map group controls by chapter, then reduce results into global indices."""
        clause_by_id = {c.get("id"): c for c in group_clauses}
        buckets: dict[str, list[int]] = {}
        for index, cp in enumerate(group_cps):
            clause = clause_by_id.get(cp.get("clause_id"), {})
            key = clause.get("chapter_title") or clause.get("location_label") or f"batch-{index // 6}"
            buckets.setdefault(str(key), []).append(index)
        groups = list(buckets.values()) or [list(range(len(group_cps)))]
        if len(groups) == 1:
            return self.analyze_diffs_combined(group_clauses, sub_clauses, group_cps, sub_cps)

        merged_diffs = []
        merged_pairs: list[tuple[int, int | None]] = []

        def run(indices: list[int]):
            subset = [group_cps[i] for i in indices]
            out, pairs = self.analyze_diffs_combined(group_clauses, sub_clauses, subset, sub_cps)
            return indices, out, pairs

        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(groups)))) as pool:
            futures = {pool.submit(run, indices): indices for indices in groups}
            for future in as_completed(futures):
                indices = futures[future]
                try:
                    indices, out, pairs = future.result()
                except Exception as exc:
                    from app.pipeline.agent_schemas import DiffItem

                    out = CoreAnalyserOutput(differences=[])
                    pairs = []
                    for local_index, global_index in enumerate(indices):
                        pairs.append((local_index, None))
                        topic = group_cps[global_index].get("control_topic") or "复杂控制要求"
                        out.differences.append(
                            DiffItem(
                                pair_index=local_index,
                                diff_type="待确认",
                                risk_level="中",
                                summary=f"{topic}：模型计算异常，需人工复核",
                                ai_reason=f"系统在章节并行分析时发生降级（{type(exc).__name__}），未强行生成确定性结论。",
                                suggestion="请结合集团与子公司原文进行人工复核。",
                                confidence=0.5,
                            )
                        )
                pair_offset = len(merged_pairs)
                for gi, si in pairs:
                    merged_pairs.append((indices[gi], si))
                for item in out.differences:
                    merged_diffs.append(item.model_copy(update={"pair_index": item.pair_index + pair_offset}))

        return CoreAnalyserOutput(differences=merged_diffs), merged_pairs

    def review_diffs_by_expert(
        self,
        diffs: list[dict[str, Any]],
    ) -> ExpertReviewOutput:
        constrained_diffs = []
        for diff in diffs[:20]:
            item = dict(diff)
            item["group_excerpt"] = (item.get("group_excerpt") or "")[:300]
            item["subsidiary_excerpt"] = (item.get("subsidiary_excerpt") or "")[:300]
            constrained_diffs.append(item)
        payload = {
            "differences": constrained_diffs,
            "review_scope": "仅仲裁候选差异及其必要证据，不重新检索全文",
        }
        user = json.dumps(payload, ensure_ascii=False)[:22000]
        t0 = time.time()
        _debug_log(
            "pre-fix",
            "H21",
            "agents.py:review_diffs_by_expert",
            "expert review start",
            {"diffs": len(diffs[:20])},
        )
        data = self.expert_llm.complete_json(SOE_EXPERT_REVIEW_SYSTEM, user)
        _debug_log(
            "pre-fix",
            "H21",
            "agents.py:review_diffs_by_expert",
            "expert review end",
            {"duration_ms": int((time.time() - t0) * 1000), "items": len(data.get("items", []))},
        )
        return ExpertReviewOutput.model_validate(data)
