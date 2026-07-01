"""匹配前工程过滤：缩小候选对，并为 LLM 附带条款原文。"""
from __future__ import annotations

import re
from typing import Any

_CJK = re.compile(r"[\u4e00-\u9fff]")


def _clause_by_id(clauses: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(c["id"]): c for c in clauses if c.get("id") is not None}


def attach_clause_to_cps(cps: list[dict[str, Any]], clauses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为控制点补充 clause_text / location_label，避免匹配阶段信息孤岛。"""
    by_id = _clause_by_id(clauses)
    enriched: list[dict[str, Any]] = []
    for cp in cps:
        cid = cp.get("clause_id")
        clause = by_id.get(int(cid)) if cid is not None else {}
        text = (clause.get("clause_text") or cp.get("requirement") or "").strip()
        item = dict(cp)
        item["clause_text"] = text[:800]
        item["location_label"] = clause.get("location_label") or ""
        item["clause_no"] = clause.get("clause_no") or ""
        item["chapter_title"] = clause.get("chapter_title") or ""
        enriched.append(item)
    return enriched


def _cjk_chars(text: str) -> set[str]:
    return set(_CJK.findall(text or ""))


def text_overlap_score(a: str, b: str) -> float:
    sa, sb = _cjk_chars(a), _cjk_chars(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def prefilter_match_candidates(
    group_cps: list[dict[str, Any]],
    sub_cps: list[dict[str, Any]],
    *,
    max_per_group: int = 3,
    max_total: int = 24,
) -> list[dict[str, Any]]:
    """
    按 control_topic + 条款原文相似度预筛，避免 50×50 全量交叉进 LLM。
    返回元素含 group_index / sub_index / prefilter_score。
    """
    if not group_cps or not sub_cps:
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    for gi, gc in enumerate(group_cps):
        g_topic = (gc.get("control_topic") or "").strip()
        g_text = f"{gc.get('clause_text', '')} {gc.get('requirement', '')}"

        scored: list[tuple[float, int]] = []
        for si, sc in enumerate(sub_cps):
            s_topic = (sc.get("control_topic") or "").strip()
            s_text = f"{sc.get('clause_text', '')} {sc.get('requirement', '')}"
            score = text_overlap_score(g_text, s_text)
            if g_topic and g_topic == s_topic:
                score += 0.45
            elif g_topic and g_topic not in ("一般控制", "制度控制要求") and s_topic in ("一般控制", "制度控制要求"):
                score += 0.08
            if score >= 0.12:
                scored.append((score, si))

        scored.sort(key=lambda x: x[0], reverse=True)
        for score, si in scored[:max_per_group]:
            key = (gi, si)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({
                "group_index": gi,
                "sub_index": si,
                "prefilter_score": round(score, 3),
                "control_topic": group_cps[gi].get("control_topic") or sub_cps[si].get("control_topic"),
            })

    candidates.sort(key=lambda x: x["prefilter_score"], reverse=True)

    return candidates[:max_total]


def cp_for_llm(cp: dict[str, Any]) -> dict[str, Any]:
    """送入核心分析模型的单条控制点（保留原文）。"""
    return {
        "control_topic": cp.get("control_topic", ""),
        "subject_role": cp.get("subject_role", ""),
        "action": cp.get("action", ""),
        "object": cp.get("object", ""),
        "threshold": cp.get("threshold", ""),
        "requirement": (cp.get("requirement") or "")[:200],
        "clause_text": (cp.get("clause_text") or "")[:600],
        "location_label": cp.get("location_label", ""),
        "clause_no": cp.get("clause_no", ""),
    }


def build_match_views(
    group_cps: list[dict[str, Any]],
    sub_cps: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> tuple[list[dict], list[dict], list[dict], list[int], list[int]]:
    """压缩为仅含候选涉及的子集，并返回索引回射表。"""
    gi_orig = sorted({c["group_index"] for c in candidates})
    si_orig = sorted({c["sub_index"] for c in candidates})
    gi_map = {o: i for i, o in enumerate(gi_orig)}
    si_map = {o: i for i, o in enumerate(si_orig)}

    g_view = [cp_for_llm(group_cps[i]) for i in gi_orig]
    s_view = [cp_for_llm(sub_cps[i]) for i in si_orig]
    hints = [
        {
            "group_control_index": gi_map[c["group_index"]],
            "subsidiary_control_index": si_map[c["sub_index"]],
            "prefilter_score": c.get("prefilter_score", 0),
            "control_topic": c.get("control_topic", ""),
        }
        for c in candidates
        if c["group_index"] in gi_map and c["sub_index"] in si_map
    ]
    return g_view, s_view, hints, gi_orig, si_orig


def remap_match_pair_indices(
    group_index: int,
    subsidiary_index: int,
    gi_orig: list[int],
    si_orig: list[int],
) -> tuple[int, int] | None:
    if group_index < 0 or group_index >= len(gi_orig):
        return None
    if subsidiary_index < 0 or subsidiary_index >= len(si_orig):
        return None
    return gi_orig[group_index], si_orig[subsidiary_index]
