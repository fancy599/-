from copy import deepcopy

from app.models import Document, ReviewTask
from app.pipeline.orchestrator import PipelineOrchestrator
from app.services.llm import FakeLLMClient
from tests.conftest import fake_llm_responses


def test_orchestrator_full_run(db, fake_llm_responses):
    g = Document(
        document_name="集团制度",
        unit_name="集团",
        document_level="group",
        parse_status="parsed",
        raw_text="第十二条 超过200万元须集团审批。",
    )
    s = Document(
        document_name="子公司制度",
        unit_name="子公司",
        document_level="subsidiary",
        parse_status="parsed",
        raw_text="第八条 500万元以下总经理办公会审批。",
    )
    db.add(g)
    db.add(s)
    db.flush()
    task = ReviewTask(
        task_name="流水线测试",
        group_document_id=g.id,
        subsidiary_document_id=s.id,
        status="draft",
    )
    db.add(task)
    db.commit()

    fake = FakeLLMClient(fake_llm_responses)
    orch = PipelineOrchestrator(db, llm=fake, mode="fast")
    orch.run(task.id)

    db.refresh(task)
    assert task.status == "reviewing"
    assert task.current_step == 6
    from app.models import Difference, PipelineRunLog

    assert db.query(PipelineRunLog).filter(PipelineRunLog.task_id == task.id).count() >= 4
    diff = db.query(Difference).filter(Difference.task_id == task.id).first()
    assert diff is not None
    assert "国企内控专家复核" in diff.ai_reason
    assert db.query(PipelineRunLog).filter(
        PipelineRunLog.task_id == task.id,
        PipelineRunLog.agent_name == "SOEExpertAgent",
    ).count() == 1


def test_expert_review_marks_diff_even_without_item_audit_comment(db, fake_llm_responses):
    g = Document(
        document_name="集团制度",
        unit_name="集团",
        document_level="group",
        parse_status="parsed",
        raw_text="第十二条 超过200万元须集团审批。",
    )
    s = Document(
        document_name="子公司制度",
        unit_name="子公司",
        document_level="subsidiary",
        parse_status="parsed",
        raw_text="第八条 500万元以下总经理办公会审批。",
    )
    db.add(g)
    db.add(s)
    db.flush()
    task = ReviewTask(
        task_name="专家标记测试",
        group_document_id=g.id,
        subsidiary_document_id=s.id,
        status="draft",
    )
    db.add(task)
    db.commit()

    responses = deepcopy(fake_llm_responses)
    responses["国企内控专家复核"]["items"][0]["audit_comment"] = ""
    fake = FakeLLMClient(responses)
    PipelineOrchestrator(db, llm=fake, mode="fast").run(task.id)

    from app.models import Difference

    diff = db.query(Difference).filter(Difference.task_id == task.id).first()
    assert diff is not None
    assert diff.ai_reason.startswith("【国企内控专家复核】")
    assert "超过200万元" in diff.ai_reason
