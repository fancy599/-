import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import StandardControlPoint


STANDARD_CONTROLS_PATH = Path(__file__).resolve().parents[1] / "data" / "standard_controls.json"

# 领域名称与制度中常见叫法的映射。顺序用于同分时优先选择更具体的领域。
DOMAIN_ALIASES: dict[str, tuple[str, ...]] = {
    "用车管理": ("用车管理", "车辆管理", "公务用车", "公车", "派车", "车辆使用"),
    "采购": ("采购", "采购管理", "供应商", "招标", "询价", "比价"),
    "销售": ("销售", "客户管理", "赊销", "应收账款", "销售合同", "房产经营", "商品房", "公房"),
    "资产": ("资产管理", "固定资产", "存货", "无形资产", "资产处置", "资产盘点"),
    "资金活动": ("资金活动", "资金管理", "融资", "投资", "投资产权", "产权", "资金支付", "现金管理", "银行账户", "行政费用"),
    "全面预算": ("全面预算", "预算管理", "预算编制", "预算执行", "预算调整"),
    "人力资源": ("人力资源", "工会管理", "工会", "员工招聘", "薪酬", "绩效考核", "员工培训", "人员退出"),
    "工程项目": ("工程项目", "建设工程", "工程建设", "工程造价", "项目立项", "竣工验收"),
    "信息系统": ("信息系统", "信息与数据", "信息安全", "网络安全", "数据安全", "系统开发"),
    "组织架构": ("组织架构", "公司治理", "子公司治理", "党建管理", "制度管理", "审计风控", "三重一大", "董事会", "监事会", "授权管理"),
    "研究与开发": ("研究与开发", "研发管理", "研发项目", "研发成果"),
    "担保业务": ("担保业务", "对外担保", "反担保", "担保管理"),
    "业务外包": ("业务外包", "服务外包", "外包管理", "承包方"),
    "内部信息传递": ("内部信息传递", "信访管理", "档案保密", "档案", "公文", "保密", "内部报告", "信息传递", "举报渠道"),
    "合同管理": ("合同管理", "合同印章", "合同审批", "合同履行", "合同签订", "印章"),
    "财务报告": ("财务报告", "财务会计", "财务报表", "会计报告", "合并报表"),
    "企业文化": ("企业文化", "价值观", "文化建设"),
    "发展战略": ("发展战略", "战略规划", "战略管理"),
    "社会责任": ("社会责任", "安全应急", "安全生产", "环境保护", "产品质量", "公益事业"),
}

