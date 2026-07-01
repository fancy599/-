import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import StatCards from "../components/StatCards";
import { api, type Dashboard, type Task } from "../api/client";

export default function Home() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [health, setHealth] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const nav = useNavigate();

  const load = useCallback(async () => {
    const [d, h] = await Promise.all([api.dashboard(), api.health()]);
    setData(d);
    setHealth(h.llm_configured ? "" : h.message);
  }, []);

  useEffect(() => {
    load()
      .catch((e) => setHealth(String(e)))
      .finally(() => setLoading(false));
  }, [load]);

  async function handleSeed() {
    if (
      data &&
      data.total_tasks > 0 &&
      !window.confirm("将清空现有全部任务、制度与复核记录，并写入采购演示样例。确定继续？")
    ) {
      return;
    }
    setMsg("");
    await api.seed();
    await load();
    setMsg("已重置并加载演示数据（1 个任务、3 条待复核差异）");
  }

  async function handleDeleteTask(task: Task) {
    if (!window.confirm(`删除任务「${task.task_name}」及其全部差异与复核记录？`)) return;
    setDeletingId(task.id);
    setMsg("");
    try {
      await api.deleteTask(task.id);
      await load();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setDeletingId(null);
    }
  }

  if (loading) return <div className="content">加载中…</div>;

  const task = data?.pending_task;
  const recent = data?.recent_tasks ?? [];
  const taskStatus = (status: string) =>
    ({ reviewing: "待复核", running: "检查中", completed: "已完成", failed: "未完成" })[status] || status;
  const taskTitle = (item: Task) => {
    const name = item.task_name?.trim();
    if (!name || /^[\x00-\x7F? -]+$/.test(name)) return `制度对照检查 #${item.id}`;
    return name.replace("单制度设计缺陷检查：", "单份制度体检：");
  };

  return (
    <>
      <header className="topbar">
        <div>
          <h1>我的工作台</h1>
          <p>先处理需要确认的问题，也可以发起一次新的制度检查。</p>
          <div className="arch-badge">
            自动检查制度内容，重要结论由人工确认
          </div>
        </div>
        <div className="flex">
          <button className="ghost" type="button" onClick={handleSeed}>
            恢复示例数据
          </button>
          <Link to="/tasks/new">
            <button className="primary" type="button">发起制度检查</button>
          </Link>
        </div>
      </header>
      <div className="content">
        {health && <div className="alert warn">{health}</div>}
        {msg && <div className={`alert ${msg.includes("已重置") ? "info" : "warn"}`}>{msg}</div>}
        {task?.pipeline_error && <div className="alert warn">{task.pipeline_error}</div>}

        {data && data.total_tasks > 1 && (
          <div className="alert warn">
            共有 <strong>{data.total_tasks}</strong> 次制度检查，其中还有 <strong>{data.pending_reviews}</strong> 个问题等待确认。
            建议先完成待办，再发起新的检查。
          </div>
        )}

        {data && (
          <StatCards
            items={[
              { label: "制度检查", value: data.total_tasks },
              {
                label: "待确认问题",
                value: data.pending_reviews,
                tone: data.pending_reviews > 0 ? "warn" : "default",
              },
            ]}
          />
        )}

        {task && task.pending_review_count > 0 ? (
          <article className="action-card">
            <span className="pill amber">需要你确认</span>
            <h2>{taskTitle(task)}</h2>
            <p>
              发现 <strong>{task.diff_count} 个问题</strong>，其中 {task.high_risk_count} 个需要优先关注，
              还有 {task.pending_review_count} 个等待确认。
            </p>
            <button
              className="primary btn-lg"
              type="button"
              onClick={() => nav(`/tasks/${task.id}`)}
            >
              继续处理
            </button>
            <div className="flex" style={{ marginTop: 16 }}>
              <button className="link" type="button" onClick={() => nav(`/tasks/${task.id}`)}>
                查看全部问题 →
              </button>
            </div>
          </article>
        ) : !task ? (
          <div className="panel">
            <div className="panel-hd">暂无待办</div>
            <div className="panel-bd">
              <p className="panel-tip" style={{ margin: 0 }}>
                点击「重置并加载演示数据」快速体验采购样例，或前往
                <Link to="/tasks/new"> 创建任务 </Link>
                选择制度并开始检查。
              </p>
            </div>
          </div>
        ) : (
          <div className="panel">
            <div className="panel-hd">最近任务无待复核差异</div>
            <div className="panel-bd">
              <p className="panel-tip" style={{ margin: 0 }}>
                最新检查「{taskTitle(task)}」暂未发现问题，或所有问题均已处理。
                {data && data.pending_reviews > 0
                  ? ` 另有 ${data.pending_reviews} 条待复核差异在其他历史任务中，见下方列表。`
                  : " 可新建任务或加载演示数据。"}
              </p>
            </div>
          </div>
        )}

        {recent.length > 0 && (
          <div className="panel">
            <div className="panel-hd">最近检查</div>
            <div className="panel-bd" style={{ padding: 0 }}>
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>任务名称</th>
                      <th>问题</th>
                      <th>待确认</th>
                      <th>状态</th>
                      <th style={{ width: 140 }}>操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recent.map((t) => (
                      <tr key={t.id}>
                        <td>
                          <button className="link" type="button" onClick={() => nav(`/tasks/${t.id}`)}>
                            {taskTitle(t)}
                          </button>
                        </td>
                        <td>{t.diff_count}</td>
                        <td>{t.pending_review_count}</td>
                        <td><span className="pill gray">{taskStatus(t.status)}</span></td>
                        <td>
                          <div className="flex">
                            <button className="ghost sm" type="button" onClick={() => nav(`/tasks/${t.id}`)}>
                              查看
                            </button>
                            <button
                              className="ghost sm"
                              type="button"
                              disabled={deletingId === t.id || t.status === "running"}
                              onClick={() => handleDeleteTask(t)}
                            >
                              {deletingId === t.id ? "删除中" : "删除"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
