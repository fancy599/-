"""百度智能云·文档解析（PaddleOCR-VL）客户端。

用 AK/SK 换取 access_token，提交 PDF（base64）→ 轮询任务 → 取解析结果（逐页 text，
表格已是 markdown）。供 PDF 制度上传时优先用模型解析，失败由调用方回退本地解析。

接口（官方）：
  鉴权:  POST https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id=AK&client_secret=SK
  提交:  POST .../rest/2.0/brain/online/v2/parser/task         (form: file_data=base64, file_name)
  查询:  POST .../rest/2.0/brain/online/v2/parser/task/query   (form: task_id)  -> status / parse_result_url / markdown_url
"""
from __future__ import annotations

import base64
import logging
import threading
import time
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class BaiduDocParserError(Exception):
    """百度文档解析调用失败。"""


# access_token 缓存（进程内，含过期时间）。
_token_lock = threading.Lock()
_token_cache: dict[str, float | str] = {"value": "", "expire_at": 0.0}


def _get_access_token() -> str:
    settings = get_settings()
    ak = settings.baidu_ocr_api_key.strip()
    sk = settings.baidu_ocr_secret_key.strip()
    if not ak or not sk:
        raise BaiduDocParserError("未配置 BAIDU_OCR_API_KEY / BAIDU_OCR_SECRET_KEY")

    now = time.time()
    with _token_lock:
        if _token_cache["value"] and float(_token_cache["expire_at"]) > now + 60:
            return str(_token_cache["value"])

    resp = httpx.post(
        settings.baidu_oauth_url,
        params={"grant_type": "client_credentials", "client_id": ak, "client_secret": sk},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise BaiduDocParserError(f"获取 access_token 失败：{data.get('error_description') or data}")
    expires_in = float(data.get("expires_in", 2592000))
    with _token_lock:
        _token_cache["value"] = token
        _token_cache["expire_at"] = now + expires_in
    return token


def _submit_task(token: str, file_path: Path) -> str:
    settings = get_settings()
    file_b64 = base64.b64encode(file_path.read_bytes()).decode("ascii")
    resp = httpx.post(
        settings.baidu_doc_parser_submit_url,
        params={"access_token": token},
        data={"file_data": file_b64, "file_name": file_path.name},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=settings.baidu_doc_parser_timeout_seconds,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("error_code"):
        raise BaiduDocParserError(f"提交解析任务失败 [{data.get('error_code')}]：{data.get('error_msg')}")
    task_id = (data.get("result") or {}).get("task_id")
    if not task_id:
        raise BaiduDocParserError(f"提交解析任务未返回 task_id：{data}")
    return task_id


def _poll_result(token: str, task_id: str) -> dict:
    settings = get_settings()
    deadline = time.time() + settings.baidu_doc_parser_timeout_seconds
    interval = max(2.0, settings.baidu_doc_parser_poll_interval)
    while time.time() < deadline:
        resp = httpx.post(
            settings.baidu_doc_parser_query_url,
            params={"access_token": token},
            data={"task_id": task_id},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=settings.baidu_doc_parser_timeout_seconds,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error_code"):
            raise BaiduDocParserError(f"查询解析结果失败 [{data.get('error_code')}]：{data.get('error_msg')}")
        result = data.get("result") or {}
        status = result.get("status")
        if status == "success":
            return result
        if status == "failed":
            raise BaiduDocParserError(f"解析任务失败：{result.get('task_error') or '未知错误'}")
        time.sleep(interval)
    raise BaiduDocParserError("解析超时，请稍后重试或回退本地解析")


def _text_from_result(result: dict) -> str:
    """优先用 parse_result_url 的逐页 text（含 markdown 表格）；缺失时回退 markdown_url。"""
    parse_url = result.get("parse_result_url")
    if parse_url:
        resp = httpx.get(parse_url, timeout=60.0)
        resp.raise_for_status()
        payload = resp.json()
        pages = payload.get("pages") or []
        parts = [(p.get("text") or "").strip() for p in pages]
        text = "\n\n".join(part for part in parts if part)
        if text.strip():
            return text
    markdown_url = result.get("markdown_url")
    if markdown_url:
        resp = httpx.get(markdown_url, timeout=60.0)
        resp.raise_for_status()
        return resp.text
    raise BaiduDocParserError("解析结果链接为空（无 parse_result_url / markdown_url）")


def parse_pdf(file_path: str) -> str:
    """提交 PDF 给百度文档解析并返回纯文本（表格保留为 markdown）。失败抛 BaiduDocParserError。"""
    path = Path(file_path)
    if not path.exists():
        raise BaiduDocParserError(f"文件不存在：{file_path}")
    token = _get_access_token()
    task_id = _submit_task(token, path)
    logger.info("百度文档解析任务已提交：%s", task_id)
    result = _poll_result(token, task_id)
    return _text_from_result(result)
