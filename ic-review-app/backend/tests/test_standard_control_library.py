from app.models import StandardControlPoint
from app.services.standard_control_library import (
    builtin_standard_controls,
    infer_standard_domains,
    load_standard_controls,
    scope_standard_controls,
    seed_builtin_standard_controls,
)


def test_builtin_file_contains_full_control_library():
    rows = builtin_standard_controls()

    assert len(rows) == 422
    assert len({row["business_domain"] for row in rows}) == 19
    assert {row["standard_code"] for row in rows} >= {"ORG-001", "VEH-016", "OUT-012", "ENG-024"}
    assert sum(1 for row in rows if row["version"] == "V2026.1") >= 133
    assert len({(row["business_domain"], row["control_topic"]) for row in rows}) == len(rows)


def test_specific_document_name_scopes_controls_within_domain():
    rows = builtin_standard_controls()
    assets = [dict(row) for row in rows if row["business_domain"] == "资产"]
    impairment = scope_standard_controls(assets, "资产减值准备财务核销处理办法")
    fixed_assets = scope_standard_controls(assets, "固定资产管理办法")

    assert {row["standard_code"] for row in impairment} >= {"AST-027", "AST-038", "AST-040", "AST-042"}
    assert "AST-001" not in {row["standard_code"] for row in impairment}
    assert "AST-001" in {row["standard_code"] for row in fixed_assets}
    assert "AST-038" not in {row["standard_code"] for row in fixed_assets}

    procurement = [dict(row) for row in rows if row["business_domain"] == "采购"]
    suppliers = scope_standard_controls(procurement, "供应商准入与评价管理办法")
    assert {row["standard_code"] for row in suppliers} >= {"PUR-002", "PUR-005", "PUR-006", "PUR-007"}
    assert "PUR-014" not in {row["standard_code"] for row in suppliers}


def test_domain_inference_prefers_explicit_domain():
    assert infer_standard_domains("制度涉及付款和车辆维修", preferred_domain="车辆管理") == ["用车管理"]
    assert infer_standard_domains("公务用车使用管理办法") == ["用车管理"]
    assert infer_standard_domains("供应商准入与采购招标管理办法") == ["采购"]
    assert infer_standard_domains("", preferred_domain="投资产权") == ["资金活动"]
    assert infer_standard_domains("", preferred_domain="档案保密") == ["内部信息传递"]
    assert infer_standard_domains("", preferred_domain="审计风控") == ["组织架构"]


def test_seed_replaces_legacy_system_controls_and_loads_selected_domain(db):
    db.add(
        StandardControlPoint(
            standard_code="BUILTIN-车辆-01",
            business_domain="车辆",
            control_topic="旧控制点",
            standard_requirement="旧要求",
            tenant_id="system",
        )
    )
    db.commit()

    seed_builtin_standard_controls(db)
    controls = load_standard_controls(db, ["用车管理"], include_general=False)

    assert db.query(StandardControlPoint).count() == 422
    assert db.query(StandardControlPoint).filter_by(standard_code="BUILTIN-车辆-01").first() is None
    assert len(controls) == 16
    assert {item["standard_code"] for item in controls} >= {"VEH-001", "VEH-016"}
