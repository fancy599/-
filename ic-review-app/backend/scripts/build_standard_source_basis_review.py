from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
STANDARD_PATH = BACKEND_ROOT / "app" / "data" / "standard_controls.json"
CORPUS_PATH = BACKEND_ROOT / "app" / "data" / "regulatory_corpus" / "regulatory_corpus.json"
OUT_DIR = BACKEND_ROOT / "app" / "data" / "regulatory_corpus"
OUT_JSON = OUT_DIR / "standard_control_source_basis_review.json"
OUT_CSV = OUT_DIR / "standard_control_source_basis_review.csv"

VERIFIED_CODES = {
    "ORG-001",
    "ORG-002",
    "ORG-003",
    "ORG-004",
    "ORG-005",
    "ORG-006",
    "ORG-007",
    "ORG-008",
    "ORG-011",
    "ORG-012",
    "FUND-003",
    "FUND-006",
    "FINR-007",
    "CULT-003",
    "CULT-004",
    "CULT-005",
    "RD-003",
    "RD-004",
    "ORG-035",
}


STOP_TERMS = {
    "\u516c\u53f8",
    "\u4f01\u4e1a",
    "\u5236\u5ea6",
    "\u7ba1\u7406",
    "\u660e\u786e",
    "\u5e94\u5f53",
    "\u5e94\u6309",
    "\u5e94\u5efa",
    "\u5e94\u5236",
    "\u5e94\u786e",
    "\u5efa\u7acb",
    "\u5b8c\u5584",
    "\u76f8\u5173",
    "\u60c5\u51b5",
    "\u6d41\u7a0b",
    "\u5de5\u4f5c",
    "\u4e1a\u52a1",
    "\u90e8\u95e8",
    "\u5c97\u4f4d",
    "\u8d23\u4efb",
}

DOMAIN_HINTS = {
    "\u7ec4\u7ec7\u67b6\u6784": ["\u8463\u4e8b\u4f1a", "\u76d1\u4e8b\u4f1a", "\u7ecf\u7406\u5c42", "\u4e09\u91cd\u4e00\u5927", "\u516c\u53f8\u7ae0\u7a0b", "\u5916\u90e8\u8463\u4e8b"],
    "\u53d1\u5c55\u6218\u7565": ["\u6218\u7565", "\u4e3b\u4e1a", "\u89c4\u5212", "\u6295\u8d44\u65b9\u5411"],
    "\u4eba\u529b\u8d44\u6e90": ["\u85aa\u916c", "\u7ee9\u6548", "\u8003\u6838", "\u62db\u8058", "\u4efb\u514d", "\u57f9\u8bad"],
    "\u8d44\u91d1\u6d3b\u52a8": ["\u8d44\u91d1", "\u878d\u8d44", "\u62c5\u4fdd", "\u51fa\u501f", "\u53f8\u5e93", "\u94f6\u884c\u8d26\u6237"],
    "\u91c7\u8d2d": ["\u91c7\u8d2d", "\u62db\u6807", "\u6295\u6807", "\u4f9b\u5e94\u5546"],
    "\u8d44\u4ea7": ["\u8d44\u4ea7", "\u8bc4\u4f30", "\u5904\u7f6e", "\u4ea7\u6743", "\u6e05\u67e5"],
    "\u9500\u552e": ["\u9500\u552e", "\u5408\u540c", "\u5ba2\u6237", "\u6536\u5165", "\u5e94\u6536"],
    "\u5de5\u7a0b\u9879\u76ee": ["\u5de5\u7a0b", "\u9879\u76ee", "\u5efa\u8bbe", "\u7ae3\u5de5", "\u9a8c\u6536"],
    "\u62c5\u4fdd\u4e1a\u52a1": ["\u62c5\u4fdd", "\u878d\u8d44", "\u53cd\u62c5\u4fdd", "\u4ee3\u507f"],
    "\u4e1a\u52a1\u5916\u5305": ["\u5916\u5305", "\u670d\u52a1\u5546", "\u59d4\u6258"],
    "\u8d22\u52a1\u62a5\u544a": ["\u8d22\u52a1", "\u62a5\u544a", "\u4f1a\u8ba1", "\u51b3\u7b97", "\u8d22\u52a1\u603b\u76d1"],
    "\u5168\u9762\u9884\u7b97": ["\u9884\u7b97", "\u51b3\u7b97", "\u7f16\u5236", "\u6267\u884c"],
    "\u5408\u540c\u7ba1\u7406": ["\u5408\u540c", "\u5ba1\u6838", "\u5c65\u884c", "\u5370\u7ae0"],
    "\u5185\u90e8\u4fe1\u606f\u4f20\u9012": ["\u4fe1\u606f", "\u6863\u6848", "\u6587\u4e66", "\u7535\u5b50\u6587\u4ef6", "\u4fdd\u5bc6"],
    "\u4fe1\u606f\u7cfb\u7edf": ["\u4fe1\u606f\u7cfb\u7edf", "\u6570\u636e", "\u7f51\u7edc", "\u6743\u9650", "\u53f8\u5e93"],
    "\u5185\u90e8\u76d1\u7763": ["\u5ba1\u8ba1", "\u76d1\u7763", "\u6574\u6539", "\u8ffd\u8d23", "\u8bc4\u4ef7"],
}

