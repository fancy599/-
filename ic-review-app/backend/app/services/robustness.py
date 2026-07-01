"""Deterministic safety rails shared by pipeline and API layers."""
from __future__ import annotations

from app.models import Difference

LOW_CONFIDENCE_THRESHOLD = 0.60
MAX_AGENT_TURNS = 3
LOW_CONFIDENCE_REASON = (
    "系统检测到相关制度内容与控制点语义有关，但当前证据或表述较为模糊，"
    "无法稳定判定具体差异类型。已降级为待确认，请结合双栏原文人工复核。"
)


def apply_low_confidence_fallback(diff: Difference) -> bool:
    """Prevent uncertain model output from becoming an assertive high-risk finding."""
    if diff.confidence is None or diff.confidence <= 0 or diff.confidence >= LOW_CONFIDENCE_THRESHOLD:
        return False
    if not diff.original_ai_reason:
        diff.original_ai_reason = diff.ai_reason or ""
    diff.fallback_reason = "LOW_CONFIDENCE"
    diff.risk_level = "中"
    diff.review_status = "pending_evidence"
    diff.diff_type = "待确认"
    if LOW_CONFIDENCE_REASON not in (diff.ai_reason or ""):
        diff.ai_reason = f"{LOW_CONFIDENCE_REASON}\n\n原判断：{diff.ai_reason or '未提供'}"
    return True
