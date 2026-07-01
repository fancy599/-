from dataclasses import dataclass


@dataclass(frozen=True)
class PollutionHit:
    topic: str
    reason: str
    suggestion: str


RULES = (
    (("一人决定", "个人决定", "经理决定"), "重大事项单人决策风险", "补充材料出现单人决策表述，可能违反集体决策或职责制衡要求。", "建议补充集体审议、前置研究或复核审批机制。"),
    (("先实施后审批", "事后补批", "先采购后审批"), "事后补批风险", "补充材料允许先执行后审批，可能弱化事前控制。", "建议明确事前审批要求和紧急情形的受控例外流程。"),
    (("拆分采购", "化整为零", "规避审批"), "规避审批阈值风险", "补充材料存在拆分或规避审批阈值的高风险表述。", "建议明确禁止拆分规避审批并增加监督问责。"),
    (("无需留痕", "无需记录", "口头审批"), "监督留痕缺失", "补充材料可能允许无记录或口头审批，证据链不足。", "建议明确书面审批、系统留痕和档案保存要求。"),
)


def scan_delta_pollution(text: str) -> list[PollutionHit]:
    normalized = text.replace(" ", "")
    return [
        PollutionHit(topic, reason, suggestion)
        for keywords, topic, reason, suggestion in RULES
        if any(keyword in normalized for keyword in keywords)
    ]
