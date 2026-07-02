from datetime import datetime
import time

from app.models import Document
from app.seed import seed_demo


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_seed_and_dashboard(client, db):
    seed_demo(db)
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["pending_task"] is not None
    assert data["pending_task"]["diff_count"] >= 3


def test_dashboard_recovers_naive_running_task_without_500(client, db):
    from app.models import ReviewTask

    g = Document(document_name="G", unit_name="集团", document_level="group", parse_status="parsed", raw_text="集团制度文本")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="子公司制度文本")
    db.add(g)
    db.add(s)
    db.flush()
    task = ReviewTask(
        task_name="历史运行任务",
        group_document_id=g.id,
        subsidiary_document_id=s.id,
        status="running",
        created_at=datetime(2026, 1, 1, 0, 0, 0),
    )
    db.add(task)
    db.commit()

    r = client.get("/api/dashboard")
    assert r.status_code == 200
    db.refresh(task)
    assert task.status == "failed"


def test_list_diffs_after_seed(client, db):
    result = seed_demo(db)
    r = client.get(f"/api/tasks/{result['task_id']}/diffs")
    assert r.status_code == 200
    assert len(r.json()) >= 3


def test_list_diffs_orders_by_group_control_sequence(client, db):
    from app.models import Clause, Difference, ReviewTask

    g = Document(document_name="G", unit_name="集团", document_level="group", parse_status="parsed", raw_text="集团制度文本")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="子公司制度文本")
    db.add_all([g, s])
    db.flush()
    c1 = Clause(document_id=g.id, clause_no="第一条", clause_text="第一条 预算编制控制点", location_label="第一条")
    c2 = Clause(document_id=g.id, clause_no="第二条", clause_text="第二条 预算审批控制点", location_label="第二条")
    db.add_all([c1, c2])
    db.flush()
    task = ReviewTask(task_name="排序任务", group_document_id=g.id, subsidiary_document_id=s.id)
    db.add(task)
    db.flush()
    later_high = Difference(
        task_id=task.id,
        group_clause_id=c2.id,
        diff_type="缺失",
        risk_level="高",
        control_topic="审批",
        summary="第二条差异",
        group_location="第二条",
    )
    earlier_low = Difference(
        task_id=task.id,
        group_clause_id=c1.id,
        diff_type="不一致",
        risk_level="低",
        control_topic="编制",
        summary="第一条差异",
        group_location="第一条",
    )
    db.add_all([later_high, earlier_low])
    db.commit()

    r = client.get(f"/api/tasks/{task.id}/diffs")
    assert r.status_code == 200
    rows = r.json()
    assert [row["id"] for row in rows[:2]] == [earlier_low.id, later_high.id]


