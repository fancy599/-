import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import StatCards from "../components/StatCards";
import { api, type Difference, type Task } from "../api/client";

export default function TaskDetail() {
  const { id } = useParams();
  const taskId = Number(id);
  const nav = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [diffs, setDiffs] = useState<Difference[]>([]);
  const [filter, setFilter] = useState("");

  function loadTask() {
    if (!taskId) return;
    api.task(taskId).then(setTask);
  }

  useEffect(() => {
    if (!taskId) return;
    loadTask();
  }, [taskId]);

  function loadDiffs() {
    const params: Record<string, string> = {};
    if (filter === "high") params.risk_level = "高";
    if (filter === "pending") params.review_status = "pending";
    api.diffs(taskId, params).then(setDiffs);
  }

  useEffect(() => {
    loadDiffs();
  }, [filter, taskId]);

  useEffect(() => {
    if (!taskId) return;
    if (task?.status !== "running") return;
    const timer = window.setInterval(() => {
      loadTask();
      loadDiffs();
    }, 4000);
    return () => window.clearInterval(timer);
  }, [task?.status, taskId, filter]);

  if (!task) return <div className="content">加载中…</div>;
  const singleAudit = task.group_document_id === task.subsidiary_document_id;
  const displayTaskName = !task.task_name?.trim() || /^[\x00-\x7F? -]+$/.test(task.task_name)
    ? `制度对照检查 #${task.id}`
    : task.task_name.replace("单制度设计缺陷检查：", "单份制度体检：");
  const statusLabel = (status: string) => {
    const labels: Record<string, string> = {
      pending: "待复核",
      pending_evidence: "待补证",
      confirmed: "已确认",
      rejected: "已驳回",
      need_supplement: "待补材料",
      delta_reviewing: "重新核对中",
      compliant_by_supplement: "材料覆盖",
      exemption_pending: "例外审批中",
      exempted: "例外豁免",
    };
    return labels[status] || status;
  };

  return (
    <>
      <header className="topbar">
        <div>
          <h1>{displayTaskName}</h1>
          <p>{singleAudit ? "查看体检发现的问题，点击任意一项可核对依据并处理" : "查看制度对照发现的问题，点击任意一项可核对原文并处理"}</p>
        </div>
        <div className="flex">
          <a href={api.exportUrl(taskId, "xlsx")} download>
            <button className="ghost" type="button">下载问题表</button>
          </a>
          <a href={api.exportUrl(taskId, "html")} target="_blank" rel="noreferrer">
            <button className="ghost" type="button">查看完整报告</button>
          </a>
        </div>
      </header>
      <div className="content">
        {task.pipeline_error && <div className="alert warn">{task.pipeline_error}</div>}
        <StatCards
          items={[
            { label: "发现问题", value: task.diff_count },
            { label: "高风险", value: task.high_risk_count, tone: task.high_risk_count > 0 ? "danger" : "default" },
            { label: "待你确认", value: task.pending_review_count, tone: task.pending_review_count > 0 ? "warn" : "ok" },
          ]}
        />

        {task.report_summary && (
          <div className="panel">
            <div className="panel-hd">审查摘要</div>
            <div className="panel-bd" style={{ lineHeight: 1.75, color: "#3f4a58" }}>
              {task.report_summary}
            </div>
          </div>
        )}

        <div className="panel">
          <div className="panel-hd">
            <strong>{singleAudit ? "体检问题清单" : "对照问题清单"}</strong>
            <div className="filter-bar">
              <button className={filter === "" ? "primary sm" : "ghost sm"} type="button" onClick={() => setFilter("")}>全部</button>
              <button className={filter === "high" ? "primary sm" : "ghost sm"} type="button" onClick={() => setFilter("high")}>高风险</button>
              <button className={filter === "pending" ? "primary sm" : "ghost sm"} type="button" onClick={() => setFilter("pending")}>待复核</button>
            </div>
          </div>
          <div className="panel-bd" style={{ padding: 0 }}>
            <div className="table-scroll">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 72 }}>风险</th>
                    <th style={{ width: 100 }}>类型</th>
                    <th style={{ width: 200, whiteSpace: "nowrap" }}>主题</th>
                    <th>摘要</th>
                    <th style={{ width: 88 }}>状态</th>
                  </tr>
                </thead>
                <tbody>
                  {diffs.map((d) => (
                    <tr key={d.id} className="clickable" onClick={() => nav(`/diffs/${d.id}`)}>
                      <td>
                        <span className={`pill ${d.risk_level === "高" ? "red" : d.risk_level === "中" ? "amber" : "blue"}`}>
                          {d.risk_level}
                        </span>
                      </td>
                      <td>{d.diff_type}</td>
                      <td>{d.control_topic}</td>
                      <td className="summary-cell">
                        {d.control_topic && d.summary.startsWith(d.control_topic)
                          ? d.summary.slice(d.control_topic.length).replace(/^[:：]\s*/, "") || d.summary
                          : d.summary}
                      </td>
                      <td>
                        <span
                          className={`pill ${
                            d.review_status === "pending" || d.review_status === "pending_evidence"
                              ? "amber"
                              : d.review_status === "confirmed"
                                ? "ok"
                                : "gray"
                          }`}
                        >
                          {statusLabel(d.review_status)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {diffs.length === 0 && (
              <p style={{ color: "var(--muted)", padding: 18 }}>
                {task.status === "running"
                  ? "制度检查进行中，问题清单会自动更新，请稍候…"
                  : "暂未发现需要关注的问题。"}
              </p>
            )}
          </div>
        </div>
        <Link to="/" className="back-link">← 返回首页</Link>
      </div>
    </>
  );
}
