from app.pipeline.orchestrator import _build_missing_summary


def test_missing_summary_describes_semantic_coverage_not_article_pairing():
    class ClauseLike:
        clause_no = "第二十三条"
        chapter_title = "第七章纪律问责管理"

    summary, reason, suggestion = _build_missing_summary(ClauseLike(), "纪律问责")

    assert "覆盖不足或待确认" in summary
    assert "不是条款编号逐条对应" in reason
    assert "对应的控制点" not in reason
    assert "责任主体" in suggestion
