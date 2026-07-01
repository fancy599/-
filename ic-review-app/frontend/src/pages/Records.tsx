import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import StatCards from "../components/StatCards";
import { api, type ReviewLog } from "../api/client";

export default function Records() {
  const [logs, setLogs] = useState<ReviewLog[]>([]);
  const [msg, setMsg] = useState("");
  const [undoingId, setUndoingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.reviews();
      setLogs(data);
      setMsg("");
    } catch (e) {
      setMsg(String(e));
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function undo(log: ReviewLog) {
    if (
      !window.confirm(
        "撤销后将删除该差异的全部复核记录（含连点产生的重复），并恢复为待复核。确定继续？"
      )
    ) {
      return;
    }
    setUndoingId(log.id);
    setMsg("");
    const diffId = log.difference_id;
    setLogs((prev) => prev.filter((l) => l.difference_id !== diffId));
    try {
      await api.undoReview(log.id);
      await load();
    } catch (e) {
      setMsg(String(e));
      await load();
    } finally {
      setUndoingId(null);
    }
  }

  const confirmed = logs.filter((l) => l.action === "confirmed").length;
  const rejected = logs.filter((l) => l.action === "rejected").length;
  const actionMeta = (action: string) => {
    const values: Record<string, { label: string; tone: string }> = {
      confirmed: { label: "已确认", tone: "ok" },
      rejected: { label: "已驳回", tone: "gray" },
      exemption_requested: { label: "申请例外", tone: "blue" },
      need_supplement: { label: "需补材料", tone: "amber" },
      delta_audit: { label: "重新核对", tone: "blue" },
    };
    return values[action] || { label: action, tone: "gray" };
  };

  return (
    <>
      <header className="topbar">
        <div>
          <h1>处理记录</h1>
          <p>查看每个问题的最新处理结果和意见，需要时可以撤销并重新确认。</p>
        </div>
      </header>
      <div className="content">
        {msg && <div className="alert warn">{msg}</div>}

        <StatCards
          items={[
            { label: "复核总数", value: logs.length },
            { label: "已确认", value: confirmed, tone: "ok" },
            { label: "已驳回", value: rejected },
          ]}
        />

        <div className="panel">
          <div className="panel-hd">最近处理记录</div>
          <div className="panel-bd" style={{ padding: 0 }}>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 88 }}>操作</th>
                    <th>差异主题</th>
                    <th style={{ width: 56 }}>风险</th>
                    <th style={{ width: 88 }}>类型</th>
                    <th>意见</th>
                    <th style={{ width: 160 }}>时间</th>
                    <th style={{ width: 72 }} />
                  </tr>
                </thead>
                <tbody>
                  {logs.map((l) => (
                    <tr key={l.id}>
                      <td>
                        <span className={`pill ${actionMeta(l.action).tone}`}>
                          {actionMeta(l.action).label}
                        </span>
                      </td>
                      <td>
                        <Link to={`/diffs/${l.difference_id}`}>{l.diff_summary}</Link>
                      </td>
                      <td>{l.risk_level}</td>
                      <td>{l.diff_type}</td>
                      <td className="summary-cell">{l.comment.replace(/AI 判断/g, "系统提示")}</td>
                      <td style={{ whiteSpace: "nowrap", fontSize: 12, color: "var(--muted)" }}>{l.created_at}</td>
                      <td>
                        <button
                          className="ghost sm"
                          type="button"
                          disabled={undoingId === l.id}
                          onClick={() => undo(l)}
                        >
                          {undoingId === l.id ? "撤销中" : "撤销"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {logs.length === 0 && (
              <p style={{ color: "var(--muted)", padding: 18 }}>
                暂无复核记录。请从 <Link to="/">任务首页</Link> 进入差异清单开始复核。
              </p>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