DOMAIN_FILE_HINTS = {
    "\u7ec4\u7ec7\u67b6\u6784": ["\u7b2c\u4e00\u7bc7 \u7ec4\u7ec7\u6cbb\u7406", "\u7ae0\u7a0b\u6307\u5f15", "\u515a\u5efa\u5de5\u4f5c", "\u5916\u90e8\u8463\u4e8b", "\u5916\u6d3e\u76d1\u4e8b"],
    "\u53d1\u5c55\u6218\u7565": ["\u7b2c\u4e00\u7bc7 \u7ec4\u7ec7\u6cbb\u7406", "\u6295\u8d44\u76d1\u7763", "\u4e3b\u8d23\u4e3b\u4e1a"],
    "\u4eba\u529b\u8d44\u6e90": ["\u7b2c\u4e5d\u7bc7 \u4eba\u4e8b\u7ba1\u7406", "\u5de5\u8d44\u51b3\u5b9a", "\u5c65\u804c\u5f85\u9047", "\u57f9\u8bad\u8d39"],
    "\u793e\u4f1a\u8d23\u4efb": ["\u7b2c\u516b\u7bc7 \u5b89\u5168\u7ba1\u7406", "\u5b89\u5168\u751f\u4ea7", "\u9632\u6c5b\u9632\u53f0"],
    "\u4f01\u4e1a\u6587\u5316": ["\u5408\u89c4\u6307\u5357", "\u7b2c\u4e00\u7bc7 \u7ec4\u7ec7\u6cbb\u7406"],
    "\u8d44\u91d1\u6d3b\u52a8": ["\u7b2c\u4e8c\u7bc7 \u8d22\u52a1\u7ba1\u7406", "\u8d44\u91d1\u7ba1\u7406", "\u53f8\u5e93", "\u878d\u8d44\u62c5\u4fdd", "\u8d44\u91d1\u51fa\u501f"],
    "\u91c7\u8d2d": ["\u7b2c\u56db\u7bc7 \u7efc\u5408\u7ba1\u7406", "\u91c7\u8d2d", "\u62db\u6807", "\u6295\u6807"],
    "\u8d44\u4ea7": ["\u7b2c\u4e8c\u7bc7 \u8d22\u52a1\u7ba1\u7406", "\u8d44\u4ea7", "\u8bc4\u4f30", "\u4ea7\u6743"],
    "\u9500\u552e": ["\u7b2c\u516d\u7bc7 \u4e1a\u52a1\u7ba1\u7406", "\u7b2c\u4e94\u7bc7 \u6cd5\u5f8b\u5408\u89c4"],
    "\u5de5\u7a0b\u9879\u76ee": ["\u5de5\u7a0b", "\u5efa\u8bbe", "\u7ae3\u5de5", "\u65bd\u5de5"],
    "\u62c5\u4fdd\u4e1a\u52a1": ["\u878d\u8d44\u62c5\u4fdd", "\u8d44\u91d1\u51fa\u501f", "\u7b2c\u4e8c\u7bc7 \u8d22\u52a1\u7ba1\u7406"],
    "\u4e1a\u52a1\u5916\u5305": ["\u7b2c\u516d\u7bc7 \u4e1a\u52a1\u7ba1\u7406", "\u7b2c\u4e94\u7bc7 \u6cd5\u5f8b\u5408\u89c4", "\u5916\u5305"],
    "\u8d22\u52a1\u62a5\u544a": ["\u7b2c\u4e8c\u7bc7 \u8d22\u52a1\u7ba1\u7406", "\u8d22\u52a1\u51b3\u7b97", "\u8d22\u52a1\u603b\u76d1"],
    "\u5168\u9762\u9884\u7b97": ["\u7b2c\u4e8c\u7bc7 \u8d22\u52a1\u7ba1\u7406", "\u9884\u7b97"],
    "\u5408\u540c\u7ba1\u7406": ["\u7b2c\u4e94\u7bc7 \u6cd5\u5f8b\u5408\u89c4", "\u5408\u540c"],
    "\u5185\u90e8\u4fe1\u606f\u4f20\u9012": ["\u7b2c\u4e09\u7bc7 \u884c\u653f\u7ba1\u7406", "\u6863\u6848", "\u7535\u5b50\u6587\u4ef6", "\u6587\u4e66"],
    "\u4fe1\u606f\u7cfb\u7edf": ["\u53f8\u5e93", "\u4fe1\u606f\u7cfb\u7edf", "\u6570\u636e\u62a5\u9001", "\u7b2c\u4e8c\u7bc7 \u8d22\u52a1\u7ba1\u7406"],
    "\u7528\u8f66\u7ba1\u7406": ["\u7b2c\u4e09\u7bc7 \u884c\u653f\u7ba1\u7406", "\u516c\u52a1\u7528\u8f66", "\u7528\u8f66"],
}


