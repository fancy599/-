from __future__ import annotations
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any


raise SystemExit(
    "Deprecated: this broad domain-level source_basis updater was superseded by "
    "build_standard_source_basis_review.py + apply_verified_source_basis.py, "
    "which require item-level evidence verification."
)


ROOT = Path(__file__).resolve().parents[3]
STANDARD_PATH = ROOT / "ic-review-app" / "backend" / "app" / "data" / "standard_controls.json"
SOURCE_PATH = ROOT / "control_points_data.json"
DB_PATH = ROOT / "ic-review-app" / "backend" / "data" / "ic_review.db"

DOMAIN_BASIS: dict[str, list[str]] = {
    "组织架构": [
        "《企业内部控制应用指引第1号——组织架构》（财会〔2010〕11号）",
        "《中华人民共和国公司法》",
        "沪国资委评价〔2016〕423号《关于加快市国资委系统企业内控体系建设的意见》",
        "沪国资党委〔2017〕136号《关于市管国有企业党建工作要求写入公司章程的指导意见》",
        "沪国资委法规〔2025〕27号《市国资委监管企业国有独资公司章程指引（2024版）》《市国资委监管企业国有控股公司章程指引（2024版）》",
    ],
    "发展战略": [
        "《企业内部控制应用指引第2号——发展战略》（财会〔2010〕11号）",
        "沪国资委规创〔2025〕199号《上海市国资委监管企业主责主业管理办法》",
    ],
    "人力资源": [
        "《企业内部控制应用指引第3号——人力资源》（财会〔2010〕11号）",
        "沪府规〔2019〕7号《上海市人民政府关于本市改革国有企业工资决定机制的实施意见》",
        "《上海市市级机关培训费管理办法》",
    ],
    "社会责任": [
        "《企业内部控制应用指引第4号——社会责任》（财会〔2010〕11号）",
        "《中华人民共和国安全生产法》",
        "《上海市安全生产条例》",
        "《上海市防汛防台专项应急预案》",
    ],
    "企业文化": [
        "《企业内部控制应用指引第5号——企业文化》（财会〔2010〕11号）",
        "沪国资委法规〔2022〕151号《上海市国资委监管企业合规管理指南》",
    ],
    "资金活动": [
        "《企业内部控制应用指引第6号——资金活动》（财会〔2010〕11号）",
        "沪国资委评价〔2013〕172号《关于进一步加强市国资委委管企业资金管理的通知》",
        "沪国资委评价〔2023〕79号《市国资委监管企业融资担保及资金出借管理办法》",
        "《关于推动市国资委监管企业深化司库体系建设的通知》及《上海市监管企业司库体系建设标准》",
    ],
    "采购": [
        "《企业内部控制应用指引第7号——采购业务》（财会〔2010〕11号）",
        "《中华人民共和国招标投标法》",
        "《关于规范中央企业采购管理工作的指导意见》",
        "沪财采〔2023〕28号《关于健全本市政府采购全链条管理的行动方案（2024-2026年）》",
        "沪财发〔2024〕1号《上海市政府采购供应商信息登记管理办法》",
    ],
    "资产": [
        "《企业内部控制应用指引第8号——资产管理》（财会〔2010〕11号）",
        "沪国资委评价〔2014〕7号《上海市国资委委管企业资产减值准备财务核销工作办法》",
        "沪国资委评估〔2019〕366号《上海市企业国有资产评估管理暂行办法》",
        "沪国资委评估〔2020〕100号《上海市企业国有资产评估核准备案操作手册》",
    ],
    "销售": [
        "《企业内部控制应用指引第9号——销售业务》（财会〔2010〕11号）",
        "《中华人民共和国民法典》",
        "《中华人民共和国城市房地产管理法》",
        "《商品房销售管理办法》",
        "《上海市住房租赁条例》",
        "《上海市国资委关于进一步完善市国资委监管企业不动产租赁管理工作的实施意见》",
    ],
    "研究与开发": [
        "《企业内部控制应用指引第10号——研究与开发》（财会〔2010〕11号）",
        "《中华人民共和国专利法》《中华人民共和国商标法》《中华人民共和国著作权法》",
        "《上海市国有企业知识产权管理和保护工作指引》",
    ],
    "工程项目": [
        "《企业内部控制应用指引第11号——工程项目》（财会〔2010〕11号）",
        "《中华人民共和国建筑法》",
        "《建设工程质量管理条例》",
        "《建设工程安全生产管理条例》",
        "《建设工程工程量清单计价标准》（GB/T 50500-2024）",
    ],
    "担保业务": [
        "《企业内部控制应用指引第12号——担保业务》（财会〔2010〕11号）",
        "沪国资委评价〔2023〕79号《市国资委监管企业融资担保及资金出借管理办法》",
    ],
    "业务外包": [
        "《企业内部控制应用指引第13号——业务外包》（财会〔2010〕11号）",
        "《中华人民共和国民法典》",
        "沪国资委法规〔2022〕2号《上海市国资委监管企业合规管理办法》",
    ],
    "财务报告": [
        "《企业内部控制应用指引第14号——财务报告》（财会〔2010〕11号）",
        "《中华人民共和国会计法》",
        "《企业财务会计报告条例》",
        "沪国资委评价〔2011〕490号《上海市国有企业财务决算审计工作规则》",
        "《市国资委监管企业财务总监管理制度》",
    ],
    "全面预算": [
        "《企业内部控制应用指引第15号——全面预算》（财会〔2010〕11号）",
        "《企业内部控制基本规范》（财会〔2008〕7号）",
        "沪国资委评价〔2016〕423号《关于加快市国资委系统企业内控体系建设的意见》",
    ],
    "合同管理": [
        "《企业内部控制应用指引第16号——合同管理》（财会〔2010〕11号）",
        "《中华人民共和国民法典》",
        "沪国资委法规〔2022〕2号《上海市国资委监管企业合规管理办法》",
    ],
    "内部信息传递": [
        "《企业内部控制应用指引第17号——内部信息传递》（财会〔2010〕11号）",
        "《中华人民共和国档案法》及《中华人民共和国档案法实施条例》",
        "《中华人民共和国保守国家秘密法》及其实施条例",
        "《信访工作条例》",
        "《党政机关公文处理工作条例》",
        "《电子文件归档与电子档案管理规范》",
    ],
    "信息系统": [
        "《企业内部控制应用指引第18号——信息系统》（财会〔2010〕11号）",
        "《中华人民共和国网络安全法》",
        "《中华人民共和国数据安全法》",
        "《中华人民共和国个人信息保护法》",
        "《网络数据安全管理条例》",
        "《上海市国资委监管企业司库信息系统数据报送标准规范》",
    ],
    "用车管理": [
        "《企业内部控制应用指引第8号——资产管理》（财会〔2010〕11号）",
        "《党政机关公务用车管理办法》",
        "《上海市事业单位及国有企业公务用车制度改革推进工作会会议材料》",
        "《市管国有企业领导人员履职待遇、业务支出管理规定》",
    ],
}

