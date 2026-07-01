from unittest.mock import patch

from app.api.routes import _govern_exemptions_after_group_upgrade
from app.models import Difference, Document, ExemptionRule, ReviewTask
from app.services.dependency_scope import cache_dependency_scope, global_context_hash


def test_global_definition_change_invalidates_dependency_hash():
    before = [{"chapter_title": "第一章 总则", "clause_no": "第一条", "clause_text": "重大项目是指5000万元以上。"}]
    after = [{"chapter_title": "第一章 总则", "clause_no": "第一条", "clause_text": "重大项目是指3000万元以上。"}]
    unchanged_downstream = [{"chapter_title": "第三章 采购执行", "clause_no": "第十条", "clause_text": "重大项目需履行审批。"}]

    assert global_context_hash(before, unchanged_downstream) != global_context_hash(after, unchanged_downstream)
    assert cache_dependency_scope(before, unchanged_downstream) == "global_definition_chain"


def test_delta_audit_scans_new_material_for_cross_scope_pollution(client, db):
    from app.seed import seed_demo

    result = seed_demo(db)
    target = client.get(f"/api/tasks/{result['task_id']}/diffs").json()[0]
    created = client.post(
        f"/api/diffs/{target['id']}/supplements",
        json={"assignee": "经办人", "requirement": "补充配套制度"},
    ).json()
    submitted = client.post(
        f"/api/supplements/{created['id']}/submit",
        json={"submitted_text": f"{target['control_topic']}已经覆盖，但黑名单由采购部经理一人决定。"},
    )

    assert submitted.status_code == 200
    body = submitted.json()
    assert "二次污染审查命中" in body["pollution_scan_result"]
    assert body["derived_difference_ids"]
    derived = client.get(f"/api/tasks/{result['task_id']}/diffs").json()
    assert any(x["control_topic"] == "重大事项单人决策风险" for x in derived)


def test_base_upgrade_suspends_changed_exemption(db):
    old = Document(
        document_name="集团采购办法2024",
        unit_name="集团",
        document_level="group",
        business_domain="采购",
        version="2024",
        raw_text="供应商黑名单可由采购部门审批。",
    )
    sub = Document(document_name="子公司办法", unit_name="子公司", document_level="subsidiary", raw_text="子公司条款")
    db.add_all([old, sub])
    db.flush()
    task = ReviewTask(task_name="旧任务", group_document_id=old.id, subsidiary_document_id=sub.id)
    db.add(task)
    db.flush()
    diff = Difference(task_id=task.id, diff_type="冲突", risk_level="高", control_topic="黑名单审批")
    db.add(diff)
    db.flush()
    exemption = ExemptionRule(
        difference_id=diff.id,
        task_id=task.id,
        control_topic="黑名单审批",
        status="active",
        base_document_id=old.id,
        base_version="2024",
        base_control_fingerprint="供应商黑名单可由采购部门审批。",
    )
    db.add(exemption)
    new = Document(
        document_name="集团采购办法2026",
        unit_name="集团",
        document_level="group",
        business_domain="采购",
        version="2026",
        raw_text="供应商黑名单必须经党委会前置研究并由董事会审批。",
    )
    db.add(new)
    db.flush()

    _govern_exemptions_after_group_upgrade(db, new)

    assert exemption.status == "suspended_by_base_upgrade"
    assert "需双人重新审计" in exemption.governance_note


def test_pdf_complex_table_warning_is_exposed(client):
    with patch("app.api.routes.extract_text_from_file", return_value="采购审批制度正文"), patch(
        "app.api.routes.detect_pdf_complex_table_pages", return_value=[3, 4]
    ):
        response = client.post(
            "/api/documents/upload",
            data={
                "document_name": "权责矩阵",
                "unit_name": "集团",
                "document_level": "group",
                "business_domain": "采购",
                "version": "2026",
            },
            files={"file": ("matrix.pdf", b"fake pdf", "application/pdf")},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["table_review_required"] is True
    assert body["complex_table_pages"] == "3,4"
    assert "人工核验" in body["degradation_notes"]
