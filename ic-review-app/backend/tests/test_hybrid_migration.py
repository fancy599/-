from unittest.mock import patch
from types import SimpleNamespace

from app.config import Settings
from app.models import Clause, DiffClauseMapping, Difference, Document, ReviewTask, TaskCheckpoint, TaskExecutionEvent
from app.pipeline.agents import Agents
from app.pipeline.orchestrator import PipelineOrchestrator
from app.services.llm import FakeLLMClient
from app.services.parser import ParseError
from app.services.task_executor import Submission
from app.services.task_executor import submit_pipeline


def test_legacy_fast_and_full_modes_map_to_hybrid(client, db):
    g = Document(document_name="G", unit_name="集团", document_level="group", parse_status="parsed", raw_text="第十条 集团审批。")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="第十条 子公司审批。")
    db.add_all([g, s])
    db.flush()
    task = ReviewTask(task_name="兼容迁移", group_document_id=g.id, subsidiary_document_id=s.id)
    db.add(task)
    db.commit()

    with patch("app.api.routes.submit_pipeline", return_value=Submission(backend="local_thread")):
        response = client.post(f"/api/tasks/{task.id}/run?mode=full")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid"
    assert "已弃用" in body["deprecated_notice"]
    db.refresh(task)
    assert task.execution_mode == "hybrid"


def test_parse_failure_is_persisted_as_document_record(client):
    with patch("app.api.routes.extract_text_from_file", side_effect=ParseError("文档已加密", "ERR_DOC_ENCRYPTED")):
        response = client.post(
            "/api/documents/upload",
            data={
                "document_name": "加密制度",
                "unit_name": "测试单位",
                "document_level": "group",
                "business_domain": "采购",
                "version": "V1",
            },
            files={"file": ("encrypted.pdf", b"fake encrypted pdf", "application/pdf")},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["parse_status"] == "parse_failed"
    assert body["parse_error_code"] == "ERR_DOC_ENCRYPTED"


def test_create_task_rejects_parse_failed_document(client, db):
    g = Document(document_name="加密集团制度", unit_name="集团", document_level="group", parse_status="parse_failed")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="子公司制度")
    db.add_all([g, s])
    db.commit()
    response = client.post(
        "/api/tasks",
        json={"task_name": "不可运行", "group_document_id": g.id, "subsidiary_document_id": s.id},
    )
    assert response.status_code == 400
    assert "尚不可审查" in response.json()["detail"]


def test_hybrid_persists_nm_mapping_and_checkpoint(db):
    g = Document(document_name="G", unit_name="集团", document_level="group", raw_text="集团制度")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", raw_text="子公司制度")
    db.add_all([g, s])
    db.flush()
    task = ReviewTask(task_name="血缘", group_document_id=g.id, subsidiary_document_id=s.id)
    db.add(task)
    db.flush()
    gc = Clause(document_id=g.id, clause_text="集团条款")
    sc = Clause(document_id=s.id, clause_text="子公司条款")
    db.add_all([gc, sc])
    db.flush()
    diff = Difference(task_id=task.id, diff_type="弱化", risk_level="中", group_clause_id=gc.id, subsidiary_clause_id=sc.id)
    db.add(diff)
    db.commit()

    orch = PipelineOrchestrator(db, llm=FakeLLMClient({}))
    orch._sync_diff_clause_mappings(task.id)
    orch._log_step(task, 1, "StructureEngine", "completed", "结构化完成", {"count": 2})

    assert db.query(DiffClauseMapping).filter(DiffClauseMapping.difference_id == diff.id).count() == 2
    assert db.query(TaskCheckpoint).filter(TaskCheckpoint.task_id == task.id).count() == 1


def test_runtime_status_declares_hybrid_only(client):
    body = client.get("/api/runtime/status").json()
    assert body["pipeline_mode"] == "hybrid"
    assert body["legacy_modes_deprecated"] is True
    assert "CoreAnalyser(Map)" in body["production_path"]
    assert body["model_routing"]["CoreAnalyser"] == "medium_model"
    assert body["model_routing"]["SOEExpertAgent"] == "large_model"


def test_dedicated_dual_model_keys_are_a_valid_configuration():
    settings = Settings(
        llm_api_key="",
        core_analyser_api_key="core-key",
        soe_expert_api_key="expert-key",
    )

    assert settings.llm_configured is True


