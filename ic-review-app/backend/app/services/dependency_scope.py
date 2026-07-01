import hashlib
import json
import re
from typing import Any


GLOBAL_SECTION_RE = re.compile(r"(总则|术语|定义|适用范围|基本原则|通用规定)")


def global_context_hash(*clause_sets: list[dict[str, Any]]) -> str:
    """Hash global definitions that invalidate every dependent chapter cache."""
    global_clauses: list[dict[str, str]] = []
    for clauses in clause_sets:
        for clause in clauses:
            heading = f"{clause.get('chapter_title', '')} {clause.get('clause_no', '')}"
            text = clause.get("clause_text", "") or ""
            if GLOBAL_SECTION_RE.search(heading) or GLOBAL_SECTION_RE.search(text[:120]):
                global_clauses.append(
                    {
                        "heading": heading.strip(),
                        "text": text,
                    }
                )
    payload = json.dumps(global_clauses, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cache_dependency_scope(*clause_sets: list[dict[str, Any]]) -> str:
    return "global_definition_chain" if any(
        GLOBAL_SECTION_RE.search(f"{c.get('chapter_title', '')} {c.get('clause_text', '')[:120]}")
        for clauses in clause_sets
        for c in clauses
    ) else "document"