# 具体制度只加载与其名称相符的子主题；名称仅为“XX管理办法”等领域级名称时，
# 仍保留该领域全量标准。每项为（制度名称触发词，标准控制点识别词）。
DOMAIN_SCOPE_FAMILIES: dict[str, tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = {
    "组织架构": (
        (("董事会",), ("董事会",)), (("监事会",), ("监事会",)), (("经理层",), ("经理层",)),
        (("三重一大",), ("三重一大", "集体决策")),
        (("子公司", "所属企业", "分子公司"), ("子公司", "所属企业", "分子公司", "集团管控")),
        (("参股",), ("参股", "股东权益")), (("授权",), ("授权", "权限")),
    ),
    "发展战略": (
        (("战略规划", "发展战略"), ("战略",)), (("战略调整",), ("战略调整",)),
        (("战略实施",), ("战略实施", "战略分解")), (("战略评估",), ("战略评估", "战略考核")),
    ),
    "人力资源": (
        (("招聘", "录用"), ("招聘", "录用")), (("薪酬", "工资", "福利"), ("薪酬", "工资", "福利")),
        (("绩效", "考核"), ("绩效", "考核")), (("培训",), ("培训",)),
        (("外派",), ("外派",)), (("离职", "退出", "辞退"), ("离职", "退出", "辞退")),
        (("涉密人员",), ("涉密", "保密")),
    ),
    "社会责任": (
        (("安全生产", "应急"), ("安全", "应急")), (("质量",), ("质量",)),
        (("环境保护", "环保", "节能"), ("环境", "环保", "节能")),
        (("员工权益", "劳动保护"), ("员工权益", "劳动保护")), (("公益",), ("公益",)),
    ),
    "资金活动": (
        (("融资", "筹资"), ("融资", "筹资", "债务", "偿还")),
        (("投资",), ("投资", "尽调", "退出")), (("并购",), ("并购", "收并购")),
        (("金融衍生", "套期保值"), ("衍生", "套期")), (("基金",), ("基金",)),
        (("银行账户", "账户"), ("银行账户", "开户", "销户")),
        (("资金支付", "付款"), ("资金支付", "大额资金", "付款")),
        (("现金",), ("现金", "小金库")), (("票据", "支票", "印鉴"), ("票据", "支票", "印鉴", "承兑汇票")),
        (("境外资金",), ("境外资金",)),
    ),
    "采购": (
        (("供应商",), ("供应商",)), (("招标", "招投标"), ("招标", "招投标", "评审公正")),
        (("采购方式", "询价", "比价"), ("采购方式", "方式选择", "询价", "比价")),
        (("采购需求", "请购"), ("采购需求", "请购", "需求预算")),
        (("采购验收", "验收"), ("采购验收", "验收")),
        (("采购付款", "预付款"), ("采购付款", "预付款", "资金支付")),
        (("采购档案",), ("采购档案", "资料归档", "档案监督")),
    ),
    "资产": (
        (("固定资产",), ("固定资产", "特种设备")), (("无形资产",), ("无形资产", "商标")),
        (("存货",), ("存货",)),
        (("资产减值", "减值准备", "财务核销"), ("减值", "核销", "账销案存", "追索", "预期信用损失", "存货跌价")),
        (("资产租赁", "融资租赁"), ("租赁",)), (("抵押", "质押"), ("抵押", "质押")),
    ),
    "销售": (
        (("客户信用",), ("客户信用", "信用额度")), (("客户投诉",), ("客户投诉",)),
        (("销售定价", "价格"), ("定价", "价格")), (("发货",), ("发货", "发运")),
        (("销售退回", "退货"), ("销售退回", "退货")), (("销售发票", "发票"), ("销售发票", "发票")),
        (("返利", "佣金"), ("返利", "佣金")), (("应收账款", "催收"), ("应收账款", "催收", "账龄")),
    ),
    "研究与开发": (
        (("研发立项",), ("研发立项", "项目立项")), (("研发预算",), ("研发预算",)),
        (("研发过程",), ("研发过程", "项目过程")), (("研发成果",), ("研发成果", "成果验收")),
        (("知识产权", "专利", "商标"), ("知识产权", "专利", "权属")), (("研发保密",), ("研发保密", "保密")),
    ),
    "工程项目": (
        (("工程立项", "可行性研究"), ("工程立项", "可研", "立项论证")),
        (("工程设计",), ("工程设计", "设计任务", "设计变更")), (("工程招标",), ("工程招标", "承包商招标")),
        (("承包商", "承包方"), ("承包商", "承包方", "承包合同")),
        (("工程施工", "施工现场"), ("工程施工", "施工现场", "进度", "质量")),
        (("工程变更",), ("工程变更", "设计预算变更")),
        (("竣工验收", "工程验收"), ("竣工验收", "工程验收", "竣工决算")),
        (("工程结算", "工程造价"), ("工程结算", "工程造价", "价款")),
    ),
    "担保业务": (
        (("担保调查",), ("调查", "评估")), (("担保审批",), ("担保审批", "授权")),
        (("担保合同",), ("担保合同",)), (("担保监控", "保后"), ("监控", "保后")),
        (("代偿", "追偿"), ("代偿", "追偿")),
    ),
    "业务外包": (
        (("外包范围", "外包决策"), ("外包范围", "外包决策")), (("承包方",), ("承包方",)),
        (("外包合同",), ("外包合同",)), (("外包过程",), ("外包过程", "履约")),
        (("外包验收",), ("外包验收", "成果验收")),
    ),
    "财务报告": (
        (("会计政策",), ("会计政策",)), (("期末结账", "关账"), ("结账", "关账")),
        (("合并报表",), ("合并",)), (("财务报告编制",), ("报告编制", "报表编制")),
        (("财务报告审计", "年报审计"), ("报告审计", "年度审计")),
        (("财务分析",), ("财务分析", "分析利用")),
    ),
    "全面预算": (
        (("预算编制",), ("预算编制", "年度预算")), (("预算分解",), ("预算分解",)),
        (("预算执行",), ("预算执行", "分期控制")), (("预算调整",), ("预算调整", "预算偏离")),
        (("预算分析",), ("预算分析", "跟踪分析")), (("预算考核",), ("预算考核",)),
    ),
    "合同管理": (
        (("合同起草", "合同文本"), ("合同起草", "合同文本")), (("合同审核", "合同审查"), ("合同审核", "合同审查")),
        (("合同签订", "合同用印"), ("合同签订", "合同用印", "合同印章")),
        (("合同履行",), ("合同履行", "履行监控", "价款收付")),
        (("合同变更", "合同解除"), ("合同变更", "合同解除")), (("合同纠纷",), ("合同纠纷",)),
        (("合同档案",), ("合同档案", "合同编号", "合同保管")),
    ),
    "内部信息传递": (
        (("内部报告",), ("内部报告",)), (("公文",), ("公文",)), (("档案",), ("档案",)),
        (("保密",), ("保密",)), (("信访",), ("信访",)), (("举报",), ("举报", "反舞弊")),
    ),
    "信息系统": (
        (("信息化规划", "系统规划"), ("系统规划", "整体规划")), (("系统开发", "系统建设"), ("系统开发", "系统建设", "功能需求")),
        (("账号", "访问权限"), ("账号", "访问权限", "用户")), (("运行维护", "运维"), ("运行", "维护", "设备")),
        (("备份", "灾难恢复"), ("备份", "灾难恢复")), (("网络安全", "信息安全", "数据安全"), ("安全", "加密", "日志")),
        (("业财", "数据共享"), ("业财", "数据流转", "穿透追溯")),
    ),
    "用车管理": (
        (("车辆配置", "公务用车配备"), ("配置", "配备")), (("派车", "用车"), ("派车", "用车", "使用登记")),
        (("车辆维修", "保养"), ("维修", "保养")), (("车辆保险",), ("保险",)),
        (("车辆油卡", "加油"), ("油卡", "加油")), (("车辆停放",), ("停放",)), (("车辆处置",), ("处置", "报废")),
    ),
}


# 业务领域 → 外规出处（法规名称、条款/依据要点）。
# 依据《企业内部控制基本规范》（财会〔2008〕7号）及《企业内部控制配套指引》（财会〔2010〕11号，
# 含第1—18号应用指引），由财政部会同证监会、审计署、银监会、保监会发布。
DOMAIN_EXTERNAL_REGULATION: dict[str, tuple[str, str]] = {
    "组织架构": (
        "《企业内部控制应用指引第1号——组织架构》（财会〔2010〕11号）；《中华人民共和国公司法》",
        "治理结构与机构设置、董事会/监事会/经理层权责分配、三重一大集体决策与授权审批",
    ),
    "发展战略": (
        "《企业内部控制应用指引第2号——发展战略》（财会〔2010〕11号）",
        "战略委员会设置、发展战略的制定与科学论证、战略实施与动态调整",
    ),
    "人力资源": (
        "《企业内部控制应用指引第3号——人力资源》（财会〔2010〕11号）",
        "人力资源引进、开发、使用与退出全流程，关键岗位轮岗与不相容职责分离",
    ),
    "社会责任": (
        "《企业内部控制应用指引第4号——社会责任》（财会〔2010〕11号）",
        "安全生产、产品质量、环境保护与资源节约、促进就业与维护员工权益",
    ),
    "企业文化": (
        "《企业内部控制应用指引第5号——企业文化》（财会〔2010〕11号）",
        "企业文化建设、培育与评估，董事/经理/员工诚信尽责与廉洁从业",
    ),
    "资金活动": (
        "《企业内部控制应用指引第6号——资金活动》（财会〔2010〕11号）",
        "资金筹集、投放与营运的审批授权、专户管理、印鉴与票据分管、不相容职责分离",
    ),
    "采购": (
        "《企业内部控制应用指引第7号——采购业务》（财会〔2010〕11号）",
        "请购与审批、供应商管理、招标比价、验收付款及采购各环节不相容职责分离",
    ),
    "资产": (
        "《企业内部控制应用指引第8号——资产管理》（财会〔2010〕11号）",
        "存货、固定资产、无形资产的取得、使用、处置、定期盘点与减值管理",
    ),
    "用车管理": (
        "《企业内部控制应用指引第8号——资产管理》（财会〔2010〕11号）",
        "公务用车作为单位资产的配备、使用登记、费用审批、维修与处置管理",
    ),
    "销售": (
        "《企业内部控制应用指引第9号——销售业务》（财会〔2010〕11号）",
        "销售政策与定价、客户信用管理、发货与收款、退货及不相容职责分离",
    ),
    "研究与开发": (
        "《企业内部控制应用指引第10号——研究与开发》（财会〔2010〕11号）",
        "研发立项审批、研发过程管理、成果验收与知识产权保护",
    ),
    "工程项目": (
        "《企业内部控制应用指引第11号——工程项目》（财会〔2010〕11号）",
        "立项与概预算、招投标管理、价款结算、质量控制与竣工验收",
    ),
    "担保业务": (
        "《企业内部控制应用指引第12号——担保业务》（财会〔2010〕11号）",
        "担保申请受理、调查评估、审批权限与额度控制、合同签订与后续监控",
    ),
    "业务外包": (
        "《企业内部控制应用指引第13号——业务外包》（财会〔2010〕11号）",
        "外包范围确定与承包方选择、合同签订、过程监控与质量验收",
    ),
    "财务报告": (
        "《企业内部控制应用指引第14号——财务报告》（财会〔2010〕11号）；《中华人民共和国会计法》",
        "财务报告的编制、对外提供与分析利用，会计政策选用与合并范围确定",
    ),
    "全面预算": (
        "《企业内部控制应用指引第15号——全面预算》（财会〔2010〕11号）",
        "预算编制、审批下达、执行控制与差异分析、预算考核",
    ),
    "合同管理": (
        "《企业内部控制应用指引第16号——合同管理》（财会〔2010〕11号）",
        "合同订立前的资信评估与审批、履行监控、纠纷处理与合同归档",
    ),
    "内部信息传递": (
        "《企业内部控制应用指引第17号——内部信息传递》（财会〔2010〕11号）",
        "内部报告体系、信息收集与传递、反舞弊举报渠道与信息保密",
    ),
    "信息系统": (
        "《企业内部控制应用指引第18号——信息系统》（财会〔2010〕11号）",
        "系统开发与上线、访问权限与职责分离、运行维护与数据安全",
    ),
}

# 兜底外规出处：未命中具体领域时回退到内控基本规范。
DEFAULT_EXTERNAL_REGULATION = (
    "《企业内部控制基本规范》（财会〔2008〕7号）",
    "内部环境、风险评估、控制活动、信息与沟通、内部监督五要素的总体要求",
)


def external_regulation_for(business_domain: str) -> tuple[str, str]:
    """返回业务领域对应的外规出处（法规名称、条款/依据要点）。"""
    return DOMAIN_EXTERNAL_REGULATION.get(business_domain, DEFAULT_EXTERNAL_REGULATION)


@lru_cache(maxsize=1)
def builtin_standard_controls() -> tuple[dict[str, str], ...]:
    rows = json.loads(STANDARD_CONTROLS_PATH.read_text(encoding="utf-8"))
    required = {
        "standard_code",
        "business_domain",
        "control_topic",
        "standard_requirement",
        "importance",
        "industry_tags",
        "source_basis",
        "version",
    }
    for index, row in enumerate(rows, start=1):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"内置标准控制点第 {index} 条缺少字段：{sorted(missing)}")
    return tuple(rows)