def test_hybrid_standard_controls_do_not_call_legacy_agent(db):
    g = Document(document_name="G", unit_name="集团", document_level="group", raw_text="集团制度")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", raw_text="子公司制度")
    db.add_all([g, s])
    db.flush()
    task = ReviewTask(task_name="仅两层认知模型", business_domain="采购", group_document_id=g.id, subsidiary_document_id=s.id)
    db.add(task)
    db.commit()

    orch = PipelineOrchestrator(db, llm=FakeLLMClient({}))
    legacy_method = "generate_" + "standard_controls"
    assert not hasattr(orch.agents, legacy_method)
    ctx = {}
    orch._step_standard_controls(task, g, s, ctx)

    assert len(ctx["standard_cps"]) == 22
    assert {item["business_domain"] for item in ctx["standard_cps"]} == {"采购"}
    assert ctx["standard_domain"] == "采购"


def test_expert_agent_receives_only_bounded_difference_evidence():
    class CapturingLLM:
        def __init__(self):
            self.user = ""

        def complete_json(self, system, user):
            self.user = user
            return {"review_summary": "已仲裁", "items": []}

    llm = CapturingLLM()
    agents = Agents(llm)
    long_text = "证据" * 500
    agents.review_diffs_by_expert(
        [{"diff_index": 0, "group_excerpt": long_text, "subsidiary_excerpt": long_text, "summary": "候选差异"}]
    )

    assert "group_full_text_excerpt" not in llm.user
    assert "sub_full_text_excerpt" not in llm.user
    assert len(long_text) > 300
    assert long_text not in llm.user


def test_core_and_expert_use_separate_model_clients():
    class TrackingLLM:
        def __init__(self, response):
            self.response = response
            self.calls = []

        def complete_json(self, system, user):
            self.calls.append((system, user))
            return self.response

    core = TrackingLLM({"differences": []})
    expert = TrackingLLM({"review_summary": "大型模型已仲裁", "items": []})
    agents = Agents(core, expert)

    agents.analyze_diffs_combined([], [], [], [])
    agents.review_diffs_by_expert([{"diff_index": 0, "summary": "候选差异"}])

    assert len(core.calls) == 1
    assert "Core Analyser" in core.calls[0][0]
    assert len(expert.calls) == 1
    assert "SOEInternalControlExpert" in expert.calls[0][0]


def test_delete_task_cleans_hybrid_audit_records(client, db):
    g = Document(document_name="G", unit_name="集团", document_level="group", raw_text="集团制度")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", raw_text="子公司制度")
    db.add_all([g, s])
    db.flush()
    task = ReviewTask(task_name="清理", group_document_id=g.id, subsidiary_document_id=s.id)
    db.add(task)
    db.flush()
    clause = Clause(document_id=g.id, clause_text="集团条款")
    db.add(clause)
    db.flush()
    diff = Difference(task_id=task.id, diff_type="缺失", risk_level="中", group_clause_id=clause.id)
    db.add(diff)
    db.flush()
    db.add(DiffClauseMapping(difference_id=diff.id, source_type="group", clause_id=clause.id))
    db.add(TaskCheckpoint(task_id=task.id, node_key="step-1", input_hash="hash"))
    db.add(TaskExecutionEvent(task_id=task.id, event_type="submitted"))
    db.commit()

    response = client.delete(f"/api/tasks/{task.id}")
    assert response.status_code == 200
    assert db.query(DiffClauseMapping).count() == 0
    assert db.query(TaskCheckpoint).count() == 0
    assert db.query(TaskExecutionEvent).count() == 0


def test_celery_executor_falls_back_to_local_when_redis_is_down():
    runner_calls = []

    class ImmediateThread:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    fake_settings = SimpleNamespace(task_executor="celery", redis_url="redis://127.0.0.1:1/0")
    with patch("app.services.task_executor.get_settings", return_value=fake_settings), patch(
        "app.services.task_executor.threading.Thread", ImmediateThread
    ):
        submission = submit_pipeline(
            lambda task_id, from_step, mode: runner_calls.append((task_id, from_step, mode)),
            9,
            2,
            "hybrid",
        )

    assert submission.backend == "local_thread"
    assert submission.degraded is True
    assert runner_calls == [(9, 2, "hybrid")]
