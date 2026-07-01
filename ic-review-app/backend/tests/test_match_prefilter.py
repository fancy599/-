from app.services.match_prefilter import attach_clause_to_cps, cp_for_llm, prefilter_match_candidates


def test_attach_clause_text():
    clauses = [{"id": 1, "clause_text": "第十条 钥匙专人保管", "location_label": "第4章第10条", "clause_no": "第十条"}]
    cps = [{"clause_id": 1, "control_topic": "用车管理", "requirement": "保管"}]
    out = attach_clause_to_cps(cps, clauses)
    assert "钥匙" in out[0]["clause_text"]
    assert out[0]["location_label"] == "第4章第10条"


def test_prefilter_limits_pairs():
    group = [
        {"control_topic": "采购审批权限", "clause_text": "超过200万须集团审批", "requirement": ""},
        {"control_topic": "供应商准入", "clause_text": "供应商评审", "requirement": ""},
    ]
    sub = [
        {"control_topic": "采购审批权限", "clause_text": "500万以下总经理审批", "requirement": ""},
        {"control_topic": "供应商准入", "clause_text": "供应商准入流程", "requirement": ""},
        {"control_topic": "一般控制", "clause_text": "其他制度条款", "requirement": ""},
    ]
    cand = prefilter_match_candidates(group, sub, max_per_group=2, max_total=10)
    assert len(cand) <= 10
    assert all("group_index" in c and "sub_index" in c for c in cand)
    topics = {c["control_topic"] for c in cand}
    assert "采购审批权限" in topics or len(cand) >= 1


def test_prefilter_does_not_pair_by_sequence_when_no_semantic_candidate():
    group = [{"control_topic": "纪律问责", "clause_text": "违规应追责问责", "requirement": ""}]
    sub = [{"control_topic": "车辆集中管理", "clause_text": "公务用车统一调配", "requirement": ""}]

    assert prefilter_match_candidates(group, sub, max_per_group=2, max_total=10) == []


def test_cp_for_llm_includes_clause_text():
    payload = cp_for_llm({"control_topic": "t", "clause_text": "第十条 正文", "subject_role": "a"})
    assert "clause_text" in payload
    assert "第十条" in payload["clause_text"]
