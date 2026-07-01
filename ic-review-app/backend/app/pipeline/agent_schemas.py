from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class DiffItem(BaseModel):
    pair_index: int
    diff_type: str
    risk_level: str
    summary: str = ""
    ai_reason: str
    suggestion: str = ""
    confidence: float = 0.0

    @model_validator(mode="before")
    @classmethod
    def normalize_suggestion(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        suggestion = data.get("suggestion")
        if isinstance(suggestion, dict):
            direction = (suggestion.get("direction") or "").strip()
            proposed = (suggestion.get("proposed_text") or "").strip()
            parts = [part for part in (direction, proposed) if part]
            data["suggestion"] = "\n".join(parts) if parts else ""
        if not data.get("summary") and data.get("ai_reason"):
            data["summary"] = str(data["ai_reason"])[:120]
        return data

    @field_validator("risk_level", mode="before")
    @classmethod
    def normalize_risk(cls, value: Any) -> str:
        text = str(value or "").strip()
        mapping = {
            "High": "高",
            "Medium": "中",
            "Low": "低",
            "high": "高",
            "medium": "中",
            "low": "低",
        }
        return mapping.get(text, text)


class CoreAnalyserOutput(BaseModel):
    differences: list[DiffItem]


class ExpertReviewItem(BaseModel):
    diff_index: int
    keep: bool = True
    diff_type: str = ""
    risk_level: str = ""
    summary: str = ""
    ai_reason: str = ""
    suggestion: str = ""
    confidence: float | None = None
    audit_comment: str = ""

    @field_validator("risk_level", mode="before")
    @classmethod
    def normalize_risk(cls, value: Any) -> str:
        text = str(value or "").strip()
        mapping = {
            "High": "高",
            "Medium": "中",
            "Low": "低",
            "high": "高",
            "medium": "中",
            "low": "低",
        }
        return mapping.get(text, text)


class ExpertReviewOutput(BaseModel):
    review_summary: str = ""
    items: list[ExpertReviewItem] = Field(default_factory=list)
