import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AgentLogPanel from "../components/AgentLogPanel";
import DocumentUploadPanel from "../components/DocumentUploadPanel";
import PipelineSteps from "../components/PipelineSteps";
import ResultBox from "../components/ResultBox";
import { usePipeline } from "../pipeline/PipelineContext";
import {
  api,
  type Document,
  type Task,
  type TaskParsePreview,
} from "../api/client";

export default function TaskCreate() {
  const nav = useNavigate();
  const pipeline = usePipeline();
  const [docs, setDocs] = useState<Document[]>([]);
  const [taskName, setTaskName] = useState("");
  const [groupId, setGroupId] = useState<number | "">("");
  const [subId, setSubId] = useState<number | "">("");
  const [localMsg, setLocalMsg] = useState("");
  const [completedTask, setCompletedTask] = useState<Task | null>(null);
  const [parsePreview, setParsePreview] = useState<TaskParsePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const { taskId, running, step, logs, statusHint, elapsed, errorMsg, createAndRun, clearError } =
    pipeline;
  const msg = localMsg || errorMsg;

  const groupDoc = docs.find((d) => d.id === groupId);
  const subDoc = docs.find((d) => d.id === subId);
  const usableDocs = docs.filter((d) => d.parse_status === "parsed");

  function loadDocs() {
    return api.documents().then((d) => {
      setDocs(d);
      return d;
    });
  }

  useEffect(() => {
    loadDocs().then((d) => {
      const g = d.find((x) => x.document_level === "group" && x.parse_status === "parsed");
      const s = d.find((x) => x.document_level === "subsidiary" && x.parse_status === "parsed");
      if (g) setGroupId(g.id);
      if (s) setSubId(s.id);
    });
  }, []);

  useEffect(() => {
    if (!taskId || running || step < 6) return;
    api.task(taskId).then(setCompletedTask).catch(() => {});
  }, [taskId, running, step]);

  function onDocUploaded(doc: Document) {
    loadDocs().then(() => {
      if (doc.document_level === "group") setGroupId(doc.id);
      else setSubId(doc.id);
    });
    setLocalMsg(`已导入：${doc.document_name}`);
    setCompletedTask(null);
    setParsePreview(null);
  }

  async function handleCreateAndRun() {
    if (!groupId || !subId) {
      setLocalMsg("请选择集团与子公司的制度文档");
      return;
    }
    setLocalMsg("");
    setCompletedTask(null);
    setParsePreview(null);
    clearError();
    await createAndRun({
      taskName,
      groupId: Number(groupId),
      subId: Number(subId),
      businessDomain: groupDoc?.business_domain || subDoc?.business_domain || "采购",
    });
  }

  const progressPct = running ? Math.min(100, Math.round(((step || 1) / 6) * 100)) : step >= 6 ? 100 : 0;
  const displayStep = running ? (step || 1) : step;
  const progressLabel = running
    ? `正在进行第 ${displayStep} 步：${["", "检查文件", "梳理要求", "对照内容", "发现问题", "核对依据", "整理结果"][displayStep] || ""}`
    : step >= 6
      ? "检查已完成"
      : "准备就绪，确认制度后即可开始";

  async function handleLoadParsePreview() {
    if (!taskId) return;
    setPreviewLoading(true);
    try {
      const data = await api.taskParsePreview(taskId, 20, 320);
      setParsePreview(data);
    } catch (e) {
      setLocalMsg(`加载解析内容失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPreviewLoading(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>制度对照检查</h1>
          <p>
            选择集团制度和子公司制度，查看要求是否落实、内容是否存在遗漏。
          </p>
        </div>
      </header>
      <div className="content">
        {msg && <div className="alert warn">{msg}</div>}
        {running && (
          <div className="alert info">
            检查正在后台进行，离开本页不会中断。完成后可以逐项确认发现的问题。
          </div>
        )}

        <div className="stack-col">
            <div className="panel">
              <div className="panel-hd">
                <strong>选择要对照的制度</strong>
                <span className="panel-hd-sub">左侧是集团要求，右侧是待检查制度</span>
              </div>
              <div className="panel-bd">
                <div className="form-grid">
                  <div className="form-row">
                    <label>集团制度</label>
                    <select value={groupId} onChange={(e) => setGroupId(Number(e.target.value))} disabled={running}>
                      <option value="">请选择</option>
                      {usableDocs.filter((d) => d.document_level === "group").map((d) => (
                        <option key={d.id} value={d.id}>{d.document_name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-row">
                    <label>子公司制度</label>
                    <select value={subId} onChange={(e) => setSubId(Number(e.target.value))} disabled={running}>
                      <option value="">请选择</option>
                      {usableDocs.filter((d) => d.document_level === "subsidiary").map((d) => (
                        <option key={d.id} value={d.id}>{d.document_name}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="upload-panels-row">
                  <DocumentUploadPanel
                    documentLevel="group"
                    title="导入集团制度"
                    onUploaded={onDocUploaded}
                  />
                  <DocumentUploadPanel
                    documentLevel="subsidiary"
                    title="导入子公司制度"
                    onUploaded={onDocUploaded}
                  />
                </div>
                <Link to="/library" className="panel-inline-link">管理全部制度文件</Link>
              </div>
            </div>

            <div className="panel">
              <div className="panel-hd">
                <strong>为本次检查命名</strong>
                <span className="panel-hd-sub">{taskName || "未命名任务"}</span>
              </div>
              <div className="panel-bd">
                <div className="form-row">
                  <label>任务名称</label>
                  <input value={taskName} onChange={(e) => setTaskName(e.target.value)} disabled={running} />
                </div>
                <div className="alert info">
                  系统会先逐项对照制度内容，再由内控复核专家核对重点问题和引用依据。最终结论仍由你确认。
                </div>
              </div>
            </div>

            <div className="panel">
              <div className="panel-hd">
                <strong>检查进度</strong>
                <span className="panel-hd-sub">{progressLabel}</span>
              </div>
              <div className="panel-bd">
                <PipelineSteps currentStep={displayStep} running={running} />

                <div className="progress-line" aria-hidden="true">
                  <div style={{ width: `${progressPct}%` }} />
                </div>
                <div className="progress-text">{progressLabel}</div>

                {(running || logs.length > 0) && (
                  <AgentLogPanel running={running} step={displayStep} logs={logs} statusHint={statusHint} />
                )}

                <div className="flex" style={{ marginTop: 20 }}>
                  <button className="primary" type="button" disabled={running} onClick={handleCreateAndRun}>
                    {running ? `正在检查 ${elapsed} 秒…` : "开始制度检查"}
                  </button>
                  {taskId && !running && (
                    <button className="ghost" type="button" onClick={() => nav(`/tasks/${taskId}`)}>
                      查看问题清单
                    </button>
                  )}
                </div>

                {completedTask && <ResultBox task={completedTask} show />}
              </div>
            </div>

            {taskId && !running && (
              <div className="panel parse-preview-panel">
                <div className="panel-hd">
                  <strong>系统识别到的制度条款</strong>
                  <button
                    className="ghost sm"
                    type="button"
                    disabled={previewLoading}
                    onClick={handleLoadParsePreview}
                  >
                    {previewLoading ? "加载中…" : "查看识别结果"}
                  </button>
                </div>
                <div className="panel-bd">
                  {!parsePreview ? (
                    <p className="panel-tip">
                      点击“查看识别结果”，确认系统是否正确读取了两份制度的主要条款。
                    </p>
                  ) : (
                    <div className="parse-preview-grid">
                      <div>
                        <h4 className="parse-preview-title">
                          集团制度：{parsePreview.group_document_name}
                        </h4>
                        <div className="parse-preview-list">
                          {parsePreview.group_clauses.map((c) => (
                            <article key={`g-${c.id}`} className="parse-clause-card">
                              <div className="parse-clause-meta">
                                {c.location_label || `${c.chapter_title} ${c.clause_no}`.trim() || `条款 ${c.id}`}
                              </div>
                              <pre>{c.excerpt || "(空)"}</pre>
                            </article>
                          ))}
                        </div>
                      </div>
                      <div>
                        <h4 className="parse-preview-title">
                          子公司制度：{parsePreview.sub_document_name}
                        </h4>
                        <div className="parse-preview-list">
                          {parsePreview.sub_clauses.map((c) => (
                            <article key={`s-${c.id}`} className="parse-clause-card">
                              <div className="parse-clause-meta">
                                {c.location_label || `${c.chapter_title} ${c.clause_no}`.trim() || `条款 ${c.id}`}
                              </div>
                              <pre>{c.excerpt || "(空)"}</pre>
                            </article>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
        </div>
      </div>
    </>
  );
}
