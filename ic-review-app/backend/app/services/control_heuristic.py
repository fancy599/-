"""Hybrid Pipeline deterministic control-point extraction.

控制点不是条款编号本身，而是条款中可审计的责任、动作、条件和留痕要求。
"""
import re

_TOPICS = [
    ("采购审批权限", ["采购审批", "采购申请", "采购事项审批", "采购预算审批", "采购支出", "支出控制审核"]),
    ("供应商准入", ["供应商", "准入", "黑名单", "合格供应商", "供应商名录"]),
    ("合同签订", ["合同签订", "合同签署", "合同审批", "合同管理", "合同审核"]),
    ("验收职责", ["验收", "检验", "到货验收", "质量验收", "入库验收"]),
    ("付款审批", ["付款审批", "支付审批", "资金支付", "付款申请", "资金审批"]),
    ("招标管理", ["招标", "投标", "招投标", "公开招标", "邀请招标"]),
    ("预算管理", ["预算编制", "预算审批", "预算调整", "预算执行", "年度预算"]),
    ("固定资产采购", ["固定资产采购", "资产采购", "采购流程"]),
    ("固定资产登记", ["资产登记", "固定资产登记", "台账", "资产目录"]),
    ("固定资产盘点", ["资产盘点", "固定资产盘点", "清查盘点"]),
    ("固定资产处置", ["资产处置", "固定资产处置", "报废", "调拨"]),
    ("用车审批", ["公务用车", "用车审批", "派车", "车辆调配"]),
    ("车辆集中管理", ["车辆管理", "集中管理", "经营和业务保障用车"]),
    ("差旅管理", ["差旅", "出差", "差旅费", "出差审批", "差旅报销"]),
    ("印章管理", ["印章", "公章", "用印", "印章保管", "印章使用"]),
    ("档案管理", ["档案", "资料归档", "文件管理", "档案保管", "档案查阅"]),
    ("费用报销", ["费用报销", "报销审批", "差旅报销", "业务招待费", "报销标准"]),
    ("对外投资", ["对外投资", "投资决策", "投资审批", "股权管理", "投资项目"]),
    ("融资担保", ["融资", "担保", "借款", "贷款", "授信"]),
    ("信息安全", ["信息安全", "网络安全", "数据安全", "保密", "信息系统"]),
    ("内部审计监督", ["内部审计", "内控检查", "审计监督", "稽核", "监督检查"]),
    ("纪律问责", ["问责", "追责", "纪律处分", "违规责任", "责任追究"]),
]

# 资产领域不能只靠“资产”或“管理”等宽泛词匹配。这里先按会计对象和
# 业务动作识别细分主题，避免资产减值/核销条款被归入固定资产日常管理。
_ASSET_TOPIC_RULES = [
    ("已核销资产追索", ["账销案存", "继续追索", "保留追索权", "核销后追索"]),
    ("存货跌价准备", ["存货跌价准备", "存货可变现净值", "成本与可变现净值孰低"]),
    ("金融资产预期信用损失", ["预期信用损失", "信用风险显著增加", "坏账准备", "应收款项减值", "委托贷款减值"]),
    ("固定资产减值测试", ["固定资产减值", "固定资产可收回金额"]),
    ("无形资产减值测试", ["无形资产减值", "无形资产可收回金额"]),
    ("在建工程减值测试", ["在建工程减值", "在建工程可收回金额"]),
    ("商誉与不确定寿命无形资产减值", ["商誉减值", "使用寿命不确定的无形资产"]),
    ("资产组减值测试", ["资产组组合", "资产组减值", "资产组的可收回金额"]),
    ("资产减值迹象识别", ["减值迹象", "可能发生减值", "陈旧过时", "长期闲置"]),
    ("资产可收回金额计量", ["可收回金额", "公允价值减去处置费用", "预计未来现金流量的现值"]),
    ("资产减值损失确认", ["减值损失", "计提相应的资产减值准备", "减值准备不得转回"]),
    ("资产减值核销披露", ["核销情况", "核销专项复核报告", "会计报表附注中进行详细披露"]),
]

