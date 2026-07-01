from io import BytesIO

from docx import Document as DocxDocument


def test_upload_docx_unicode_filename(client, tmp_path):
    docx = tmp_path / "test.docx"
    d = DocxDocument()
    d.add_paragraph("第十二条 测试条款内容超过四十个字以便通过校验规则。")
    d.save(docx)

    with docx.open("rb") as f:
        content = f.read()

    files = {"file": ("22、金外滩集团办法.docx", BytesIO(content), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    data = {
        "document_name": "金外滩集团公务用车管理办法",
        "unit_name": "集团总部",
        "document_level": "group",
        "business_domain": "采购",
        "version": "",
    }
    r = client.post("/api/documents/upload", files=files, data=data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["parse_status"] == "parsed"
