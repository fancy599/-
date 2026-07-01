"""制度正文清洗：PDF 页码、孤立数字行、明显 OCR 噪声等。"""
import re

_PAGE_MARKER = re.compile(r"\[第\s*(\d+)\s*页\]", re.IGNORECASE)
_PAGE_LINE = re.compile(r"^第\s*\d+\s*页")
_DIGIT_ONLY = re.compile(r"^\d{1,4}$")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_INLINE_UPPER_OCR = re.compile(
    r"((?:第[一二三四五六七八九十百千万零〇两\d]+条|第[一二三四五六七八九十百千万零〇两\d]+章))"
    r"\s+[A-Z][A-Z0-9\s\"'`´.,;:!?()（）/\\|\-]{10,}"
)
_UPPER_OCR_LINE = re.compile(r"^[A-Z0-9\s\"'`´.,;:!?()（）/\\|\-]{14,}$")


def _strip_ocr_noise(line: str) -> str:
    line = _INLINE_UPPER_OCR.sub(r"\1", line).strip()
    cjk_count = len(_CJK.findall(line))
    if cjk_count == 0 and _UPPER_OCR_LINE.fullmatch(line):
        ascii_letters = len(re.findall(r"[A-Za-z]", line))
        if ascii_letters >= 10:
            return ""
    return line


def clean_page_body(text: str) -> str:
    lines: list[str] = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        if _PAGE_MARKER.fullmatch(ln) or _PAGE_LINE.match(ln):
            continue
        if _DIGIT_ONLY.match(ln):
            continue
        ln = _PAGE_MARKER.sub("", ln).strip()
        ln = _strip_ocr_noise(ln)
        if not ln or _DIGIT_ONLY.match(ln):
            continue
        lines.append(ln)
    return "\n".join(lines)


def normalize_extracted_text(text: str) -> str:
    """上传解析后的全文清洗。"""
    if not text:
        return ""
    t = text.replace("\r\n", "\n")
    t = _PAGE_MARKER.sub("\n\n", t)
    blocks = [clean_page_body(b) for b in re.split(r"\n{2,}", t)]
    blocks = [b for b in blocks if b and len(b) >= 8]
    if blocks:
        return "\n\n".join(blocks)
    return clean_page_body(t)


def cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = len(_CJK.findall(text))
    return cjk / max(len(text), 1)


def is_low_quality_clause(text: str) -> bool:
    """页码碎片、几乎无汉字的条款正文。"""
    if not text or len(text.strip()) < 20:
        return True
    t = text.strip()
    markers = len(_PAGE_MARKER.findall(t))
    if markers >= 2:
        return True
    if markers >= 1 and cjk_ratio(t) < 0.08:
        return True
    digit_lines = sum(1 for ln in t.split("\n") if _DIGIT_ONLY.match(ln.strip()))
    if digit_lines >= 3 and cjk_ratio(t) < 0.15:
        return True
    if cjk_ratio(t) < 0.05 and len(t) > 30:
        return True
    return False


def extract_readable_excerpt(text: str, hint: str = "", max_len: int = 700) -> str:
    """从 PDF 碎片中提取可读的汉字段落用于展示。"""
    if not text:
        return ""
    text = normalize_extracted_text(text)
    if not is_low_quality_clause(text) and len(text) <= max_len:
        return text.strip()

    lines: list[str] = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        ln = _PAGE_MARKER.sub("", ln).strip()
        ln = _strip_ocr_noise(ln)
        if len(_CJK.findall(ln)) < 6:
            continue
        if _DIGIT_ONLY.match(ln):
            continue
        lines.append(ln)

    body = "\n".join(lines)
    if not body:
        body = "".join(_CJK.findall(text))
        if len(body) < 20:
            return ""

    if hint and len(hint) >= 4:
        idx = body.find(hint[: min(24, len(hint))])
        if idx >= 0:
            start = max(0, idx - 120)
            end = min(len(body), idx + max_len - 120)
            snippet = body[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(body):
                snippet += "..."
            return snippet[:max_len]
        # 提供了定位线索却未在正文中命中：不再用“制度/管理”等高频词强行定位，
        # 也不回退到正文开头（否则会展示无关的“第一章 总则”等），返回空让上层
        # 改用该差异的证据快照，保证高亮/原文片段与判断理由一致。
        return ""

    return body[:max_len] + ("..." if len(body) > max_len else "")
