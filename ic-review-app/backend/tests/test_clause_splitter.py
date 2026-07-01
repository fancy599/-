from app.services.clause_excerpt import pick_clause_excerpt
from app.services.clause_splitter import split_clauses_local


def test_split_by_tiao():
    text = "\u7b2c\u56db\u7ae0 \u91c7\u8d2d\n\u7b2c\u5341\u4e8c\u6761 \u8d85\u8fc7200\u4e07\u5143\u5e94\u62a5\u6279\u3002\n\u7b2c\u5341\u4e09\u6761 \u7d27\u6025\u91c7\u8d2d\u987b\u5907\u6848\u3002"
    items = split_clauses_local(text)
    assert len(items) >= 2
    assert "\u7b2c\u5341\u4e8c\u6761" in items[0]["clause_no"] or "\u7b2c\u5341\u4e8c\u6761" in items[0]["clause_text"]


def test_split_by_chinese_numbered_headings():
    text = (
        "\u4e00\u3001\u76ee\u6807\u8981\u6c42\n"
        "\u52a0\u5f3a\u96c6\u56e2\u91c7\u8d2d\u7edf\u4e00\u7ba1\u7406\u3002\n"
        "\u4e8c\u3001\u9002\u7528\u8303\u56f4\u548c\u57fa\u672c\u539f\u5219\n"
        "\uff08\u4e00\uff09\u9002\u7528\u8303\u56f4\n"
        "\u672c\u529e\u6cd5\u9002\u7528\u4e8e\u5168\u96c6\u56e2\u3002\n"
        "\uff08\u4e8c\uff09\u57fa\u672c\u539f\u5219\n"
        "\u575a\u6301\u516c\u5f00\u900f\u660e\u3002\n"
        "1\u3001\u575a\u6301\u521b\u65b0\u5236\u5ea6\n"
        "\u63a8\u8fdb\u6570\u5b57\u5316\u91c7\u8d2d\u3002"
    )
    items = split_clauses_local(text)
    assert len(items) >= 2
    assert any("\u4e00\u3001" in i["location_label"] or "\u76ee\u6807\u8981\u6c42" in i["clause_text"] for i in items)
    assert all(len(i["clause_text"]) < 3000 for i in items)


def test_split_single_newline_docx_style():
    text = (
        "\u524d\u8a00\u8bf4\u660e\n"
        "\u4e00\u3001\u603b\u5219\n"
        "\u7b2c\u4e00\u6761\u5185\u5bb9\u8f83\u957f\u9700\u8981\u8d85\u8fc7\u56db\u5341\u4e2a\u5b57\u7b26\u624d\u80fd\u88ab\u8bc6\u522b\u4e3a\u72ec\u7acb\u6bb5\u843d\u5757\u3002\n"
        "\u4e8c\u3001\u7ec6\u5219\n"
        "\u7b2c\u4e8c\u6761\u540c\u6837\u8981\u6709\u8db3\u591f\u957f\u5ea6\u624d\u80fd\u72ec\u7acb\u6210\u6bb5\u4e0d\u88ab\u5408\u5e76\u6389\u3002"
    )
    items = split_clauses_local(text)
    assert len(items) >= 2


def test_pick_excerpt_from_long_clause():
    long_text = "A" * 200 + "\u8d85\u8fc7500\u4e07\u5143\u987b\u62a5\u6279" + "B" * 1000
    excerpt, truncated = pick_clause_excerpt(long_text, hint="\u8d85\u8fc7500\u4e07\u5143\u987b\u62a5\u6279")
    assert truncated
    assert "500\u4e07" in excerpt
    assert len(excerpt) < len(long_text)
