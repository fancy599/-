from app.models import Difference, Document, ReviewTask
from app.services.robustness import LOW_CONFIDENCE_REASON, MAX_AGENT_TURNS


def test_low_confidence_difference_is_downgraded_before_persist(db):
    g = Document(document_name="G", unit_name="集团", document_level="group", raw_text="集团制度")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", raw_text="子公司制度")
    db.add_all([g, s])
    db.flush()
    task = ReviewTask(task_name="低置信度", group_document_id=g.id, subsidiary_document_id=s.id)
    db.add(task)
    db.flush()
    diff = Difference(
        task_id=task.id,
        diff_type="缺失",
        risk_level="高",
        confidence=0.42,
        ai_reason="模型不确定但强判为缺失",
    )
    db.add(diff)
    db.commit()
    db.refresh(diff)

    assert diff.diff_type == "待确认"
    assert diff.risk_level == "中"
    assert diff.review_status == "pending_evidence"
    assert LOW_CONFIDENCE_REASON in diff.ai_reason
    assert diff.original_ai_reason == "模型不确定但强判为缺失"
    assert diff.fallback_reason == "LOW_CONFIDENCE"


def test_robustness_status_exposes_fallback_boundaries(client):
    body = client.get("/api/robustness/status").json()
    assert body["max_agent_turns"] == MAX_AGENT_TURNS
    assert body["low_confidence_threshold"] == 0.60
    assert body["checkpoint_mode"] == "pipeline_step_logs"
