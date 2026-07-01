import { memo } from "react";

const STEPS = [
  { id: 1, title: "检查文件", sub: "确认内容可正常读取" },
  { id: 2, title: "梳理条款", sub: "识别职责与控制要求" },
  { id: 3, title: "发现问题", sub: "逐项检查制度内容" },
  { id: 4, title: "专业复核", sub: "复核重点与疑难问题" },
  { id: 5, title: "核对依据", sub: "确认原文与判断一致" },
  { id: 6, title: "整理结果", sub: "生成问题与整改建议" },
];

export default memo(function PipelineSteps({
  currentStep,
  running,
}: {
  currentStep: number;
  running?: boolean;
}) {
  return (
    <div className="pipeline" aria-label="制度检查进度">
      {STEPS.map((s) => {
        let cls = "step-card";
        if (currentStep > 0 && s.id < currentStep) cls += " done";
        else if (currentStep > 0 && s.id === currentStep) {
          cls += " current";
          if (running) cls += " running";
        }
        return (
          <div key={s.id} className={cls} data-step={s.id}>
            <div className="step-no">{s.id}</div>
            <strong>{s.title}</strong>
            <span className="sub">{s.sub}</span>
          </div>
        );
      })}
    </div>
  );
});
