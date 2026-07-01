from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.baidu_doc_parser import parse_pdf  # noqa: E402
from scripts.build_regulatory_corpus import MAX_TEXT_CHARS, clean_text, paragraphs  # noqa: E402


CORPUS_PATH = BACKEND_ROOT / "app" / "data" / "regulatory_corpus" / "regulatory_corpus.json"
CACHE_DIR = BACKEND_ROOT / "app" / "data" / "regulatory_corpus" / "ocr_cache"

PRIORITY_KEYWORDS = [
    "\u5185\u63a7\u4f53\u7cfb\u5efa\u8bbe",
    "\u8d22\u52a1\u603b\u76d1\u7ba1\u7406\u5236\u5ea6",
    "\u8fdd\u89c4\u7ecf\u8425\u6295\u8d44\u8d23\u4efb\u8ffd\u7a76",
    "\u5c65\u804c\u5f85\u9047\u548c\u4e1a\u52a1\u652f\u51fa",
    "\u6295\u8d44\u76d1\u7763\u7ba1\u7406\u529e\u6cd5",
    "\u5916\u90e8\u8463\u4e8b\u7ba1\u7406\u529e\u6cd5",
    "\u5916\u6d3e\u76d1\u4e8b\u4f1a\u4e3b\u5e2d\u7ba1\u7406",
    "\u5ba1\u8ba1\u4e2d\u4ecb\u673a\u6784",
    "\u878d\u8d44\u62c5\u4fdd\u53ca\u8d44\u91d1\u51fa\u501f",
    "\u5408\u89c4\u7ba1\u7406\u529e\u6cd5",
]


def cache_path(relative_path: str) -> Path:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:16]
    safe_name = re.sub(r"[^\w.-]+", "_", Path(relative_path).stem, flags=re.UNICODE).strip("_")
    return CACHE_DIR / f"{safe_name[:60]}_{digest}.txt"


def should_ocr(record: dict[str, Any], keywords: list[str], all_zero: bool) -> bool:
    if record.get("suffix") != ".pdf":
        return False
    if int(record.get("text_len") or 0) > 0:
        return False
    if all_zero:
        return True
    haystack = f"{record.get('relative_path', '')} {record.get('file_name', '')}"
    return any(keyword in haystack for keyword in keywords)


def merge_ocr(record: dict[str, Any], source_root: Path) -> dict[str, Any]:
    relative_path = str(record["relative_path"])
    source_path = source_root / relative_path
    out_path = cache_path(relative_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists():
        text = out_path.read_text(encoding="utf-8")
        from_cache = True
    else:
        text = parse_pdf(str(source_path))
        out_path.write_text(text, encoding="utf-8")
        from_cache = False

    text = clean_text(text)[:MAX_TEXT_CHARS]
    paras = paragraphs(text)
    record.update(
        {
            "ok": True,
            "text_len": len(text),
            "paragraphs": paras,
            "title_guess": next((p for p in paras[:8] if len(p) <= 120), record.get("file_name")),
            "ocr_provider": "baidu_doc_parser",
            "ocr_cache_path": str(out_path),
            "ocr_from_cache": from_cache,
        }
    )
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-zero", action="store_true", help="OCR every zero-text PDF in the corpus.")
    parser.add_argument("--keyword", action="append", default=[], help="Additional filename keyword to OCR.")
    args = parser.parse_args()

    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    source_root = Path(payload["source_root"])
    keywords = PRIORITY_KEYWORDS + args.keyword

    updated = []
    failed = []
    skipped = 0
    for record in payload["records"]:
        if not should_ocr(record, keywords, args.all_zero):
            skipped += 1
            continue
        try:
            merge_ocr(record, source_root)
            updated.append(record["relative_path"])
            CORPUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            record["ocr_error"] = f"{type(exc).__name__}: {exc}"
            failed.append({"file": record["relative_path"], "error": record["ocr_error"]})
            CORPUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            continue

    CORPUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"updated": len(updated), "failed": len(failed), "skipped": skipped, "files": updated, "errors": failed},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