def file_matches_domain(domain: str, file_path: str) -> bool:
    hints = DOMAIN_FILE_HINTS.get(domain)
    if not hints:
        return True
    return any(hint in file_path for hint in hints)


def terms(text: str) -> Counter[str]:
    found: Counter[str] = Counter()
    for item in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", text):
        item = item.strip()
        if len(item) < 2:
            continue
        if item in STOP_TERMS:
            continue
        if len(item) <= 8:
            found[item] += 3
        for size in (2, 3, 4):
            if len(item) >= size:
                for idx in range(0, len(item) - size + 1):
                    piece = item[idx : idx + size]
                    if piece not in STOP_TERMS:
                        found[piece] += 1
    return found


def excerpt(text: str, query_terms: set[str], width: int = 220) -> str:
    compact = " ".join(text.split())
    hit_at = min((compact.find(t) for t in query_terms if compact.find(t) >= 0), default=0)
    start = max(0, hit_at - 55)
    cut = compact[start : start + width]
    if start > 0:
        cut = "..." + cut
    if start + width < len(compact):
        cut += "..."
    return cut


def load_evidence() -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    evidence = []
    index: dict[str, list[int]] = defaultdict(list)
    for record in payload["records"]:
        if not record.get("ok") or not record.get("paragraphs"):
            continue
        file_text = f"{record.get('relative_path', '')} {record.get('title_guess', '')}"
        file_terms = terms(file_text)
        for idx, paragraph in enumerate(record["paragraphs"]):
            if len(paragraph) < 20:
                continue
            item_terms = terms(paragraph) + file_terms
            evidence_id = len(evidence)
            evidence.append(
                {
                    "file": record["relative_path"],
                    "file_name": record["file_name"],
                    "paragraph_index": idx,
                    "paragraph": paragraph,
                    "terms": item_terms,
                }
            )
            for term in item_terms:
                index[term].append(evidence_id)
    return evidence, index


def control_query(control: dict[str, Any]) -> Counter[str]:
    query = terms(
        " ".join(
            str(control.get(key, ""))
            for key in ("business_domain", "control_topic", "standard_requirement", "industry_tags")
        )
    )
    for hint in DOMAIN_HINTS.get(str(control.get("business_domain")), []):
        query[hint] += 4
    return query


def score_control(control: dict[str, Any], query: Counter[str], evidence: dict[str, Any]) -> float:
    overlap = set(query) & set(evidence["terms"])
    if not overlap:
        return 0.0
    weighted = sum(min(query[t], evidence["terms"][t]) for t in overlap)
    exact_bonus = 0
    paragraph = evidence["paragraph"]
    for phrase in re.findall(r"[\u4e00-\u9fff]{3,12}", str(control.get("control_topic", ""))):
        if phrase in paragraph:
            exact_bonus += 6
    return weighted + exact_bonus


def confidence(score: float) -> str:
    if score >= 85:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def main() -> None:
    controls = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
    evidence, index = load_evidence()
    rows = []
    for control in controls:
        query = control_query(control)
        candidate_hits: Counter[int] = Counter()
        for term, weight in query.items():
            for evidence_id in index.get(term, []):
                candidate_hits[evidence_id] += weight
        candidate_ids = [evidence_id for evidence_id, _ in candidate_hits.most_common(1800)]
        scoped_ids = [
            evidence_id
            for evidence_id in candidate_ids
            if file_matches_domain(str(control.get("business_domain")), str(evidence[evidence_id]["file"]))
        ]
        if scoped_ids:
            candidate_ids = scoped_ids
        if not candidate_ids:
            best_score, best = 0.0, evidence[0]
        else:
            best_score, best = max(
                ((score_control(control, query, evidence[evidence_id]), evidence[evidence_id]) for evidence_id in candidate_ids),
                key=lambda pair: pair[0],
            )
        conf = confidence(best_score)
        status = "verified" if control.get("standard_code") in VERIFIED_CODES else "candidate"
        if conf == "low" and status != "verified":
            status = "needs_manual_review"
        evidence_excerpt = excerpt(best["paragraph"], set(query))
        rows.append(
            {
                "standard_code": control.get("standard_code"),
                "business_domain": control.get("business_domain"),
                "control_topic": control.get("control_topic"),
                "standard_requirement": control.get("standard_requirement"),
                "current_source_basis": control.get("source_basis"),
                "proposed_source_basis": f"{best['file']}；段落{best['paragraph_index'] + 1}",
                "evidence_excerpt": evidence_excerpt,
                "match_score": round(best_score, 2),
                "confidence": conf,
                "review_status": status,
            }
        )

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    summary = Counter(row["confidence"] for row in rows)
    print(json.dumps({"rows": len(rows), "summary": dict(summary), "json": str(OUT_JSON), "csv": str(OUT_CSV)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
