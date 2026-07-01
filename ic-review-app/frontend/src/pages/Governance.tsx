import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Exemption, type Supplement } from "../api/client";
import StatCards from "../components/StatCards";

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending_approval: "待审批",
    active: "已生效",
    inherited: "基准升级后继承",
    suspended_by_base_upgrade: "因基准升级暂停",
    revoked: "已撤销",
    pending: "待补正",
    rejected: "需继续补充",
    accepted: "已闭环",
    delta_reviewing: "重新核对中",
  };
  return labels[status] || status;
}

export default function Governance() {
  const [exemptions, setExemptions] = useState<Exemption[]>([]);
  const [supplements, setSupplements] = useState<Supplement[]>([]);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const [ex, su] = await Promise.all([api.exemptions(), api.supplements()]);
      setExemptions(ex);
      setSupplements(su);
      setMsg("");
    } catch (e) {
      setMsg(String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setMsg("");
    try {
      await fn();
      await load();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy("");
    }
  }

  const pendingExemptions = exemptions.filter((x) => x.status === "pending_approval").length;
  const openSupplements = supplements.filter((x) => ["pending", "rejected", "delta_reviewing"].includes(x.status)).length;
  const closedSupplements = supplements.filter((x) => x.status === "accepted").length;

  return (
    <>
      <header className="topbar">
        <div>
          <h1>整改与例外</h1>
          <p>在这里跟进材料补充和例外审批，让每个问题都有明确的处理结果。</p>
        </div>
      </header>
      <div className="content">
        {msg && <div className="alert warn">{msg}</div>}
        <StatCards
          items={[
            { label: "待审批例外", value: pendingExemptions, tone: pendingExemptions ? "warn" : "default" },
            { label: "待补正材料", value: openSupplements, tone: openSupplements ? "warn" : "default" },
            { label: "材料闭环", value: closedSupplements, tone: closedSupplements ? "ok" : "default" },
          ]}
        />

        <section className="workspace-section">
          <div className="section-heading">
            <div>
              <h2>合规例外</h2>
              <p>例外必须审批后生效，命中后仍保留原始差异和依据。</p>
            </div>
          </div>
          <div className="work-list">
            {exemptions.map((x) => (
              <article className="work-item" key={x.id}>
                <div className="work-item-main">
                  <div className="work-item-title">
                    <Link to={`/diffs/${x.difference_id}`}>{x.control_topic}</Link>
                    <span className={`pill ${["active", "inherited"].includes(x.status) ? "ok" : ["pending_approval", "suspended_by_base_upgrade"].includes(x.status) ? "amber" : "gray"}`}>
                      {statusLabel(x.status)}
                    </span>
                  </div>
                  <p>{x.justification}</p>
                  <div className="work-meta">适用范围：{x.org_scope} · 依据：{x.policy_basis || "未填写"} · 到期：{x.expires_at || "未设置"}</div>
                  {x.governance_note && <div className="inline-result">{x.governance_note}</div>}
                </div>
                <div className="work-actions">
                  {["pending_approval", "suspended_by_base_upgrade"].includes(x.status) && (
                    <button className="primary sm" disabled={busy === `approve-${x.id}`} onClick={() => act(`approve-${x.id}`, () => api.approveExemption(x.id))}>
                      {x.status === "suspended_by_base_upgrade" ? "重新审批" : "批准例外"}
                    </button>
                  )}
                  {["active", "inherited", "suspended_by_base_upgrade"].includes(x.status) && (
                    <button className="ghost sm" disabled={busy === `revoke-${x.id}`} onClick={() => act(`revoke-${x.id}`, () => api.revokeExemption(x.id))}>
                      撤销
                    </button>
                  )}
                </div>
              </article>
            ))}
            {exemptions.length === 0 && <div className="empty-state">暂无例外申请</div>}
          </div>
        </section>

        <section className="workspace-section">
          <div className="section-heading">
            <div>
              <h2>材料补正</h2>
              <p>补充材料后，只重新核对相关问题，不必重新检查整份制度。</p>
            </div>
          </div>
          <div className="work-list">
            {supplements.map((x) => (
              <article className="work-item" key={x.id}>
                <div className="work-item-main">
                  <div className="work-item-title">
                    <Link to={`/diffs/${x.difference_id}`}>差异 #{x.difference_id}</Link>
                    <span className={`pill ${x.status === "accepted" ? "ok" : "amber"}`}>{statusLabel(x.status)}</span>
                  </div>
                  <p>{x.requirement}</p>
                  <div className="work-meta">经办人：{x.assignee} · 截止：{x.due_at || "未设置"}</div>
                  {x.result_reason && <div className="inline-result">{x.result_reason}</div>}
                  {x.pollution_scan_result && <div className="inline-result">{x.pollution_scan_result}</div>}
                  {x.derived_difference_ids && <div className="work-meta">衍生待确认差异：#{x.derived_difference_ids.split(",").join("、#")}</div>}
                  {["pending", "rejected"].includes(x.status) && (
                    <textarea
                      className="work-textarea"
                      value={drafts[x.id] || ""}
                      onChange={(e) => setDrafts({ ...drafts, [x.id]: e.target.value })}
                      placeholder="录入补充条款或配套制度关键内容（至少 5 个字）"
                    />
                  )}
                </div>
                <div className="work-actions">
                  {["pending", "rejected"].includes(x.status) && (
                    <button
                      className="primary sm"
                      disabled={busy === `submit-${x.id}` || (drafts[x.id] || "").trim().length < 5}
                      onClick={() => act(`submit-${x.id}`, () => api.submitSupplement(x.id, drafts[x.id]))}
                    >
                      提交并局部审查
                    </button>
                  )}
                </div>
              </article>
            ))}
            {supplements.length === 0 && <div className="empty-state">暂无材料补正任务</div>}
          </div>
        </section>
      </div>
    </>
  );
}
