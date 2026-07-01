import re
import uuid
from pathlib import Path

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_RAW_TEXT_CHARS = 2_000_000


def safe_storage_name(original: str | None, suffix: str) -> str:
    """避免中文/特殊字符路径导致 Windows 写入失败。"""
    ext = suffix if suffix.startswith(".") else f".{suffix}"
    if ext.lower() not in (".txt", ".doc", ".docx", ".pdf"):
        ext = ".bin"
    return f"{uuid.uuid4().hex}{ext}"


def parse_api_error_detail(detail) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(x) for x in item.get("loc", []))
                msg = item.get("msg", "")
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "; ".join(parts) if parts else "请求参数错误"
    return str(detail)
