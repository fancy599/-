from sqlalchemy.orm import Session

from app.models import (
    Clause, ControlPoint, Difference, DiffClauseMapping, Document, ExemptionRule,
    PipelineRunLog, ReviewLog, ReviewTask, SupplementRequest, TaskCheckpoint,
    TaskExecutionEvent,
)


GROUP_CLAUSES = [
    {
        "chapter_title": "第四章 采购审批",
        "clause_no": "第十二条",
        "clause_text": "第十二条 采购事项应按照集团授权管理规定执行。单项采购预算金额超过 200 万元的，应提交集团采购委员会审批；200 万元及以下事项，由子公司按照集团授权清单履行内部审批程序。涉及战略供应商、关联交易或重大合同条款变更的，不受金额限制，应报集团采购管理部门复核。",
        "page_no": 18,
        "location_label": "第 4 章第 12 条，第 18 页",
    },
    {
        "chapter_title": "第四章 采购审批",
        "clause_no": "第十条",
        "clause_text": "第十条 采购申请须事前完成审批，未经审批不得组织实施采购活动。紧急采购须事先报集团备案。",
        "page_no": 16,
        "location_label": "第 4 章第 10 条，第 16 页",
    },
    {
        "chapter_title": "第二章 供应商管理",
        "clause_no": "第五条",
        "clause_text": "第五条 供应商准入应经过评审，并核查黑名单。应建立供应商年度复评机制。",
        "page_no": 8,
        "location_label": "第 2 章第 5 条，第 8 页",
    },
]

SUB_CLAUSES = [
    {
        "chapter_title": "第三章 采购审批",
        "clause_no": "第八条",
        "clause_text": "第八条 公司采购事项由业务部门发起，采购部组织询价、评审及合同谈判。单项采购预算金额 500 万元及以下的，由总经理办公会审批后执行；超过 500 万元的，按集团相关规定报批。特殊紧急采购可先行组织实施，后续补充审批材料。",
        "page_no": 9,
        "location_label": "第 3 章第 8 条，第 9 页",
    },
    {
        "chapter_title": "第五章 紧急采购",
        "clause_no": "第十四条",
        "clause_text": "第十四条 紧急采购可先组织实施，五个工作日内补办审批手续。",
        "page_no": 14,
        "location_label": "第 5 章第 14 条，第 14 页",
    },
]

DIFFERENCES = [
    {
        "diff_type": "越权",
        "risk_level": "高",
        "control_topic": "采购审批权限",
        "summary": "子公司将 500 万以下审批权限下放至总经理办公会，超出集团 200 万授权边界。",
        "group_excerpt": "超过 200 万元的，应提交集团采购委员会审批",
        "subsidiary_excerpt": "500 万元及以下的，由总经理办公会审批后执行",
        "group_location": "第 4 章第 12 条，第 18 页",
        "subsidiary_location": "第 3 章第 8 条，第 9 页",
        "ai_reason": "集团明确 200 万元以上须报集团采购委员会，子公司将本级审批上限设为 500 万元，扩大子公司审批权限。",
        "suggestion": "建议将子公司审批权限调整为 200 万元及以下由内部授权审批，超过 200 万元提交集团采购委员会。",
        "confidence": 0.91,
        "evidence_ok": True,
    },
    {
        "diff_type": "冲突",
        "risk_level": "高",
        "control_topic": "事前审批",
        "summary": "子公司允许紧急采购事后补批，与集团事前审批要求冲突。",
        "group_excerpt": "采购申请须事前完成审批",
        "subsidiary_excerpt": "紧急采购可先行组织实施，后续补充审批",
        "group_location": "第 4 章第 10 条，第 16 页",
        "subsidiary_location": "第 5 章第 14 条，第 14 页",
        "ai_reason": "集团要求事前审批，子公司允许先实施后补批。",
        "suggestion": "限定紧急采购适用条件，并明确须事先向集团备案。",
        "confidence": 0.88,
        "evidence_ok": True,
    },
    {
        "diff_type": "缺失",
        "risk_level": "中",
        "control_topic": "供应商准入",
        "summary": "子公司制度未明确供应商准入评审与黑名单校验。",
        "group_excerpt": "供应商准入应经过评审，并核查黑名单",
        "subsidiary_excerpt": "（无匹配条款）",
        "group_location": "第 2 章第 5 条，第 8 页",
        "subsidiary_location": "无匹配条款",
        "ai_reason": "集团在供应商管理章节有明确要求，子公司制度未见对应条款。",
        "suggestion": "补充供应商准入评审、黑名单校验和年度复评要求。",
        "confidence": 0.85,
        "evidence_ok": True,
    },
]


