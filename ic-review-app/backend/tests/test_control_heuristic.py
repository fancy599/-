from app.services.control_heuristic import extract_control_points_local


def test_control_extractor_skips_purpose_scope_and_principle_clauses():
    clauses = [
        {
            "clause_text": "第一条 为建立健全固定资产管理机制，降低成本，使固定资产管理制度化、规范化，特制定本办法。"
        },
        {"clause_text": "第二条 本办法适用于集团固定资产的采购、使用与日常管理以及处置等环节。"},
        {"clause_text": "第二十三条 坚持厉行节约，提高效率，以公务交通成本节支情况作为评价标准。"},
    ]

    assert extract_control_points_local(clauses) == []


def test_control_extractor_keeps_actionable_responsibility_clause():
    clauses = [
        {"clause_text": "行政办公室负责固定资产的采购流程管理及具体操作。"},
        {"clause_text": "财务管理部负责采购支出控制审核。"},
    ]

    cps = extract_control_points_local(clauses)
    assert [cp["control_topic"] for cp in cps] == ["固定资产采购", "采购审批权限"]
    assert cps[0]["subject_role"] == "行政办公室"


def test_asset_impairment_is_not_misclassified_as_fixed_asset_management():
    standards = [
        {
            "business_domain": "资产",
            "control_topic": "固定资产保管调拨",
            "key_requirement": "固定资产使用部门应负责固定资产日常管理。",
        },
        {
            "business_domain": "资产",
            "control_topic": "资产减值准备核销",
            "key_requirement": "资产减值准备核销应履行审批。",
        },
    ]
    clauses = [
        {"clause_text": "企业核销资产减值准备必须经董事会审议批准，并形成书面核准意见。"},
        {"clause_text": "企业应当在资产负债表日判断资产是否存在减值迹象。"},
        {"clause_text": "固定资产可收回金额低于账面价值的，应当计提固定资产减值准备。"},
    ]

    cps = extract_control_points_local(clauses, standard_cps=standards)

    assert [cp["control_topic"] for cp in cps] == [
        "资产减值准备核销审批",
        "资产减值迹象识别",
        "固定资产减值测试",
    ]