def seed_builtin_standard_controls(db: Session) -> int:
    """将随产品发布的标准控制点库同步至系统租户，返回新增数量。"""
    source_rows = builtin_standard_controls()
    source_codes = {row["standard_code"] for row in source_rows}
    existing = {
        row.standard_code: row
        for row in db.query(StandardControlPoint).filter(StandardControlPoint.tenant_id == "system").all()
    }
    created = 0
    changed = False
    now = datetime.now(timezone.utc)
    fields = (
        "business_domain",
        "control_topic",
        "standard_requirement",
        "importance",
        "industry_tags",
        "source_basis",
        "external_regulation",
        "external_basis",
        "version",
    )

    for raw_item in source_rows:
        ext_regulation, ext_basis = external_regulation_for(raw_item["business_domain"])
        item = {
            **raw_item,
            "external_regulation": raw_item.get("external_regulation") or ext_regulation,
            "external_basis": raw_item.get("external_basis") or ext_basis,
        }
        code = item["standard_code"]
        row = existing.get(code)
        if row is None:
            db.add(
                StandardControlPoint(
                    **{field: item[field] for field in ("standard_code", *fields)},
                    tenant_id="system",
                    is_active=True,
                )
            )
            created += 1
            changed = True
            continue

        row_changed = False
        for field in fields:
            if getattr(row, field) != item[field]:
                setattr(row, field, item[field])
                row_changed = True
        if not row.is_active:
            row.is_active = True
            row_changed = True
        if row_changed:
            row.updated_at = now
            changed = True

    legacy_rows = (
        db.query(StandardControlPoint)
        .filter(
            StandardControlPoint.tenant_id == "system",
            StandardControlPoint.standard_code.notin_(source_codes),
        )
        .all()
    )
    for row in legacy_rows:
        db.delete(row)
        changed = True

    if changed:
        db.commit()
    return created