def seed_demo(db: Session) -> dict:
    db.query(DiffClauseMapping).delete()
    db.query(ExemptionRule).delete()
    db.query(SupplementRequest).delete()
    db.query(ReviewLog).delete()
    db.query(Difference).delete()
    db.query(TaskCheckpoint).delete()
    db.query(TaskExecutionEvent).delete()
    db.query(PipelineRunLog).delete()
    db.query(ReviewTask).delete()
    db.query(ControlPoint).delete()
    db.query(Clause).delete()
    for doc in db.query(Document).all():
        db.delete(doc)
    db.commit()

    group_text = "\n\n".join(c["clause_text"] for c in GROUP_CLAUSES)
    sub_text = "\n\n".join(c["clause_text"] for c in SUB_CLAUSES)

    group_doc = Document(
        document_name="集团采购管理制度",
        unit_name="集团总部",
        document_level="group",
        business_domain="采购",
        version="V2026.03",
        parse_status="parsed",
        raw_text=group_text,
    )
    sub_doc = Document(
        document_name="华东子公司采购管理办法",
        unit_name="华东子公司",
        document_level="subsidiary",
        business_domain="采购",
        version="V2025.12",
        parse_status="parsed",
        raw_text=sub_text,
    )
    db.add(group_doc)
    db.add(sub_doc)
    db.flush()

    group_clause_ids = []
    for c in GROUP_CLAUSES:
        clause = Clause(document_id=group_doc.id, **c)
        db.add(clause)
        db.flush()
        group_clause_ids.append(clause.id)
        db.add(
            ControlPoint(
                clause_id=clause.id,
                document_id=group_doc.id,
                business_domain="采购",
                control_topic="采购审批权限" if "200 万" in c["clause_text"] else "供应商准入",
                subject_role="集团采购委员会",
                action="审批",
                threshold="200万元",
                requirement=c["clause_text"][:200],
            )
        )

    sub_clause_ids = []
    for c in SUB_CLAUSES:
        clause = Clause(document_id=sub_doc.id, **c)
        db.add(clause)
        db.flush()
        sub_clause_ids.append(clause.id)

    task = ReviewTask(
        task_name="2026 采购制度专项审查",
        business_domain="采购",
        description="Demo 内置样例任务",
        group_document_id=group_doc.id,
        subsidiary_document_id=sub_doc.id,
        status="reviewing",
        current_step=6,
        report_summary="识别 3 条差异，其中高风险 2 条，建议优先处理审批权限越权与事前审批冲突。",
    )
    db.add(task)
    db.flush()

    for i, d in enumerate(DIFFERENCES):
        diff = Difference(
            task_id=task.id,
            group_clause_id=group_clause_ids[0] if i == 0 else (group_clause_ids[1] if i == 1 else group_clause_ids[2]),
            subsidiary_clause_id=sub_clause_ids[0] if i < 2 else None,
            review_status="pending",
            **d,
        )
        db.add(diff)

    db.commit()
    return {
        "group_document_id": group_doc.id,
        "subsidiary_document_id": sub_doc.id,
        "task_id": task.id,
    }
