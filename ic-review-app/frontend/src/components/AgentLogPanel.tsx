const AGENT_LABELS: Record<string, string> = {
  StructureEngine: "条款梳理助手",
  StandardControlLibrary: "标准控制点库",
  ControlRuleEngine: "控制要求检查助手",
  CoreAnalyser: "制度审查助手",
  SOEExpertAgent: "国企内控复核专家",
  DesignDefectRules: "制度完整性检查助手",
  EvidenceRules: "依据核对助手",
  ReportBuilder: "结果整理助手",
  Orchestrator: "检查进度",
};

type Props = {
  running: boolean;
  step?: number;
  logs: string[];
  statusHint?: string;
};

function parseLogLine(line: string): { agent: string; label: string; message: string } {
  const m = line.match(/^\[([^\]]+)\]\s*(.*)$/);
  if (!m) return { agent: "System", label: "系统", message: line };
  const agent = m[1];
  return { agent, label: AGENT_LABELS[agent] || agent, message: m[2] };
}

export default function AgentLogPanel({ running, logs, statusHint }: Props) {
  if (logs.length === 0) {
    return (
      <p className="agent-empty">
        {running ? statusHint || "正在准备检查…" : "开始检查后，这里会显示每一步的进展。"}
      </p>
    );
  }

  return (
    <div className="agent-stream">
      {logs.map((line, i) => {
        const { label, message } = parseLogLine(line);
        const isDone = message.includes("完成") || message.includes("✓");
        return (
          <div key={`${i}-${line.slice(0, 24)}`} className="agent-log">
            <div className="agent-name">{label}</div>
            <div>{isDone ? "✓ " : "▶ "}{message}</div>
          </div>
        );
      })}
    </div>
  );
}
