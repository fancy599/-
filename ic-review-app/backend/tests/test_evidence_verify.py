from app.services.evidence_verify import excerpt_in_clause, verify_single_draft


def test_excerpt_in_clause():
    assert excerpt_in_clause("超过200万元", "第十二条 超过200万元应报批")


def test_verify_ok():
    clauses_g = [{"id": 1, "clause_text": "第十条 钥匙专人保管", "location_label": "第10条"}]
    clauses_s = [{"id": 2, "clause_text": "第八条 无钥匙保管要求", "location_label": "第8条"}]
    draft = {
        "pair": {"group_clause_id": 1, "subsidiary_clause_id": 2},
        "diff_type": "缺失",
        "group_excerpt": "钥匙专人保管",
        "subsidiary_excerpt": "无钥匙",
        "group_location": "",
        "subsidiary_location": "",
    }
    r = verify_single_draft(draft, clauses_g, clauses_s)
    assert r["evidence_ok"] is True
    assert r["group_location"] == "第10条"


def test_verify_bad_clause_id():
    draft = {
        "pair": {"group_clause_id": 99, "subsidiary_clause_id": 2},
        "diff_type": "冲突",
        "group_excerpt": "x",
        "subsidiary_excerpt": "",
    }
    r = verify_single_draft(draft, [], [{"id": 2, "clause_text": "子公司条款"}])
    assert r["evidence_ok"] is False
