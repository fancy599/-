import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api, subscribePipeline, type PipelineLog } from "../api/client";

const STORAGE_KEY = "ic_pipeline_task_id";

type CreateParams = {
  taskName: string;
  groupId: number;
  subId: number;
  businessDomain: string;
};

type PipelineContextValue = {
  taskId: number | null;
  running: boolean;
  step: number;
  logs: string[];
  statusHint: string;
  elapsed: number;
  errorMsg: string;
  clearError: () => void;
  createAndRun: (params: CreateParams) => Promise<number | null>;
};

const PipelineContext = createContext<PipelineContextValue | null>(null);

function formatLogs(items: PipelineLog[]): string[] {
  return items.map((l) => `[${l.agent_name}] ${l.message}`);
}

export function PipelineProvider({ children }: { children: ReactNode }) {
  const [taskId, setTaskId] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState(0);
  const [logs, setLogs] = useState<string[]>([]);
  const [statusHint, setStatusHint] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");

  const unsubRef = useRef<(() => void) | null>(null);
  const pollRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);
  const stepRef = useRef(0);
  const watchingIdRef = useRef<number | null>(null);

  const stopWatch = useCallback(() => {
    unsubRef.current?.();
    unsubRef.current = null;
    if (pollRef.current) window.clearInterval(pollRef.current);
    pollRef.current = null;
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    watchingIdRef.current = null;
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  const finishRun = useCallback(
    (hint: string) => {
      setRunning(false);
      setStatusHint(hint);
      stopWatch();
    },
    [stopWatch]
  );

  const bumpStep = useCallback((next: number) => {
    const v = Math.max(0, Math.min(6, Number(next) || 0));
    if (v > stepRef.current) {
      stepRef.current = v;
      setStep(v);
    }
  }, []);

  const applyPipelineLogs = useCallback((items: PipelineLog[]) => {
    if (!items.length) return;
    const lines = formatLogs(items);
    setLogs((prev) => {
      if (prev.length === lines.length && prev.every((l, i) => l === lines[i])) return prev;
      return lines;
    });
  }, []);

  const beginWatch = useCallback(
    (id: number) => {
      if (watchingIdRef.current === id && unsubRef.current) return;

      stopWatch();
      watchingIdRef.current = id;
      sessionStorage.setItem(STORAGE_KEY, String(id));
      setTaskId(id);
      setRunning(true);
      stepRef.current = 0;
      setStep(0);
      setLogs([]);
      setErrorMsg("");
      setStatusHint("正在后台检查制度，可以先去处理其他工作");

      if (timerRef.current) window.clearInterval(timerRef.current);
      timerRef.current = window.setInterval(() => setElapsed((s) => s + 1), 1000);
      setElapsed(0);

      const onEvent = (ev: Record<string, unknown>) => {
        if (ev.type === "ping" || ev.type === "connected") return;
        if (ev.step) bumpStep(Number(ev.step));
        if (ev.message) {
          const line = `[${ev.agent_name}] ${ev.message}`;
          setLogs((prev) => (prev.includes(line) ? prev : [...prev, line]));
        }
        if (ev.status === "failed") {
          setErrorMsg(String(ev.message || "制度检查未完成"));
          finishRun("");
        }
        if (ev.status === "done" || (ev.agent_name === "Orchestrator" && ev.status === "done")) {
          bumpStep(6);
          finishRun("制度检查已完成，可以查看问题清单");
        }
      };

      unsubRef.current = subscribePipeline(id, onEvent);

      const poll = async () => {
        try {
          const t = await api.task(id);
          if (t.current_step) bumpStep(t.current_step);
          const plogs = await api.pipelineLogs(id);
          applyPipelineLogs(plogs);
          if (t.status === "reviewing") {
            bumpStep(6);
            finishRun("制度检查已完成，可以查看问题清单");
          }
          if (t.status === "failed") {
            setErrorMsg(t.pipeline_error || "制度检查未完成");
            finishRun("");
          }
        } catch {
          /* ignore transient errors */
        }
      };

      poll();
      pollRef.current = window.setInterval(poll, 2500);
    },
    [applyPipelineLogs, bumpStep, finishRun, stopWatch]
  );

  useEffect(() => {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    const id = Number(raw);
    if (!id) return;
    api
      .task(id)
      .then((t) => {
        if (t.status === "running") beginWatch(id);
        else sessionStorage.removeItem(STORAGE_KEY);
      })
      .catch(() => sessionStorage.removeItem(STORAGE_KEY));

    return () => {
      /* 不在卸载时关闭 SSE，流水线需在后台继续 */
    };
  }, [beginWatch]);

  useEffect(() => () => stopWatch(), [stopWatch]);

  const createAndRun = useCallback(
    async (params: CreateParams): Promise<number | null> => {
      if (running) {
        setErrorMsg("已有一项制度检查正在进行，请等待完成后再试");
        return null;
      }
      setErrorMsg("");
      try {
        const task = await api.createTask({
          task_name: params.taskName,
          business_domain: params.businessDomain,
          description: "",
          group_document_id: params.groupId,
          subsidiary_document_id: params.subId,
        });
        beginWatch(task.id);
        await new Promise((r) => setTimeout(r, 300));
        setStatusHint("正在逐项对照并复核重点问题，预计需要 1–2 分钟");
        await api.runTask(task.id, "hybrid");
        return task.id;
      } catch (e) {
        stopWatch();
        setRunning(false);
        setErrorMsg(String(e));
        return null;
      }
    },
    [beginWatch, running, stopWatch]
  );

  const value: PipelineContextValue = {
    taskId,
    running,
    step,
    logs,
    statusHint,
    elapsed,
    errorMsg,
    clearError: () => setErrorMsg(""),
    createAndRun,
  };

  return <PipelineContext.Provider value={value}>{children}</PipelineContext.Provider>;
}

export function usePipeline() {
  const ctx = useContext(PipelineContext);
  if (!ctx) throw new Error("usePipeline must be used within PipelineProvider");
  return ctx;
}
