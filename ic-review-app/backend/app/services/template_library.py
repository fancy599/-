"""脱敏制度资产库（范本）服务。

单制度体检时，把同领域的既有制度范本作为参考：
- 列出/读取 69 个脱敏范本及其标准控制点；
- 按业务领域自动匹配最相关范本（可被前端手动改写）；
- 用范本控制点比对被检制度全文，缺口生成"范本缺口"差异。

数据来源：app/data/deidentified_policies/（index.json + texts/*.txt），
随产品发布，纯本地解析，不做向量化 / RAG。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Difference, Document, ReviewTask
from app.services.match_prefilter import text_overlap_score
from app.services.text_normalize import normalize_extracted_text

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "data" / "deidentified_policies"
INDEX_PATH = TEMPLATE_DIR / "index.json"

# 范本领域（公司治理/采购管理…）→ 内置标准领域（组织架构/采购…），用于按领域自动匹配。
TEMPLATE_DOMAIN_TO_STANDARD: dict[str, str] = {
    "公司治理": "组织架构",
    "子公司治理": "组织架构",
    "制度管理": "组织架构",
    "审计风控": "组织架构",
    "党建管理": "企业文化",
    "工会管理": "企业文化",
    "投资产权": "资金活动",
    "资金管理": "资金活动",
    "财务会计": "财务报告",
    "房产经营": "资产",
    "资产管理": "资产",
    "行政费用": "用车管理",
    "采购管理": "采购",
    "档案保密": "信息系统",
    "信息与数据": "信息系统",
    "建设工程": "工程项目",
    "合同印章": "合同管理",
    "安全应急": "社会责任",
    "业务运营": "销售",
    "信访管理": "内部信息传递",
    "知识产权": "研究与开发",
}

_CONTROL_RE = re.compile(r"^\s*\d+\.\s*\[(?P<risk>.)\]\s*(?P<topic>.+?)[：:]\s*(?P<req>.+)$")
_EVIDENCE_RE = re.compile(r"^\s*留痕材料[：:]\s*(.+)$")
_BASIS_RE = re.compile(r"^\s*外部依据[：:]\s*(.+)$")


@lru_cache(maxsize=1)
def _raw_index() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"policies": []}
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


def _standard_domain(template_domain: str) -> str:
    return TEMPLATE_DOMAIN_TO_STANDARD.get(template_domain, "")


@lru_cache(maxsize=1)
def _index_by_id() -> dict[str, dict[str, Any]]:
    return {p["policy_id"]: p for p in _raw_index().get("policies", [])}


def list_templates() -> list[dict[str, Any]]:
    """范本概要列表（供下拉选择与展示）。"""
    out: list[dict[str, Any]] = []
    for p in _raw_index().get("policies", []):
        out.append(
            {
                "policy_id": p["policy_id"],
                "title": p["title"],
                "domain": p.get("domain", ""),
                "standard_domain": _standard_domain(p.get("domain", "")),
                "owner": p.get("owner", ""),
                "volume": p.get("volume", ""),
                "sequence": p.get("sequence", 0),
                "control_count": p.get("control_count", 0),
            }
        )
    return out


def _split_external_basis(raw: str) -> tuple[str, str]:
    """把"法规名称 - 依据要点"拆成（法规名称, 依据要点）。"""
    raw = (raw or "").strip()
    for sep in (" - ", " — ", " – ", "-"):
        if sep in raw:
            name, _, pts = raw.partition(sep)
            return name.strip(), pts.strip()
    return raw, ""


def _parse_controls(section: str) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in section.splitlines():
        m = _CONTROL_RE.match(line)
        if m:
            reg_name, basis_pts = "", ""
            cur = {
                "risk": m.group("risk").strip(),
                "topic": m.group("topic").strip(),
                "requirement": m.group("req").strip(),
                "evidence": "",
                "external_regulation": reg_name,
                "external_basis": basis_pts,
            }
            controls.append(cur)
            continue
        if cur is None:
            continue
        em = _EVIDENCE_RE.match(line)
        if em:
            cur["evidence"] = em.group(1).strip()
            continue
        bm = _BASIS_RE.match(line)
        if bm:
            reg_name, basis_pts = _split_external_basis(bm.group(1))
            cur["external_regulation"] = reg_name
            cur["external_basis"] = basis_pts
    return controls


@lru_cache(maxsize=128)
def get_template(policy_id: str) -> dict[str, Any] | None:
    """范本详情：元数据 + 标准控制点（含留痕材料与外部依据）+ 正文摘录文本。"""
    meta = _index_by_id().get(policy_id)
    if not meta:
        return None
    path = TEMPLATE_DIR / meta["file"]
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    body_section = ""
    control_section = ""
    m_ctrl = re.search(r"四、标准控制点\s*(.*)$", text, re.S)
    if m_ctrl:
        control_section = m_ctrl.group(1)
        body_section = text[: m_ctrl.start()]
    else:
        body_section = text
    return {
        "policy_id": policy_id,
        "title": meta["title"],
        "domain": meta.get("domain", ""),
        "standard_domain": _standard_domain(meta.get("domain", "")),
        "owner": meta.get("owner", ""),
        "volume": meta.get("volume", ""),
        "control_count": meta.get("control_count", 0),
        "controls": _parse_controls(control_section),
        "excerpt_text": body_section.strip(),
    }


def auto_match_template(doc_name: str, doc_text: str, standard_domains: list[str]) -> str | None:
    """按领域自动匹配最相关范本，返回 policy_id；同领域无范本时回退全库文本相似度。"""
    policies = _raw_index().get("policies", [])
    if not policies:
        return None
    domains = [d for d in (standard_domains or []) if d]
    probe = normalize_extracted_text(f"{doc_name} {doc_text or ''}")[:2000]

    def score(p: dict[str, Any]) -> float:
        meta_text = f"{p.get('title', '')} {p.get('domain', '')} {p.get('owner', '')}"
        return text_overlap_score(meta_text, probe)

    in_domain = [p for p in policies if _standard_domain(p.get("domain", "")) in domains]
    pool = in_domain or policies
    best = max(pool, key=score, default=None)
    if best is None:
        return None
    # 同领域优先：若领域内有候选，直接取领域内相似度最高者。
    return best["policy_id"]


TEMPLATE_AUDIT_AI_SYSTEM = (
    "你是企业内控审查专家。下面给你一份制度的正文，以及若干条来自同领域既有制度范本的控制点。"
    "重要前提：一份制度只就其自身【主题与适用范围】负责，无需覆盖范本里的全部控制点。"
    "请对每条控制点分两步判断："
    "①适用性 applicable：该控制点是否落在本制度的主题与适用范围之内"
    "（与本制度主题无关则 applicable=false，不得作为缺陷）；"
    "②覆盖性 covered：仅对适用的控制点，判断本制度是否实质覆盖其要求（关注责任主体、控制动作、"
    "审批/授权、记录留痕、监督问责等，不要求字面一致，可跨章节理解）。"
    "严格基于给定正文判断，正文中没有的不要臆测。"
    '返回 JSON：{"items":[{"index":整数,"applicable":true或false,"covered":true或false}]}'
)


def _llm_judge_template_controls(
    doc_text: str, controls: list[dict[str, Any]]
) -> dict[int, dict[str, Any]]:
    """用大模型对范本控制点做"适用性+覆盖性"判断；失败或未配置返回空字典（调用方回退规则）。"""
    if not controls:
        return {}
    from app.services.llm import LLMClient

    full_text = doc_text[:7000]
    results: dict[int, dict[str, Any]] = {}
    client = LLMClient(timeout=45)
    for start in range(0, len(controls), 10):
        chunk = controls[start:start + 10]
        payload = {
            "document_text": full_text,
            "controls": [
                {"index": start + i, "topic": c["topic"], "requirement": c["requirement"]}
                for i, c in enumerate(chunk)
            ],
        }
        try:
            data = client.complete_json(
                TEMPLATE_AUDIT_AI_SYSTEM, json.dumps(payload, ensure_ascii=False), max_retries=1
            )
            for it in (data.get("items", []) if isinstance(data, dict) else []):
                if isinstance(it, dict) and isinstance(it.get("index"), int):
                    results[it["index"]] = it
        except Exception:
            continue
    return results


def add_template_coverage_differences(
    db: Session, task: ReviewTask, doc: Document, policy_id: str
) -> int:
    """用范本的标准控制点比对被检制度全文，未覆盖的生成"范本缺口"差异。"""
    tpl = get_template(policy_id)
    if not tpl:
        return 0
    full_text = normalize_extracted_text(doc.raw_text or "")
    existing_topics = {
        row[0]
        for row in db.query(Difference.control_topic).filter(Difference.task_id == task.id).all()
    }
    controls = tpl["controls"]
    judged = _llm_judge_template_controls(full_text, controls) if get_settings().llm_configured else {}
    created = 0
    for idx, c in enumerate(controls):
        topic = c["topic"]
        req = c["requirement"]
        if not topic or topic in existing_topics:
            continue
        verdict = judged.get(idx)
        if verdict is not None:
            # 适用范围之外或已覆盖的，不算缺口。
            if verdict.get("applicable") is False or verdict.get("covered") is True:
                continue
        else:
            # 无 LLM 或该条未判到：退回文本相似度规则。
            score = text_overlap_score(f"{topic} {req}", full_text)
            if (topic in full_text) or score >= 0.18:
                continue
        risk = c["risk"] if c["risk"] in ("高", "中", "低") else "中"
        evidence = f"（留痕材料：{c['evidence']}）" if c.get("evidence") else ""
        db.add(
            Difference(
                task_id=task.id,
                diff_type="范本缺口",
                risk_level=risk,
                control_topic=topic,
                summary=f"{topic}：同领域既有制度范本含该控制要求，本制度未见覆盖",
                group_clause_id=None,
                subsidiary_clause_id=None,
                group_excerpt=f"同领域范本控制点：{topic}。{req}{evidence}",
                subsidiary_excerpt="未在本制度全文中发现可证明覆盖该范本控制点的内容。",
                group_location="同领域范本控制点",
                group_external_regulation=c.get("external_regulation", ""),
                group_external_basis=c.get("external_basis", ""),
                subsidiary_location="全文覆盖判断",
                ai_reason=(
                    f"系统以同领域既有制度范本的标准控制点比对本制度全文，"
                    f"未发现对「{topic}」的实质覆盖，可据此补充完善。"
                ),
                suggestion=f"建议补充「{topic}」相关条款：{req}",
                confidence=0.7,
                evidence_ok=True,
                review_status="pending",
            )
        )
        existing_topics.add(topic)
        created += 1
    return created