REPLACEMENTS = [
    (r"上海金外滩（集团）发展有限公司", "某集团公司"),
    (r"上海金外滩\(集团\)发展有限公司", "某集团公司"),
    (r"上海金外滩集团", "某集团"),
    (r"金外滩集团", "某集团"),
    (r"金外滩", "某集团"),
    (r"上海市黄浦区", "所在地"),
    (r"黄浦区", "所在地"),
]


def redact(value: Any) -> str:
    text = "" if value is None else str(value)
    for pattern, replacement in REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    return text.strip()


def normalize(text: str) -> str:
    return re.sub(r"\W+", "", text or "").lower()


def unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = redact(value)
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def external_basis_by_requirement() -> dict[str, list[str]]:
    if not SOURCE_PATH.exists():
        return {}
    data = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    mapping: dict[str, list[str]] = defaultdict(list)
    for item in data.get("controls", []):
        key = normalize(item.get("standard_control_point", ""))
        if not key:
            continue
        reg = redact(item.get("external_regulation", ""))
        basis = redact(item.get("external_basis", ""))
        applicability = redact(item.get("applicability", ""))
        source_url = redact(item.get("source_url", ""))
        text = reg
        if basis:
            text += f"（{basis}）"
        if applicability:
            text += f"；适用性：{applicability}"
        if source_url:
            text += f"；官方来源：{source_url}"
        if text:
            mapping[key].append(text)
    return {key: unique(values) for key, values in mapping.items()}


def source_basis_for(row: dict[str, Any], external_by_req: dict[str, list[str]]) -> str:
    domain = row.get("business_domain", "")
    requirement_key = normalize(row.get("standard_requirement", ""))
    specific = external_by_req.get(requirement_key, [])
    domain_basis = DOMAIN_BASIS.get(domain, ["《企业内部控制基本规范》（财会〔2008〕7号）"])
    parts = unique(specific + domain_basis)
    return "；".join(parts)


def sync_database(rows: list[dict[str, Any]]) -> None:
    if not DB_PATH.exists():
        return
    con = sqlite3.connect(DB_PATH)
    try:
        for row in rows:
            con.execute(
                """
                update standard_control_points
                set source_basis=?
                where standard_code=? and tenant_id='system'
                """,
                (row["source_basis"], row["standard_code"]),
            )
        con.commit()
    finally:
        con.close()


def main() -> None:
    rows = json.loads(STANDARD_PATH.read_text(encoding="utf-8"))
    external_by_req = external_basis_by_requirement()
    changed = 0
    for row in rows:
        old = row.get("source_basis", "")
        new = source_basis_for(row, external_by_req)
        if old != new:
            row["source_basis"] = new
            changed += 1
    STANDARD_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sync_database(rows)
    print(json.dumps({"rows": len(rows), "changed": changed}, ensure_ascii=False))


if __name__ == "__main__":
    main()
