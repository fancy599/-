from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = ROOT / "ic-review-app" / "backend"
DATA_DIR = APP_ROOT / "app" / "data" / "deidentified_policies"
TEXT_DIR = DATA_DIR / "texts"
DB_PATH = APP_ROOT / "data" / "ic_review.db"
VERSION = "脱敏版-2026-06-26"
UNIT_NAME = "脱敏制度库"


REPLACEMENTS = [
    (r"上海金外滩（集团）发展有限公司", "某集团公司"),
    (r"上海金外滩\(集团\)发展有限公司", "某集团公司"),
    (r"上海金外滩集团", "某集团"),
    (r"金外滩集团", "某集团"),
    (r"金外滩", "某集团"),
    (r"上海上泰置业有限公司", "某子公司"),
    (r"上泰置业有限公司", "某子公司"),
    (r"上泰公司", "某子公司"),
    (r"上泰", "某子公司"),
    (r"Shanghai Gold Bund\(Group\) Development Co\.,Ltd\.", "Company Name Redacted"),
    (r"沪金外滩〔?\d{4}〕?\d+号", "〔文号已脱敏〕"),
    (r"沪金上收\([^)]+\)-\d+号", "〔文号已脱敏〕"),
    (r"上海市黄浦区", "所在地"),
    (r"黄浦区", "所在地"),
    (r"上海市", "所在地"),
    (r"福州路66号", "注册地址已脱敏"),
]


def redact(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value
    for pattern, replacement in REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"第一册-\d{2}-", "", text)
    text = re.sub(r"第二册-\d{2}-", "", text)
    text = re.sub(r"\.docx$", ".txt", text, flags=re.I)
    return text


def safe_name(value: str) -> str:
    value = redact(value).strip()
    value = re.sub(r'[<>:"/\\|?*]', "_", value)
    value = re.sub(r"\s+", " ", value)
    return value[:90].strip(" ._") or "未命名制度"


def policy_id(volume: str, number: int) -> str:
    return f"{volume}-{number:02d}"


def load_sources() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    requirements = json.loads((ROOT / "policy_requirements.json").read_text(encoding="utf-8"))
    controls_data = json.loads((ROOT / "control_points_data.json").read_text(encoding="utf-8"))
    policies = {item["policy_id"]: item for item in controls_data["policies"]}
    controls_by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for control in controls_data["controls"]:
        controls_by_policy[control["policy_id"]].append(control)
    return requirements, policies, controls_by_policy


def unique_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        clean = redact(line).strip()
        if clean and clean not in seen:
            result.append(clean)
            seen.add(clean)
    return result


