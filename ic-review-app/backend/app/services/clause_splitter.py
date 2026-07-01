"""Deterministic Markdown/clause splitter used by the Hybrid Pipeline."""
import re

from app.services.text_normalize import extract_readable_excerpt, normalize_extracted_text

_CLAUSE_START = re.compile(r"第[一二三四五六七八九十百零\d]+条")
_CHAPTER = re.compile(r"第[一二三四五六七八九十百零\d]+章[^\n]{0,30}")
_TOP_HEADING_LINE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零\d]+[章节条][^\n]{0,40}"
    r"|[一二三四五六七八九十百]+、"
    r")",
    re.MULTILINE,
)
_HEADING_LINE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零\d]+[章节条][^\n]{0,40}"
    r"|[一二三四五六七八九十百]+、"
    r"|[（(][一二三四五六七八九十百\d]+[）)]"
    r"|\d+[、．.]\s*\S"
    r")",
    re.MULTILINE,
)
_MIN_CLAUSE_LEN = 40
_MAX_CLAUSE_CHARS = 2500


def split_clauses_local(raw_text: str, max_clauses: int = 300) -> list[dict]:
    text = normalize_extracted_text(raw_text.replace("\r\n", "\n").strip())
    if not text:
        return []

    matches = list(_CLAUSE_START.finditer(text))
    if matches:
        return _split_by_tiao(text, matches, max_clauses)

    by_heading = _split_by_heading_lines(text, max_clauses)
    if len(by_heading) >= 2:
        return by_heading

    by_para = _split_by_paragraphs(text, max_clauses)
    if len(by_para) >= 2:
        return by_para

    return _split_dense_text(text, max_clauses)


def _split_by_tiao(text: str, matches: list[re.Match], max_clauses: int) -> list[dict]:
    result = []
    current_chapter = ""
    for i, m in enumerate(matches[:max_clauses]):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        clause_no = m.group(0)
        prefix = text[:start]
        chs = _CHAPTER.findall(prefix)
        if chs:
            current_chapter = chs[-1]
        result.append({
            "chapter_title": current_chapter,
            "clause_no": clause_no,
            "clause_text": body[:_MAX_CLAUSE_CHARS],
            "page_no": None,
            "location_label": f"{current_chapter} {clause_no}".strip(),
        })
    return result


def _split_by_heading_lines(text: str, max_clauses: int) -> list[dict]:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return []

    sections: list[tuple[str, list[str]]] = []
    heading = ""
    buf: list[str] = []

    def flush() -> None:
        nonlocal buf, heading
        body = "\n".join(buf).strip()
        if not body:
            buf = []
            return
        if sections and len(body) < _MIN_CLAUSE_LEN:
            prev_h, prev_body = sections[-1]
            sections[-1] = (prev_h, f"{prev_body}\n{body}")
        else:
            sections.append((heading, body))
        buf = []

    for line in lines:
        if _TOP_HEADING_LINE.match(line) and buf:
            flush()
            heading = line[:80]
            buf = [line]
        elif _TOP_HEADING_LINE.match(line) and not buf:
            heading = line[:80]
            buf = [line]
        else:
            buf.append(line)
    flush()

    if len(sections) < 2:
        return []

    return [
        {
            "chapter_title": h.split(" ")[0] if h else "",
            "clause_no": h or f"段落{i + 1}",
            "clause_text": body[:_MAX_CLAUSE_CHARS],
            "page_no": None,
            "location_label": (h or f"段落{i + 1}")[:80],
        }
        for i, (h, body) in enumerate(sections[:max_clauses])
    ]


def _split_by_paragraphs(text: str, max_clauses: int) -> list[dict]:
    blocks: list[str] = []
    for sep in (r"\n{2,}", r"\n"):
        parts = [p.strip() for p in re.split(sep, text) if len(p.strip()) >= _MIN_CLAUSE_LEN]
        if len(parts) >= 2:
            blocks = parts
            break
    if len(blocks) < 2:
        return []

    return [
        {
            "chapter_title": "",
            "clause_no": f"段落{i + 1}",
            "clause_text": b[:_MAX_CLAUSE_CHARS],
            "page_no": None,
            "location_label": _paragraph_label(b, i),
        }
        for i, b in enumerate(blocks[:max_clauses])
    ]


def _paragraph_label(body: str, index: int) -> str:
    first = body.split("\n", 1)[0].strip()
    if _HEADING_LINE.match(first):
        return first[:80]
    return f"段落{index + 1}"


def _split_dense_text(text: str, max_clauses: int) -> list[dict]:
    """无标题、无换行时的兜底：按句号分块。"""
    parts = re.split(r"(?<=[。；])\s*", text)
    chunks: list[str] = []
    buf = ""
    target = 500
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) > target and len(buf) >= _MIN_CLAUSE_LEN:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf}{p}" if buf else p
    if buf and len(buf) >= _MIN_CLAUSE_LEN:
        chunks.append(buf)
    if not chunks:
        readable = extract_readable_excerpt(text, max_len=_MAX_CLAUSE_CHARS)
        chunks = [readable] if readable else [text[:_MAX_CLAUSE_CHARS]]

    return [
        {
            "chapter_title": "",
            "clause_no": f"片段{i + 1}",
            "clause_text": c[:_MAX_CLAUSE_CHARS],
            "page_no": None,
            "location_label": _fragment_label(c, i),
        }
        for i, c in enumerate(chunks[:max_clauses])
        if c and len(c.strip()) >= 20
    ]


def _fragment_label(body: str, index: int) -> str:
    m = re.search(r"第[一二三四五六七八九十百零\d]+条", body)
    if m:
        return m.group(0)
    for ln in body.split("\n"):
        ln = ln.strip()
        if len(ln) >= 8 and re.search(r"[\u4e00-\u9fff]", ln):
            return ln[:40]
    return f"片段{index + 1}"