def infer_standard_domains(text: str, preferred_domain: str = "", max_domains: int = 2) -> list[str]:
    """根据显式业务领域和制度文本识别标准库领域，优先采用显式领域。"""
    preferred = (preferred_domain or "").strip()
    combined = f"{preferred} {text or ''}"

    exact = [
        domain
        for domain, aliases in DOMAIN_ALIASES.items()
        if preferred == domain or preferred in aliases
    ]
    if exact:
        return exact[:1]

    scored: list[tuple[int, int, str]] = []
    for order, (domain, aliases) in enumerate(DOMAIN_ALIASES.items()):
        score = sum(3 if alias in preferred else 1 for alias in aliases if alias in combined)
        if score:
            scored.append((score, -order, domain))
    scored.sort(reverse=True)
    return [domain for _, _, domain in scored[:max_domains]]


def scope_standard_controls(
    controls: list[dict[str, Any]],
    context_text: str = "",
) -> list[dict[str, Any]]:
    """按制度名称中的具体业务子主题收窄标准；领域级通用名称保持全量。"""
    context = re.sub(r"\s+", "", context_text or "")
    if not context or not controls:
        return controls

    domain = controls[0].get("business_domain", "")
    families = DOMAIN_SCOPE_FAMILIES.get(domain, ())
    selected_keywords: set[str] = set()
    for triggers, keywords in families:
        if any(trigger in context for trigger in triggers):
            selected_keywords.update(keywords)
    if not selected_keywords:
        return controls

    scoped = []
    for control in controls:
        haystack = " ".join(
            [
                control.get("control_topic", ""),
                control.get("key_requirement", ""),
                control.get("standard_requirement", ""),
            ]
        )
        if any(keyword in haystack for keyword in selected_keywords):
            scoped.append(control)
    return scoped or controls


def load_standard_controls(
    db: Session,
    domains: list[str],
    include_general: bool = True,
    context_text: str = "",
) -> list[dict[str, Any]]:
    seed_builtin_standard_controls(db)
    selected = list(dict.fromkeys(domain for domain in domains if domain in DOMAIN_ALIASES))
    if not selected:
        return []
    rows = (
        db.query(StandardControlPoint)
        .filter(
            StandardControlPoint.is_active.is_(True),
            StandardControlPoint.business_domain.in_(selected),
        )
        .order_by(StandardControlPoint.business_domain.asc(), StandardControlPoint.id.asc())
        .all()
    )
    controls = [
        {
            "id": row.id,
            "standard_code": row.standard_code,
            "business_domain": row.business_domain,
            "control_topic": row.control_topic,
            "key_requirement": row.standard_requirement,
            "standard_requirement": row.standard_requirement,
            "importance": row.importance,
            "industry_tags": row.industry_tags,
            "source_basis": row.source_basis,
            "external_regulation": row.external_regulation,
            "external_basis": row.external_basis,
            "version": row.version,
        }
        for row in rows
    ]
    return scope_standard_controls(controls, context_text=context_text)
