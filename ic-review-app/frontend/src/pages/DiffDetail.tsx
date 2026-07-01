import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type DifferenceDetail } from "../api/client";

function reviewStatusLabel(status: string) {
  if (status === "pending") return "待处理";
  if (status === "pending_evidence") return "待补证";
  if (status === "confirmed") return "已确认";
  if (status === "rejected") return "已驳回";
  if (status === "need_supplement") return "待补充材料";
  if (status === "delta_reviewing") return "重新核对中";
  if (status === "compliant_by_supplement") return "补充材料已覆盖";
  if (status === "exemption_pending") return "例外审批中";
  if (status === "exempted") return "例外豁免";
  return status || "未知";
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// 高亮锚定该差异的“证据片段”而非主题散词，避免在原文里命中无关的同词句子。
function excerptKeywords(excerpt: string | undefined): string[] {
  if (!excerpt) return [];
  const body = excerpt.replace(
    /^(标准控制点|标准依据|集团依据|集团制度|制度依据|子公司制度|本制度|控制点规则预筛红线|集团侧|子公司侧)[:：]\s*/,
    ""
  );
  const phrases = body
    .split(/[\s,，。；;、：:|()[\]{}《》“”"'…·]+/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 6);
  return Array.from(new Set(phrases)).slice(0, 6);
}

function HighlightText({ text, keywords }: { text: string; keywords: string[] }) {
  if (!text || keywords.length === 0) return <>{text}</>;
  const pattern = new RegExp(`(${keywords.map(escapeRegExp).join("|")})`, "g");
  return (
    <>
      {text.split(pattern).map((part, index) => {
        if (!part) return null;
        const hit = keywords.includes(part);
        return hit ? <mark key={`${part}-${index}`}>{part}</mark> : part;
      })}
    </>
  );
}

export default function DiffDetail() {
  const { id } = useParams();
  const diffId = Number(id);
  const nav = useNavigate();
  const [d, setD] = useState<DifferenceDetail | null>(null);
  const [comment, setComment] = useState("经核对，确认该问题需要整改。");
  const [msg, setMsg] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.diff(diffId).then(setD).catch((e) => setMsg(String(e)));
  }, [diffId]);

  async function review(action: string) {
    if (submitting) return;
    setSubmitting(true);
    setMsg("");
    try {
      await api.reviewDiff(diffId, action, comment);
      nav(`/tasks/${d?.task_id}`);
    } catch (e) {
      setMsg(String(e));
      setSubmitting(false);
    }
  }

  if (!d) return <div className="content">加载中...</div>;
  const groupKeywords = excerptKeywords(d.group_excerpt);
  const subKeywords = excerptKeywords(d.subsidiary_excerpt);
  // 理由/建议/专家复核里出现的证据短语也高亮，统一用左右证据短语的并集。
  const keywords = Array.from(new Set([...groupKeywords, ...subKeywords]));
  const singleAudit = Boolean(d.single_document_audit);
  const subPosition = d.semantic_review
    ? singleAudit ? "本制度全文覆盖判断" : "全文语义覆盖判断"
    : d.subsidiary_location || "未标注";
  const leftTitle = singleAudit ? "设计缺陷依据（非集团原文）" : "集团制度原文";
  const rightTitle = singleAudit ? "本制度原文" : "子公司制度原文";

  return (
    <>
      <header className="topbar">
        <div>
          <h1>问题核对</h1>
          <p>{d.control_topic} · {d.diff_type}</p>
          <div className="meta-chips">
            <span className={`pill ${d.risk_level === "高" ? "red" : d.risk_level === "中" ? "amber" : "blue"}`}>
              {d.risk_level}风险
            </span>
            <span className="meta-chip">置信度 {(d.confidence * 100).toFixed(0)}%</span>
            <span className="meta-chip">证据 {d.evidence_ok ? "通过" : "待补证"}</span>
            <span className="meta-chip">复核 {reviewStatusLabel(d.review_status)}</span>
            {d.semantic_review && <span className="meta-chip semantic">已核对全文</span>}
            {d.expert_reviewed && <span className="meta-chip expert">内控复核专家已确认</span>}
          </div>
        </div>
      </header>
      <div className="content">
        {msg && <div className="alert warn">{msg}</div>}

        <div className="diff-brief">
          <div>
            <span>主题</span>
            <strong>{d.control_topic}</strong>
          </div>
          <div>
            <span>{singleAudit ? "标准依据" : "集团控制点位置"}</span>
            <strong>{d.group_location || "未标注"}</strong>
          </div>
          <div>
            <span>{singleAudit ? "本制度覆盖口径" : "子公司覆盖口径"}</span>
            <strong>{subPosition}</strong>
          </div>
        </div>

        {d.semantic_review && (
          <div className="semantic-note">
            {singleAudit
              ? "单制度检查没有集团制度原文；左侧为设计规则或标准控制点依据，右侧展示本制度原文关联片段。"
              : "本结果基于集团控制点与子公司制度全文的语义覆盖审查；下方展示两份制度的关联原文片段，不代表逐条编号对应。"}
          </div>
        )}

        {d.table_review_required && (
          <div className="alert warn table-verification-alert">
            <strong>表格内容需要人工确认</strong>
            <div>原文件中的复杂表格可能存在读取偏差，请结合原始页面确认金额、岗位和审批主体。</div>
            <div className="flex">
              {(d.table_review_documents || []).flatMap((doc) =>
                doc.pages.split(",").filter(Boolean).slice(0, 3).map((page) => (
                  <a key={`${doc.document_id}-${page}`} href={`/api/documents/${doc.document_id}/table-snapshot?page=${page}`} target="_blank" rel="noreferrer">
                    {doc.side}第 {page} 页原始快照
                  </a>
                ))
              )}
            </div>
          </div>
        )}

        <div className={d.semantic_review ? "compare semantic-compare" : "compare"}>
          <div className="clause">
            <div className="clause-hd">{leftTitle} · {d.group_location || "未标注"}</div>
            <div className="clause-bd">
              <HighlightText text={d.group_clause_text} keywords={groupKeywords} />
            </div>
            {d.group_external_regulation && (
              <div className="clause-source">
                <span className="clause-source-label">外规出处</span>
                <div className="clause-source-name">{d.group_external_regulation}</div>
                {d.group_external_basis && (
                  <div className="clause-source-basis">条款/依据要点：{d.group_external_basis}</div>
                )}
              </div>
            )}
          </div>
          <div className="clause">
            <div className="clause-hd">
              {d.semantic_review ? rightTitle : `${singleAudit ? "本制度" : "子公司制度"} · ${subPosition}`}
              {d.subsidiary_clause_truncated && (
                <span className="clause-hint">原文较长，仅显示前部分</span>
              )}
            </div>
            <div className="clause-bd">
              <HighlightText text={d.subsidiary_clause_text} keywords={subKeywords} />
            </div>
          </div>
        </div>

        {d.expert_reviewed && (
          <details className="review-detail expert-review" open>
            <summary>内控复核专家意见</summary>
            <div className="review-detail-bd">
              <HighlightText text={d.expert_review_note ?? ""} keywords={keywords} />
            </div>
          </details>
        )}

        <details className="review-detail" open>
          <summary>为什么提示这个问题</summary>
          <div className="review-detail-bd">
            <HighlightText text={d.ai_reason} keywords={keywords} />
          </div>
        </details>

        <details className="review-detail" open>
          <summary>修改建议</summary>
          <div className="review-detail-bd">
            <HighlightText text={d.suggestion} keywords={keywords} />
          </div>
        </details>

        <div className="panel">
          <div className="panel-hd">
            <strong>请确认处理结论</strong>
            <span className="panel-hd-sub">你的意见会保留在处理记录中</span>
          </div>
          <div className="panel-bd">
            <div className="form-row">
              <label>复核意见</label>
              <textarea value={comment} onChange={(e) => setComment(e.target.value)} />
            </div>
            <div className="flex">
              <button className="primary" type="button" disabled={submitting} onClick={() => review("confirmed")}>
                {submitting ? "提交中..." : "确认差异"}
              </button>
              <button className="ghost" type="button" disabled={submitting} onClick={() => review("rejected")}>
                驳回
              </button>
              <Link to={`/tasks/${d.task_id}`}>
                <button className="ghost" type="button">返回清单</button>
              </Link>
            </div>
          </div>
        </div>

      </div>
    </>
  );
}
