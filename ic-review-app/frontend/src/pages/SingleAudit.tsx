import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import DocumentUploadPanel from "../components/DocumentUploadPanel";
import ScrollableSelect from "../components/ScrollableSelect";
import { api, STANDARD_CONTROL_DOMAINS, type Document } from "../api/client";

export default function SingleAudit() {
  const nav = useNavigate();
  const [docs, setDocs] = useState<Document[]>([]);
  const [documentId, setDocumentId] = useState<number | "">("");
  const [taskName, setTaskName] = useState("");
  const [businessDomain, setBusinessDomain] = useState("采购");
  const [msg, setMsg] = useState("");
  const [running, setRunning] = useState(false);
  const [source, setSource] = useState<"library" | "upload">("library");

  const selectedDoc = docs.find((d) => d.id === documentId);

  function loadDocs() {
    return api.documents().then((items) => {
      setDocs(items);
      return items;
    });
  }

  useEffect(() => {
    loadDocs().then((items) => {
      const first = items[0];
      if (first) {
        setDocumentId(first.id);
        setBusinessDomain(first.business_domain || "采购");
      } else {
        setSource("upload");
      }
    });
  }, []);

  function onDocUploaded(doc: Document) {
    loadDocs().then(() => {
      setDocumentId(doc.id);
      setBusinessDomain(doc.business_domain || "采购");
    });
    setSource("library");
    setTaskName(`单份制度体检：${doc.document_name}`);
    setMsg(`已导入并选中：${doc.document_name}`);
  }

  async function runAudit() {
    if (!documentId) {
      setMsg("请先从制度库选择，或上传一个制度文件");
      return;
    }
    setRunning(true);
    setMsg("");
    try {
      const task = await api.runSingleAudit({
        document_id: Number(documentId),
        task_name: taskName || (selectedDoc ? `单份制度体检：${selectedDoc.document_name}` : ""),
        business_domain: businessDomain,
        mode: "ai",
      });
      nav(`/tasks/${task.id}`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
      setRunning(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <div>
          <h1>单份制度体检</h1>
          <p>没有集团制度也能检查，快速发现职责、审批、监督和执行要求是否完整。</p>
        </div>
      </header>
      <div className="content">
        {msg && <div className="alert warn">{msg}</div>}

        <div className="stack-col">
          <div className="panel">
            <div className="panel-hd">
              <strong>选择待检查制度</strong>
              <span className="panel-hd-sub">适合制度起草、修订和发布前自查</span>
            </div>
            <div className="panel-bd">
              <div className="form-row">
                <label>制度来源</label>
                <div className="seg">
                  <button
                    type="button"
                    className={source === "library" ? "active" : ""}
                    onClick={() => setSource("library")}
                    disabled={running}
                  >
                    从制度库选择
                  </button>
                  <button
                    type="button"
                    className={source === "upload" ? "active" : ""}
                    onClick={() => setSource("upload")}
                    disabled={running}
                  >
                    上传新制度
                  </button>
                </div>
              </div>

              {source === "library" ? (
                <div className="form-row">
                  <label>制度文件</label>
                  <select
                    value={documentId}
                    onChange={(e) => {
                      const id = Number(e.target.value);
                      setDocumentId(id);
                      const doc = docs.find((item) => item.id === id);
                      if (doc) setBusinessDomain(doc.business_domain || "采购");
                    }}
                    disabled={running}
                  >
                    <option value="">请选择</option>
                    {docs.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.document_name}（{d.document_level === "group" ? "集团" : "子公司"}）
                      </option>
                    ))}
                  </select>
                  {docs.length === 0 && (
                    <p className="panel-tip" style={{ marginTop: 6 }}>制度库暂无制度，请切换到“上传新制度”。</p>
                  )}
                </div>
              ) : (
                <DocumentUploadPanel
                  embedded
                  documentLevel="subsidiary"
                  title="上传待检查制度"
                  onUploaded={onDocUploaded}
                />
              )}

              <div className="form-row">
                <label>标准控制点领域</label>
                <ScrollableSelect
                  value={businessDomain}
                  options={STANDARD_CONTROL_DOMAINS}
                  onChange={setBusinessDomain}
                  disabled={running}
                  ariaLabel="标准控制点领域"
                />
              </div>

              <div className="form-row">
                <label>任务名称</label>
                <input value={taskName} onChange={(e) => setTaskName(e.target.value)} disabled={running} />
              </div>

              <div className="audit-scope">
                <div className="audit-scope-title">这次会检查什么</div>
                <ul className="check-list">
                  <li>制度目的、适用范围和业务边界是否完整</li>
                  <li>归口、执行、审批、监督等职责是否明确</li>
                  <li>授权审批、不相容职责分离和决策机制是否健全</li>
                  <li>流程留痕、监督检查、整改闭环和例外处理是否完备</li>
                  <li>问责、解释、修订、生效机制及弹性表述是否合理</li>
                </ul>
              </div>

              <p className="panel-tip">
                深度体检（AI）：由大模型对每条标准控制点做全文语义覆盖判断，逐条识别责任主体、控制动作、审批授权、记录留痕和监督问责是否完备。
              </p>
              <button className="primary" type="button" disabled={running} onClick={runAudit}>
                {running ? "正在检查..." : "开始体检"}
              </button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