def test_diff_detail_exposes_expert_review_and_semantic_flag(client, db):
    from app.models import Clause, Difference, ReviewTask

    g = Document(document_name="G", unit_name="集团", document_level="group", parse_status="parsed", raw_text="集团制度文本")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="子公司制度全文覆盖采购流程")
    db.add_all([g, s])
    db.flush()
    c = Clause(document_id=g.id, clause_no="第一条", clause_text="第一条 采购申请应先预算审核。", location_label="第一条")
    db.add(c)
    db.flush()
    task = ReviewTask(task_name="专家任务", group_document_id=g.id, subsidiary_document_id=s.id)
    db.add(task)
    db.flush()
    diff = Difference(
        task_id=task.id,
        group_clause_id=c.id,
        subsidiary_clause_id=None,
        diff_type="缺失",
        risk_level="高",
        control_topic="采购预算",
        summary="缺少预算审核控制点",
        group_location="第一条",
        ai_reason="【国企内控专家复核】专家认为该控制点应保留。\n子公司全文未体现预算审核。",
    )
    db.add(diff)
    db.commit()

    r = client.get(f"/api/diffs/{diff.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["semantic_review"] is True
    assert body["expert_reviewed"] is True
    assert body["expert_review_note"] == "专家认为该控制点应保留。"
    assert body["ai_reason"] == "子公司全文未体现预算审核。"
    assert "采购申请应先预算审核" in body["group_clause_text"]
    assert "子公司制度全文覆盖采购流程" in body["subsidiary_clause_text"]


def test_review_diff(client, db):
    result = seed_demo(db)
    diffs = client.get(f"/api/tasks/{result['task_id']}/diffs").json()
    diff_id = diffs[0]["id"]
    r = client.post(f"/api/diffs/{diff_id}/review", json={"action": "confirmed", "comment": "同意"})
    assert r.status_code == 200
    assert r.json()["review_status"] == "confirmed"
    reviews = client.get("/api/reviews").json()
    assert len(reviews) >= 1
    # 连点不应产生重复记录
    r2 = client.post(f"/api/diffs/{diff_id}/review", json={"action": "confirmed", "comment": "同意"})
    assert r2.status_code == 200
    reviews2 = client.get("/api/reviews").json()
    same_diff_logs = [x for x in reviews2 if x["difference_id"] == diff_id]
    assert len(same_diff_logs) == 1


def test_exemption_requires_approval_and_can_be_revoked(client, db):
    result = seed_demo(db)
    diff_id = client.get(f"/api/tasks/{result['task_id']}/diffs").json()[0]["id"]

    created = client.post(
        f"/api/diffs/{diff_id}/exemptions",
        json={
            "justification": "该子公司已取得集团专项授权，允许在紧急事项下执行例外流程。",
            "policy_basis": "集团专项授权批复〔2026〕3号",
            "org_scope": "本机构",
        },
    )
    assert created.status_code == 200
    exemption = created.json()
    assert exemption["status"] == "pending_approval"
    assert client.get(f"/api/diffs/{diff_id}").json()["review_status"] == "exemption_pending"

    approved = client.post(f"/api/exemptions/{exemption['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"
    assert client.get(f"/api/diffs/{diff_id}").json()["review_status"] == "exempted"

    revoked = client.post(f"/api/exemptions/{exemption['id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"
    assert client.get(f"/api/diffs/{diff_id}").json()["review_status"] == "pending"


def test_supplement_delta_audit_only_updates_target_diff(client, db):
    result = seed_demo(db)
    rows = client.get(f"/api/tasks/{result['task_id']}/diffs").json()
    target = rows[0]
    untouched = rows[1]

    created = client.post(
        f"/api/diffs/{target['id']}/supplements",
        json={
            "assignee": "子公司制度管理员",
            "requirement": f"请补充能够证明「{target['control_topic']}」已覆盖的配套制度条款。",
        },
    )
    assert created.status_code == 200
    request_row = created.json()
    assert request_row["status"] == "pending"
    assert client.get(f"/api/diffs/{target['id']}").json()["review_status"] == "need_supplement"

    submitted = client.post(
        f"/api/supplements/{request_row['id']}/submit",
        json={"submitted_text": f"配套制度明确规定：{target['control_topic']}必须履行申请、审核、审批和归档程序。"},
    )
    assert submitted.status_code == 200
    assert submitted.json()["result"] == "compliant_by_supplement"
    assert client.get(f"/api/diffs/{target['id']}").json()["review_status"] == "compliant_by_supplement"
    assert client.get(f"/api/diffs/{untouched['id']}").json()["review_status"] == untouched["review_status"]


def test_undo_review(client, db):
    result = seed_demo(db)
    diffs = client.get(f"/api/tasks/{result['task_id']}/diffs").json()
    diff_id = diffs[0]["id"]
    client.post(f"/api/diffs/{diff_id}/review", json={"action": "confirmed", "comment": "同意"})
    client.post(f"/api/diffs/{diff_id}/review", json={"action": "confirmed", "comment": "再次确认"})
    assert len(client.get("/api/reviews").json()) == 1
    log_id = client.get("/api/reviews").json()[0]["id"]
    r = client.delete(f"/api/reviews/{log_id}")
    assert r.status_code == 200
    assert r.json()["removed_count"] == 2
    diff = client.get(f"/api/diffs/{diff_id}").json()
    assert diff["review_status"] == "pending"
    assert len(client.get("/api/reviews").json()) == 0


def test_run_task_rejects_when_already_running(client, db):
    result = seed_demo(db)
    task_id = result["task_id"]
    from app.models import ReviewTask

    task = db.get(ReviewTask, task_id)
    task.status = "running"
    db.commit()
    r = client.post(f"/api/tasks/{task_id}/run")
    assert r.status_code == 400


def test_retry_state_cleanup_removes_stale_logs_diffs_and_reviews(db):
    from app.api.routes import _clear_retry_state
    from app.models import Difference, PipelineRunLog, ReviewLog, ReviewTask

    g = Document(document_name="G", unit_name="集团", document_level="group", parse_status="parsed", raw_text="集团制度文本")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="子公司制度文本")
    db.add_all([g, s])
    db.flush()
    task = ReviewTask(
        task_name="重跑清理任务",
        group_document_id=g.id,
        subsidiary_document_id=s.id,
        status="reviewing",
        current_step=6,
        pipeline_error="旧错误",
        report_summary="旧报告",
    )
    db.add(task)
    db.flush()
    diff = Difference(task_id=task.id, diff_type="缺失", risk_level="高", summary="旧差异")
    db.add(diff)
    db.flush()
    db.add(ReviewLog(task_id=task.id, difference_id=diff.id, action="confirmed", comment="旧复核"))
    db.add(PipelineRunLog(task_id=task.id, step=4, agent_name="CoreAnalyser", status="completed", message="旧日志"))
    db.commit()

    _clear_retry_state(db, task, from_step=1)
    db.commit()

    assert db.query(Difference).filter(Difference.task_id == task.id).count() == 0
    assert db.query(ReviewLog).filter(ReviewLog.task_id == task.id).count() == 0
    assert db.query(PipelineRunLog).filter(PipelineRunLog.task_id == task.id).count() == 0
    assert task.pipeline_error is None
    assert task.report_summary is None
    assert task.current_step == 0


def test_retry_from_later_step_preserves_completed_checkpoint_logs(db):
    from app.api.routes import _clear_retry_state
    from app.models import PipelineRunLog, ReviewTask

    g = Document(document_name="G", unit_name="集团", document_level="group", parse_status="parsed", raw_text="集团制度")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="子公司制度")
    db.add_all([g, s])
    db.flush()
    task = ReviewTask(task_name="断点续跑", group_document_id=g.id, subsidiary_document_id=s.id, current_step=5)
    db.add(task)
    db.flush()
    db.add_all(
        [
            PipelineRunLog(task_id=task.id, step=1, agent_name="StructureEngine", status="completed", message="解析完成", output_json='{"ok":true}'),
            PipelineRunLog(task_id=task.id, step=4, agent_name="CoreAnalyser", status="completed", message="差异完成", output_json='{"count":1}'),
            PipelineRunLog(task_id=task.id, step=5, agent_name="EvidenceRules", status="failed", message="超时"),
        ]
    )
    db.commit()

    _clear_retry_state(db, task, from_step=5)
    db.commit()

    logs = db.query(PipelineRunLog).filter(PipelineRunLog.task_id == task.id).order_by(PipelineRunLog.step).all()
    assert [log.step for log in logs] == [1, 4]
    assert task.current_step == 4


def test_document_preview(client, db):
    result = seed_demo(db)
    r = client.get(f"/api/documents/{result['group_document_id']}/preview")
    assert r.status_code == 200
    body = r.json()
    assert "text_content" in body
    assert len(body["text_content"]) > 0


def test_create_task(client, db):
    g = Document(document_name="G", unit_name="集团", document_level="group", parse_status="parsed", raw_text="集团制度文本")
    s = Document(document_name="S", unit_name="子公司", document_level="subsidiary", parse_status="parsed", raw_text="子公司制度文本")
    db.add(g)
    db.add(s)
    db.commit()
    db.refresh(g)
    db.refresh(s)
    r = client.post(
        "/api/tasks",
        json={
            "task_name": "测试任务",
            "group_document_id": g.id,
            "subsidiary_document_id": s.id,
        },
    )
    assert r.status_code == 200
    assert r.json()["task_name"] == "测试任务"


def test_single_document_audit_finds_design_defects(client, db):
    doc = Document(
        document_name="简略车辆管理办法",
        unit_name="测试公司",
        document_level="subsidiary",
        business_domain="车辆管理",
        parse_status="parsed",
        raw_text="第一条 本办法用于车辆管理。车辆使用人员应妥善使用车辆。",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    r = client.post(
        "/api/single-audits/run",
        json={"document_id": doc.id, "task_name": "单制度设计检查测试", "business_domain": "车辆管理"},
    )
    assert r.status_code == 200
    task = r.json()
    assert task["status"] == "running"
    assert task["group_document_id"] == doc.id
    assert task["subsidiary_document_id"] == doc.id

    # 单制度体检由后台线程执行；轮询任务终态，避免把旧的同步行为写进测试。
    deadline = time.monotonic() + 5
    while task["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
        task = client.get(f"/api/tasks/{task['id']}").json()

    assert task["status"] == "reviewing"
    assert "其中高风险 0 项" not in task["report_summary"]

    rows = client.get(f"/api/tasks/{task['id']}/diffs").json()
    design_rows = [row for row in rows if row["diff_type"] == "设计缺陷"]
    control_missing_rows = [row for row in rows if row["diff_type"] == "控制缺失"]
    topics = {row["control_topic"] for row in design_rows}
    assert "职责分工与归口管理" in topics
    assert "监督检查与整改闭环" in topics
    assert all(row["group_location"] == "制度设计检查规则" for row in design_rows)
    assert control_missing_rows
    assert all(row["group_location"].startswith("标准控制点库/VEH-") for row in control_missing_rows)

    detail = client.get(f"/api/diffs/{design_rows[0]['id']}").json()
    assert "第一条 本办法用于车辆管理" in detail["subsidiary_clause_text"]
    assert detail["single_document_audit"] is True


def test_builtin_standard_controls_are_persisted_and_queryable(client, db):
    rows = client.get("/api/standard-controls").json()

    assert len(rows) == 422
    assert len({row["business_domain"] for row in rows}) == 19
    assert {row["business_domain"] for row in rows} >= {"用车管理", "采购", "资产", "担保业务"}
    assert all(not row["standard_code"].startswith("BUILTIN-") for row in rows)
    assert all(row["is_active"] is True for row in rows)

    procurement = client.get("/api/standard-controls?business_domain=采购").json()
    assert len(procurement) == 22
    assert {row["control_topic"] for row in procurement} >= {"供应商准入评估制度", "采购方式分级选择"}

    vehicles = client.get("/api/standard-controls?business_domain=用车管理").json()
    assert len(vehicles) == 16
    assert {row["standard_code"] for row in vehicles} >= {"VEH-001", "VEH-016"}


def test_delete_task(client, db):
    result = seed_demo(db)
    task_id = result["task_id"]
    r = client.delete(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    assert client.get(f"/api/tasks/{task_id}").status_code == 404
    dash = client.get("/api/dashboard").json()
    assert dash["total_tasks"] == 0


def test_delete_document_blocked_when_referenced(client, db):
    result = seed_demo(db)
    r = client.delete(f"/api/documents/{result['group_document_id']}")
    assert r.status_code == 400


def test_delete_document_after_task_removed(client, db):
    result = seed_demo(db)
    client.delete(f"/api/tasks/{result['task_id']}")
    r = client.delete(f"/api/documents/{result['group_document_id']}")
    assert r.status_code == 200
    assert client.get(f"/api/documents/{result['group_document_id']}/preview").status_code == 404
