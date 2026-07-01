from pathlib import Path

from app.services.parser import extract_text_from_file, split_text_to_chunks


def test_split_chunks():
    text = "a" * 25000
    chunks = split_text_to_chunks(text, max_chars=10000)
    assert len(chunks) == 3


def test_extract_txt(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("第十二条 采购审批规定", encoding="utf-8")
    assert "第十二条" in extract_text_from_file(str(f))