def build_record(
    source: dict[str, Any],
    policy_meta: dict[str, Any],
    controls: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    pid = policy_id(source["volume"], int(source["number"]))
    title = safe_name(source["title"])
    raw_title = source["title"]
    filename = f"{pid}-{title}.txt"

    opening = unique_lines(source.get("opening", []))
    requirements = [
        redact(item["text"]).strip()
        for item in source.get("requirements", [])
        if item.get("text")
    ]
    closing = unique_lines(source.get("closing", []))
    controls_slim = [
        {
            "control_id": control["control_id"],
            "objective": redact(control.get("control_objective", "")),
            "standard_control_point": redact(control.get("standard_control_point", "")),
            "owner": redact(control.get("owner", "")),
            "frequency": redact(control.get("frequency", "")),
            "evidence": redact(control.get("evidence", "")),
            "risk_level": redact(control.get("risk_level", "")),
            "internal_reference": redact(control.get("internal_reference", "")),
            "external_regulation": redact(control.get("external_regulation", "")),
            "external_basis": redact(control.get("external_basis", "")),
            "test_method": redact(control.get("test_method", "")),
        }
        for control in controls
    ]

    lines = [
        title,
        "",
        f"制度编号：{pid}",
        f"制度领域：{redact(policy_meta.get('domain', ''))}",
        f"责任部门：{redact(policy_meta.get('owner', ''))}",
        f"版本：{VERSION}",
        "脱敏说明：已移除或替换公司名称、子公司名称、注册地址、文号等可识别信息。",
        "资料说明：本文件由项目内结构化制度摘录生成，用于制度资产管理和展示；未做向量化或 RAG 入库。",
        "",
        "一、制度正文摘录",
    ]
    lines.extend(f"{i}. {text}" for i, text in enumerate(opening, start=1))
    lines.extend(["", "二、重点条款摘录"])
    lines.extend(f"{i}. {text}" for i, text in enumerate(requirements, start=1))
    lines.extend(["", "三、末尾条款摘录"])
    lines.extend(f"{i}. {text}" for i, text in enumerate(closing, start=1))
    lines.extend(["", "四、标准控制点"])
    for i, control in enumerate(controls_slim, start=1):
        lines.append(f"{i}. [{control['risk_level']}] {control['objective']}：{control['standard_control_point']}")
        if control["evidence"]:
            lines.append(f"   留痕材料：{control['evidence']}")
        if control["external_regulation"]:
            lines.append(f"   外部依据：{control['external_regulation']} - {control['external_basis']}")
    text = "\n".join(lines).strip() + "\n"

    clauses: list[dict[str, Any]] = []
    for i, item in enumerate(opening, start=1):
        clauses.append({"chapter_title": "制度正文摘录", "clause_no": f"正文摘录{i}", "clause_text": item})
    for i, item in enumerate(requirements, start=1):
        clauses.append({"chapter_title": "重点条款摘录", "clause_no": f"重点条款{i}", "clause_text": item})
    for i, item in enumerate(closing, start=1):
        clauses.append({"chapter_title": "末尾条款摘录", "clause_no": f"末尾条款{i}", "clause_text": item})
    for i, item in enumerate(controls_slim, start=1):
        clause_text = f"{item['objective']}：{item['standard_control_point']}".strip("：")
        clauses.append({"chapter_title": "标准控制点", "clause_no": f"控制点{i}", "clause_text": clause_text})

    record = {
        "policy_id": pid,
        "title": title,
        "original_title_redacted": redact(raw_title),
        "volume": source["volume"],
        "sequence": source["number"],
        "domain": redact(policy_meta.get("domain", "")),
        "owner": redact(policy_meta.get("owner", "")),
        "source_file_redacted": safe_name(policy_meta.get("source_file", source.get("file", ""))),
        "paragraph_count": source.get("paragraph_count", 0),
        "excerpt_count": len(opening) + len(requirements) + len(closing),
        "control_count": len(controls_slim),
        "file": f"texts/{filename}",
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "version": VERSION,
    }
    return record, text, clauses


def write_assets(records: list[dict[str, Any]], texts: dict[str, str]) -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    for record in records:
        path = DATA_DIR / record["file"]
        path.write_text(texts[record["policy_id"]], encoding="utf-8")
    index = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "count": len(records),
        "redaction_scope": [
            "公司名称",
            "子公司名称",
            "注册地址",
            "内部文号",
            "源文件名中的公司标识",
        ],
        "rag": False,
        "policies": records,
    }
    (DATA_DIR / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    (DATA_DIR / "README.md").write_text(
        "# 脱敏制度资产库\n\n"
        f"- 版本：{VERSION}\n"
        f"- 制度数量：{len(records)}\n"
        "- 处理方式：仅做脱敏、结构化归档和本地数据库导入，不做 RAG、不生成向量。\n"
        "- 内容来源：项目根目录的 `policy_requirements.json` 与 `control_points_data.json`。\n"
        "- 注意：当前资产是结构化摘录和控制点集合，不是原始 Word 全文复刻。\n",
        encoding="utf-8",
    )


def import_database(records: list[dict[str, Any]], texts: dict[str, str], clauses_by_policy: dict[str, list[dict[str, Any]]]) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    try:
        cur = con.cursor()
        doc_ids = [
            row[0]
            for row in cur.execute(
                "select id from documents where unit_name = ? and version = ?",
                (UNIT_NAME, VERSION),
            ).fetchall()
        ]
        if doc_ids:
            placeholders = ",".join("?" for _ in doc_ids)
            cur.execute(f"delete from control_points where document_id in ({placeholders})", doc_ids)
            cur.execute(
                f"delete from clauses where document_id in ({placeholders})",
                doc_ids,
            )
            cur.execute(f"delete from documents where id in ({placeholders})", doc_ids)

        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        for record in records:
            file_path = str((DATA_DIR / record["file"]).resolve())
            raw_text = texts[record["policy_id"]]
            cur.execute(
                """
                insert into documents (
                    document_name, unit_name, document_level, business_domain, version,
                    parse_status, tenant_id, org_id, lock_status, quality_status,
                    file_size, content_hash, file_path, raw_text, created_at
                )
                values (?, ?, ?, ?, ?, 'parsed', 'default', 'deidentified', 'unlocked', 'normal', ?, ?, ?, ?, ?)
                """,
                (
                    record["title"],
                    UNIT_NAME,
                    "group",
                    record["domain"] or "内控",
                    VERSION,
                    len(raw_text.encode("utf-8")),
                    record["content_hash"],
                    file_path,
                    raw_text,
                    now,
                ),
            )
            doc_id = cur.lastrowid
            for i, clause in enumerate(clauses_by_policy[record["policy_id"]], start=1):
                cur.execute(
                    """
                    insert into clauses (
                        document_id, chapter_title, clause_no, clause_text,
                        page_no, paragraph_no, location_label
                    )
                    values (?, ?, ?, ?, null, ?, ?)
                    """,
                    (
                        doc_id,
                        clause["chapter_title"],
                        clause["clause_no"],
                        clause["clause_text"],
                        i,
                        f"{clause['chapter_title']} {clause['clause_no']}".strip(),
                    ),
                )
        con.commit()
    finally:
        con.close()


def main() -> None:
    requirements, policies, controls_by_policy = load_sources()
    records: list[dict[str, Any]] = []
    texts: dict[str, str] = {}
    clauses_by_policy: dict[str, list[dict[str, Any]]] = {}
    for source in requirements:
        pid = policy_id(source["volume"], int(source["number"]))
        record, text, clauses = build_record(source, policies[pid], controls_by_policy.get(pid, []))
        records.append(record)
        texts[pid] = text
        clauses_by_policy[pid] = clauses

    records.sort(key=lambda item: (item["volume"], item["sequence"]))
    write_assets(records, texts)
    import_database(records, texts, clauses_by_policy)
    print(json.dumps({"imported": len(records), "asset_dir": str(DATA_DIR), "db": str(DB_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
