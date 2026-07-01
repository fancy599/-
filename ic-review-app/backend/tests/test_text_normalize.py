from app.services.text_normalize import (
    extract_readable_excerpt,
    is_low_quality_clause,
    normalize_extracted_text,
)


def test_normalize_pdf_page_markers():
    raw = "[第1页]\n144\n第十条 钥匙应由专人保管。\n\n[第2页]\n145\n第十一条 测试内容。"
    norm = normalize_extracted_text(raw)
    assert "144" not in norm.split() or "144" not in norm
    assert "第十条" in norm


def test_is_low_quality_page_junk():
    junk = "[第1页] 144 [第2页] 145 [第3页] 146"
    assert is_low_quality_clause(junk)


def test_extract_readable_from_junk():
    raw = "[第1页]\n144\n车辆钥匙应由专人保管，使用人与保管人不得为同一人。\n[第2页]\n145"
    out = extract_readable_excerpt(raw, hint="钥匙保管")
    assert "钥匙" in out
    assert "[第1页]" not in out


def test_normalize_removes_uppercase_ocr_noise_after_article_heading():
    raw = "第一条 HELE LEER EMP ARAL PER AA” )\n固定资产管理机制，降低成本，使固定资产管理制度化、规范化。"
    out = normalize_extracted_text(raw)
    assert "HELE" not in out
    assert "第一条" in out
    assert "固定资产管理" in out