_KEY_PHRASE_RE = re.compile(
    r"(?:关于|加强|规范|完善|明确|严格)([一-鿿]{2,10})(?:管理|工作|制度|规定|办法|细则)",
    re.MULTILINE,
)
_SECTION_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百零\d]+章\s*|[\(（][一二三四五六七八九十百\d]+[）)]\s*)([一-鿿]{2,20})",
    re.MULTILINE,
)
_PURPOSE_OR_SCOPE_RE = re.compile(
    r"^(?:第[一二三四五六七八九十百零\d]+条\s*)?"
    r"(?:为|为了|根据|依据|本办法适用于|本制度适用于|本办法所称|本制度所称|以下简称|总则)"
)
_PRINCIPLE_RE = re.compile(r"^(?:第[一二三四五六七八九十百零\d]+条\s*)?(?:坚持|遵循|按照).{0,80}(?:原则|方针|理念|标准)")
_CONTROL_ACTIONS = [
    "应当",
    "必须",
    "须",
    "不得",
    "严禁",
    "禁止",
    "负责",
    "审批",
    "审核",
    "批准",
    "报批",
    "备案",
    "报备",
    "登记",
    "台账",
    "归档",
    "盘点",
    "清查",
    "验收",
    "保管",
    "留痕",
    "监督",
    "检查",
    "问责",
    "追责",
    "分离",
    "授权",
    "支付",
    "处置",
    "报废",
    "调拨",
    "签订",
    "招标",
    "询价",
]
_RESPONSIBILITY_HINTS = ["负责", "由", "经", "报", "应当", "必须", "须", "不得", "严禁", "禁止"]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _has_control_signal(text: str) -> bool:
    t = _normalize_text(text)
    if len(t) < 14:
        return False
    action_hits = [kw for kw in _CONTROL_ACTIONS if kw in t]
    if not action_hits:
        return False
    has_responsibility = any(kw in t for kw in _RESPONSIBILITY_HINTS)
    if _PURPOSE_OR_SCOPE_RE.match(t) and not has_responsibility:
        return False
    if _PRINCIPLE_RE.match(t) and not has_responsibility:
        return False
    if action_hits == ["监督"] and not has_responsibility:
        return False
    return True


def _extract_topic_fallback(text: str) -> str:
    """当关键词未匹配时，从控制性文本中提取 topic；非控制性文本返回空。"""
    if not _has_control_signal(text):
        return ""
    m = _KEY_PHRASE_RE.search(text)
    if m:
        return m.group(1) + "管理"
    for line in text.split("\n")[:3]:
        m = _SECTION_RE.match(line.strip())
        if m:
            title = m.group(1)
            if title not in ("总则", "附则"):
                return title
    for kw in _CONTROL_ACTIONS:
        if kw in text:
            idx = text.find(kw)
            start = max(0, idx - 10)
            phrase = text[start: idx + len(kw)].strip()
            phrase = re.sub(r"^[\s、，；:.（）()\[\]第十二三四五六七八九百零\d条]+", "", phrase)
            if 4 <= len(phrase) <= 18:
                return phrase
    return ""


def _match_standard_topic(text: str, standard_cps: list[dict] | None) -> str:
    if not standard_cps:
        return ""
    if any(sc.get("business_domain") == "资产" for sc in standard_cps):
        normalized = _normalize_text(text)
        if any(keyword in normalized for keyword in ("资产减值准备财务核销", "减值准备财务核销", "核销资产减值准备")):
            if any(keyword in normalized for keyword in ("董事会", "三重一大", "审批", "批准", "核准", "报批")):
                return "资产减值准备核销审批"
            if any(keyword in normalized for keyword in ("专项审计", "专项复核", "会计师事务所", "审计机构")):
                return "资产减值准备核销审计"
            if any(keyword in normalized for keyword in ("证据", "证明", "损失清单", "责任认定")):
                return "资产减值准备核销证据"
            if any(keyword in normalized for keyword in ("披露", "报备", "报表附注")):
                return "资产减值核销披露"
            return "资产减值准备核销"
        for topic, keywords in _ASSET_TOPIC_RULES:
            if any(keyword in normalized for keyword in keywords):
                return topic
    best_topic = ""
    best_hits = 0
    for sc in standard_cps:
        sc_topic = (sc.get("control_topic") or "").strip()
        sc_req = (sc.get("key_requirement") or "").strip()
        hits = 0
        for kw in {sc_topic, sc_req}:
            if not kw:
                continue
            for token in re.split(r"[\s、，；;（）()]+", kw):
                if len(token) >= 2 and token in text:
                    hits += 1
        if hits > best_hits:
            best_hits = hits
            best_topic = sc_topic
    return best_topic if best_hits >= 2 else ""


def _extract_role(text: str) -> str:
    m = re.search(r"([一-鿿]{2,18}(?:部门|办公室|委员会|小组|人员|岗位|单位))负责", text)
    if m:
        return m.group(1)
    m = re.search(r"由([一-鿿]{2,18})", text)
    if m:
        return m.group(1)
    return "相关责任主体"


def _extract_action(text: str) -> str:
    for kw in _CONTROL_ACTIONS:
        if kw in text:
            return kw
    return "执行"


def extract_control_points_local(
    clauses: list[dict],
    *,
    standard_cps: list[dict] | None = None,
) -> list[dict]:
    result = []
    for idx, c in enumerate(clauses):
        text = c.get("clause_text", "")
        if not _has_control_signal(text):
            continue

        topic = _match_standard_topic(text, standard_cps)
        if not topic:
            for name, kws in _TOPICS:
                if any(k in text for k in kws):
                    topic = name
                    break
        if not topic:
            topic = _extract_topic_fallback(text)
        if not topic:
            continue

        threshold = ""
        m = re.search(r"(\d+)\s*万", text)
        if m:
            threshold = f"{m.group(1)}万元"
        result.append(
            {
                "clause_index": idx,
                "control_topic": topic,
                "subject_role": _extract_role(text),
                "action": _extract_action(text),
                "object": topic,
                "threshold": threshold,
                "requirement": text[:160],
            }
        )
    return result[:25]
