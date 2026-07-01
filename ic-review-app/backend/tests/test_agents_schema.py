from app.pipeline.agent_schemas import CoreAnalyserOutput, ExpertReviewOutput


def test_diff_output_schema_with_suggestion_object():
    data = {
        "differences": [
            {
                "pair_index": 0,
                "diff_type": "越权",
                "risk_level": "高",
                "ai_reason": "理由",
                "suggestion": {"direction": "下调审批权限", "proposed_text": "超过200万元须报批"},
                "confidence": 0.9,
            }
        ]
    }
    out = CoreAnalyserOutput.model_validate(data)
    assert "下调审批权限" in out.differences[0].suggestion
    assert out.differences[0].summary


def test_expert_review_output_schema():
    data = {
        "review_summary": "专家复核完成",
        "items": [
            {
                "diff_index": 0,
                "keep": True,
                "diff_type": "越权",
                "risk_level": "High",
                "summary": "审批权限越权",
                "ai_reason": "集团授权边界被突破",
                "suggestion": "收回审批权限",
                "confidence": 0.9,
                "audit_comment": "保留",
            }
        ],
    }
    out = ExpertReviewOutput.model_validate(data)
    assert out.items[0].risk_level == "高"
