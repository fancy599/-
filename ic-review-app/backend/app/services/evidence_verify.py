"""确定性证据校验：校验条款 ID 与摘要是否能在原文中定位。"""
from __future__ import annotations

import re
from typing import Any

from app.services.text_normalize import is_low_quality_clause

_WS = re.compile(r"\s+")


def _normalize(s: str) -> str:
    return _WS.sub("", (s or "").strip())


def excerpt_in_clause(excerpt: str, clause_text: str, *, min_len: int = 12) -> bool:
    if not excerpt or not clause_text:
        return False
    ex = _normalize(excerpt)
    body = _normalize(clause_text)
    if len(ex) < min_len:
        return ex in body
    if ex in body:
        return True
    probe = ex[: min(80, len(ex))]
    return len(probe) >= min_len and probe in body


def _clause_maps(clauses: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for c in clauses:
        if c.get("id") is not None:
            out[int(c["id"])] = c
    return out


def verify_single_draft(
    draft: dict[str, Any],
    group_clauses: list[dict[str, Any]],
    sub_clauses: list[dict[str, Any]],
) -> dict[str, Any]:
    """返回 evidence_ok, group_location, subsidiary_location, note。"""
    pair = draft.get("pair") or {}
    g_id = pair.get("group_clause_id")
    s_id = pair.get("subsidiary_clause_id")
    g_map = _clause_maps(group_clauses)
    s_map = _clause_maps(sub_clauses)

    notes: list[str] = []
    ok = True

    gc = g_map.get(int(g_id)) if g_id is not None else None
    if not gc:
        ok = False
        notes.append("集团条款ID不存在于解析结果")
    else:
        g_body = gc.get("clause_text") or ""
        g_ex = draft.get("group_excerpt") or ""
        if g_ex and not excerpt_in_clause(g_ex, g_body):
            if not is_low_quality_clause(g_body):
                ok = False
                notes.append("集团摘要无法在对应条款原文中定位")

    sc = s_map.get(int(s_id)) if s_id is not None else None
    diff_type = draft.get("diff_type") or ""

    if s_id is None:
        if diff_type != "缺失":
            notes.append("未关联子公司条款（非缺失类差异需人工核对）")
    elif not sc:
        ok = False
        notes.append("子公司条款ID不存在于解析结果")
    else:
        s_body = sc.get("clause_text") or ""
        s_ex = draft.get("subsidiary_excerpt") or ""
        if s_ex and not is_low_quality_clause(s_body):
            if not excerpt_in_clause(s_ex, s_body):
                if diff_type != "缺失":
                    ok = False
                    notes.append("子公司摘要无法在对应条款原文中定位")
        elif is_low_quality_clause(s_body) and diff_type != "缺失":
            notes.append("子公司条款正文质量较差，建议制度库预览原文")

    return {
        "evidence_ok": ok,
        "group_location": (gc.get("location_label") if gc else None) or draft.get("group_location", ""),
        "subsidiary_location": (sc.get("location_label") if sc else None) or draft.get("subsidiary_location", ""),
        "note": "；".join(notes),
    }


def verify_diff_drafts(
    drafts: list[dict[str, Any]],
    group_clauses: list[dict[str, Any]],
    sub_clauses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [verify_single_draft(d, group_clauses, sub_clauses) for d in drafts]
