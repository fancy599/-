import queue
import threading
from collections import defaultdict

# 线程安全队列：流水线在后台线程运行，SSE 在 asyncio 协程中读取
_subscribers: dict[int, list[queue.Queue]] = defaultdict(list)
_lock = threading.Lock()


def subscribe(task_id: int) -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=200)
    with _lock:
        _subscribers[task_id].append(q)
    return q


def unsubscribe(task_id: int, q: queue.Queue) -> None:
    with _lock:
        if task_id in _subscribers and q in _subscribers[task_id]:
            _subscribers[task_id].remove(q)


def publish_event(
    task_id: int,
    step: int,
    agent_name: str,
    status: str,
    message: str,
    progress: float,
) -> None:
    payload = {
        "task_id": task_id,
        "step": step,
        "step_name": _step_name(step),
        "agent_name": agent_name,
        "status": status,
        "message": message,
        "progress": progress,
    }
    with _lock:
        queues = list(_subscribers.get(task_id, []))
    for q in queues:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass


def _step_name(step: int) -> str:
    names = {
        1: "文件解析",
        2: "控制点抽取",
        3: "条款匹配",
        4: "差异判断",
        5: "证据校验",
        6: "报告生成",
    }
    return names.get(step, "")
