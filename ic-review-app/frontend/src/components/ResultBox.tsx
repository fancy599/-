import { Link } from "react-router-dom";
import type { Task } from "../api/client";

type Props = {
  task: Task;
  show: boolean;
};

export default function ResultBox({ task, show }: Props) {
  if (!show) return null;
  return (
    <div className="result-box show">
      <h3>制度检查已完成</h3>
      <p>已梳理需要关注的问题和对应依据，请进入问题清单逐项确认。</p>
      <div className="result-stats">
        <span>差异：{task.diff_count} 条</span>
        <span>高风险：{task.high_risk_count} 条</span>
        <span>待复核：{task.pending_review_count} 条</span>
      </div>
      <div className="flex" style={{ marginTop: 14 }}>
        <Link to={`/tasks/${task.id}`}>
          <button className="primary" type="button">查看问题清单</button>
        </Link>
      </div>
    </div>
  );
}
