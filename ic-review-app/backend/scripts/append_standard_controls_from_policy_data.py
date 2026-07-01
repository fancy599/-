from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
STANDARD_PATH = ROOT / "ic-review-app" / "backend" / "app" / "data" / "standard_controls.json"
SOURCE_PATH = ROOT / "control_points_data.json"
DB_PATH = ROOT / "ic-review-app" / "backend" / "data" / "ic_review.db"
VERSION = "V2026.1"

DOMAIN_MAP = {
    "公司治理": "组织架构",
    "制度管理": "组织架构",
    "党建管理": "组织架构",
    "子公司治理": "组织架构",
    "审计风控": "组织架构",
    "投资产权": "资金活动",
    "资金管理": "资金活动",
    "行政费用": "资金活动",
    "财务会计": "财务报告",
    "采购管理": "采购",
    "资产管理": "资产",
    "建设工程": "工程项目",
    "安全应急": "社会责任",
    "档案保密": "内部信息传递",
    "信访管理": "内部信息传递",
    "信息与数据": "信息系统",
    "合同印章": "合同管理",
    "知识产权": "研究与开发",
    "房产经营": "销售",
    "业务运营": "业务外包",
    "工会管理": "人力资源",
}

PREFIX_MAP = {
    "组织架构": "ORG",
    "发展战略": "STR",
    "人力资源": "HR",
    "社会责任": "CSR",
    "企业文化": "CULT",
    "资金活动": "FUND",
    "采购": "PUR",
    "资产": "AST",
    "销售": "SALE",
    "研究与开发": "RD",
    "工程项目": "ENG",
    "担保业务": "GUAR",
    "业务外包": "OUT",
    "财务报告": "FINR",
    "全面预算": "BUD",
    "合同管理": "CONT",
    "内部信息传递": "INFO",
    "信息系统": "IT",
    "用车管理": "VEH",
}

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


def redact(text: Any) -> str:
    value = "" if text is None else str(text)
    for pattern, replacement in REPLACEMENTS:
        value = re.sub(pattern, replacement, value)
    return value.strip()


def normalize(text: str) -> str:
    return re.sub(r"\W+", "", text or "").lower()


def importance_for(risk_level: str) -> str:
    return "high" if "高" in risk_level else "required"


def next_numbers(rows: list[dict[str, Any]]) -> dict[str, int]:
    numbers: dict[str, int] = defaultdict(int)
    for row in rows:
        match = re.match(r"([A-Z]+)-(\d+)$", row.get("standard_code", ""))
        if match:
            numbers[match.group(1)] = max(numbers[match.group(1)], int(match.group(2)))
    return numbers


def make_source_basis(item: dict[str, Any]) -> str:
    pieces = [
        "69项制度外规核对及标准控制点",
        f"制度：{redact(item.get('policy'))}",
        f"控制点：{item.get('control_id', '')}",
        f"责任部门：{redact(item.get('owner'))}",
    ]
    if item.get("external_regulation"):
        pieces.append(f"外规：{redact(item.get('external_regulation'))}")
    if item.get("internal_reference"):
        pieces.append(f"内部依据摘录：{redact(item.get('internal_reference'))[:180]}")
    return "；".join(piece for piece in pieces if piece and not piece.endswith("："))


def build_rows() -> tuple[list[dict[str, Any]], int]:
    rows = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    existing_requirements = {normalize(row["standard_requirement"]) for row in rows}
    numbers = next_numbers(rows)
    added = 0

    for item in source["controls"]:
        requirement = redact(item.get("standard_control_point"))
        if not requirement:
            continue
        key = normalize(requirement)
        if key in existing_requirements:
            continue
        domain = DOMAIN_MAP.get(item.get("domain", ""), item.get("domain", "") or "组织架构")
        prefix = PREFIX_MAP.get(domain, "GEN")
        numbers[prefix] += 1
        rows.append(
            {
                "standard_code": f"{prefix}-{numbers[prefix]:03d}",
                "business_domain": domain,
                "control_topic": redact(item.get("control_objective")) or "制度控制",
                "standard_requirement": requirement,
                "importance": importance_for(redact(item.get("risk_level"))),
                "industry_tags": "国企,内控,制度控制点,69项制度",
                "source_basis": make_source_basis(item),
                "version": VERSION,
            }
        )
        existing_requirements.add(key)
        added += 1

    return rows, added


def sync_database(rows: list[dict[str, Any]]) -> None:
    if not DB_PATH.exists():
        return
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    con = sqlite3.connect(DB_PATH)
    try:
        existing = {
            row[0]: row[1]
            for row in con.execute(
                "select standard_code, id from standard_control_points where tenant_id='system'"
            )
        }
        source_codes = {row["standard_code"] for row in rows}
        for item in rows:
            row_id = existing.get(item["standard_code"])
            values = (
                item["business_domain"],
                item["control_topic"],
                item["standard_requirement"],
                item["importance"],
                item["industry_tags"],
                item["source_basis"],
                "",
                "",
                item["version"],
                now,
                item["standard_code"],
            )
            if row_id:
                con.execute(
                    """
                    update standard_control_points
                    set business_domain=?, control_topic=?, standard_requirement=?, importance=?,
                        industry_tags=?, source_basis=?, external_regulation=?, external_basis=?,
                        version=?, updated_at=?, is_active=1
                    where standard_code=? and tenant_id='system'
                    """,
                    values,
                )
            else:
                con.execute(
                    """
                    insert into standard_control_points (
                        standard_code, business_domain, control_topic, standard_requirement,
                        importance, industry_tags, source_basis, external_regulation, external_basis,
                        version, tenant_id, is_active, created_at, updated_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?, '', '', ?, 'system', 1, ?, ?)
                    """,
                    (
                        item["standard_code"],
                        item["business_domain"],
                        item["control_topic"],
                        item["standard_requirement"],
                        item["importance"],
                        item["industry_tags"],
                        item["source_basis"],
                        item["version"],
                        now,
                        now,
                    ),
                )

        stale = sorted(set(existing) - source_codes)
        for code in stale:
            con.execute(
                "delete from standard_control_points where standard_code=? and tenant_id='system'",
                (code,),
            )
        con.commit()
    finally:
        con.close()


def main() -> None:
    rows, added = build_rows()
    STANDARD_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sync_database(rows)
    print(json.dumps({"total": len(rows), "added": added, "path": str(STANDARD_PATH)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
