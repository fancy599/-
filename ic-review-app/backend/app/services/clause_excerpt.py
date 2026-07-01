"""从长条款中提取与差异相关的展示片段。"""
import re

from app.services.text_normalize import extract_readable_excerpt, is_low_quality_clause

_DISPLAY_MAX = 300


def pick_clause_excerpt(
    clause_text: str,
    *,
    stored_excerpt: str = "",
    hint: str = "",
    topic: str = "",
    max_len: int = _DISPLAY_MAX,
) -> tuple[str, bool]:
    """返回 (展示文本, 是否为摘要而非全文)。"""
    hint_combined = " ".join(x for x in (stored_excerpt, hint, topic) if x).strip()

    if is_low_quality_clause(clause_text):
        readable = extract_readable_excerpt(clause_text, hint=hint_combined, max_len=max_len)
        if readable:
            return readable, True
        if stored_excerpt and not is_low_quality_clause(stored_excerpt):
            return stored_excerpt[:max_len], True
        return "（未能从 PDF/文档中定位到可读条款正文，请在制度库中预览原文）", False

    if not clause_text:
        return stored_excerpt or "", False
    if len(clause_text) <= max_len:
        return clause_text, False

    needles: list[str] = []
    for src in (stored_excerpt, hint, topic):
        s = (src or "").strip()
        if len(s) >= 4:
            needles.append(s)
    for m in re.finditer(r"\d+\s*万", clause_text):
        needles.append(m.group(0))

    for needle in needles:
        idx = clause_text.find(needle)
        if idx < 0 and len(needle) > 20:
            idx = clause_text.find(needle[:20])
        if idx >= 0:
            return _window(clause_text, idx, idx + max(len(needle), 40), max_len), True

    first = clause_text.split("\n", 1)[0].strip()
    if _HEADING_LINE.match(first):
        lines = clause_text.split("\n")
        buf = [lines[0]]
        total = len(lines[0])
        for ln in lines[1:]:
            if total + len(ln) + 1 > max_len:
                break
            buf.append(ln)
            total += len(ln) + 1
        chunk = "\n".join(buf)
        if len(chunk) < len(clause_text):
            chunk += "…"
        return chunk, True

    readable = extract_readable_excerpt(clause_text, hint=hint_combined, max_len=max_len)
    if readable:
        return readable, True
    return clause_text[:max_len] + "…", True


def _window(text: str, start: int, end: int, max_len: int) -> str:
    pad = max(0, (max_len - (end - start)) // 2)
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    if e - s > max_len:
        e = s + max_len

    # 尽量在句子/段落边界截断，避免从句子中间断开
    if s > 0:
        prev_text = text[max(0, s - 20):s]
        last_break = max(prev_text.rfind("\n"), prev_text.rfind("。"), prev_text.rfind("；"))
        if last_break != -1:
            s = s - 20 + last_break + 1

    if e < len(text):
        next_text = text[e:min(len(text), e + 20)]
        next_break = -1
        for ch in ("\n", "。", "；"):
            pos = next_text.find(ch)
            if pos != -1 and (next_break == -1 or pos < next_break):
                next_break = pos
        if next_break != -1:
            e = e + next_break + 1

    out = text[s:e].strip()
    if s > 0:
        out = "…" + out
    if e < len(text):
        out = out + "…"
    return out


_HEADING_LINE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百零\d]+[章节条]"
    r"|[一二三四五六七八九十百]+、"
    r"|[（(][一二三四五六七八九十百\d]+[）)]"
    r"|\d+[、．.]"
    r")",
    re.MULTILINE,
)
