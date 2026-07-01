import { Link } from "react-router-dom";
import { usePipeline } from "../pipeline/PipelineContext";

export default function PipelineBanner() {
  const { running, taskId, step, elapsed, statusHint } = usePipeline();
  if (!running || !taskId) return null;

  const pct = Math.min(100, Math.round(((step || 1) / 6) * 100));

  return (
    <div className="pipeline-banner">
      <div className="pipeline-banner-inner">
        <strong>制度检查进行中</strong>
        <span>
          步骤 {step || 1}/6 · 约 {pct}% · {elapsed}s
        </span>
        <span className="pipeline-banner-hint">{statusHint || "可切换页面，后台将继续执行"}</span>
        <div className="pipeline-banner-actions">
          <Link to="/tasks/new">查看进度</Link>
          <Link to={`/tasks/${taskId}`}>差异清单</Link>
        </div>
      </div>
      <div className="pipeline-banner-bar">
        <div style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
