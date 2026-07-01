import json
import logging
import re
import time
from typing import Any

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    logger.debug("%s %s %s %s %s", run_id, hypothesis_id, location, message, data)


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        timeout: float | None = None,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.llm_api_key
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.temperature = settings.llm_temperature
        self._force_temp_one = False
        if not self.api_key or self.api_key == "sk-your-key-here":
            raise LLMError("LLM_API_KEY 未配置，请在 .env 中设置")
        self.fallback_model = (
            settings.llm_fallback_model.strip()
            if fallback_model is None
            else fallback_model.strip()
        )
        self.retry_backoff_seconds = max(0.0, settings.llm_retry_backoff_seconds)
        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=max(10.0, timeout if timeout is not None else settings.llm_timeout_seconds),
        )

    @staticmethod
    def _temperature_only_one(err: Exception) -> bool:
        msg = str(err).lower()
        return "temperature" in msg and ("only 1" in msg or "must be 1" in msg)

    def _build_request_kwargs(
        self,
        system: str,
        user: str,
        temperature: float | None,
        model: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        # 推理类模型可能不支持 json_object，失败时在调用处重试不带该参数
        kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    def complete_json(
        self,
        system: str,
        user: str,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        settings = get_settings()
        temps_to_try: list[float | None] = []
        if self._force_temp_one:
            temps_to_try.append(1.0)
        elif settings.llm_temperature is not None:
            temps_to_try.append(settings.llm_temperature)
        else:
            temps_to_try.extend([0.2, 1.0])

        last_err: Exception | None = None
        use_json_format = True
        active_model = self.model
        active_user = user

        for temp in temps_to_try:
            for attempt in range(max_retries + 1):
                try:
                    if attempt >= 1 and self.fallback_model:
                        active_model = self.fallback_model
                    if attempt >= 2 and len(user) > 6000:
                        active_user = (
                            user[:3000]
                            + "\n\n[系统降级提示：原上下文过长，以下保留末尾关键内容]\n\n"
                            + user[-3000:]
                        )
                    kwargs = self._build_request_kwargs(system, active_user, temp, active_model)
                    if not use_json_format:
                        kwargs.pop("response_format", None)
                    # region agent log
                    _debug_log(
                        "pre-fix",
                        "H29",
                        "llm.py:complete_json",
                        "llm attempt start",
                        {"model": active_model, "temperature": temp, "attempt": attempt, "use_json_format": use_json_format},
                    )
                    # endregion
                    t0 = time.time()
                    response = self._client.chat.completions.create(**kwargs)
                    content = response.choices[0].message.content or "{}"
                    # region agent log
                    _debug_log(
                        "pre-fix",
                        "H29",
                        "llm.py:complete_json",
                        "llm attempt success",
                        {"temperature": temp, "attempt": attempt, "duration_ms": int((time.time() - t0) * 1000)},
                    )
                    # endregion
                    return self._parse_json(content)
                except Exception as e:
                    last_err = e
                    # region agent log
                    _debug_log(
                        "pre-fix",
                        "H29",
                        "llm.py:complete_json",
                        "llm attempt error",
                        {"temperature": temp, "attempt": attempt, "error": str(e)[:500]},
                    )
                    # endregion
                    if self._temperature_only_one(e) and temp != 1.0:
                        self._force_temp_one = True
                        # region agent log
                        _debug_log(
                            "pre-fix",
                            "H31",
                            "llm.py:complete_json",
                            "switch to forced temperature=1.0",
                            {"model": self.model},
                        )
                        # endregion
                        break  # 换 temperature=1 再试
                    if "response_format" in str(e).lower() or "json_object" in str(e).lower():
                        use_json_format = False
                        continue
                    if attempt < max_retries and self.retry_backoff_seconds:
                        time.sleep(self.retry_backoff_seconds * (attempt + 1))
                    if attempt >= max_retries:
                        break

        msg = str(last_err or "")
        lowered = msg.lower()
        if "out of memory" in lowered or "cuda" in lowered and "memory" in lowered:
            raise LLMError("ERR_LLM_OOM: 本地算力暂时满载，任务已停止在当前步骤，请稍后从失败步骤继续") from last_err
        if "timeout" in lowered or "timed out" in lowered:
            raise LLMError("ERR_LLM_TIMEOUT: 大模型调用多次超时，当前步骤已安全停止，可稍后从失败步骤继续") from last_err
        raise LLMError(f"ERR_LLM_FAILED: 大模型调用失败: {last_err}") from last_err

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*", "", content)
            content = re.sub(r"\s*```$", "", content)
        data = json.loads(content)
        if not isinstance(data, dict):
            raise LLMError("LLM 返回非 JSON 对象")
        return data


class FakeLLMClient:
    """Used in tests — returns scripted responses per agent key in user prompt."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, max_retries: int = 2) -> dict[str, Any]:
        self.calls.append((system, user))
        aliases = [
            ("SOEInternalControlExpert", "国企内控专家复核"),
            ("SOEExpertAgent", "国企内控专家复核"),
            ("Core Analyser", "内控制度比对"),
            ("快速审查模式", "内控制度比对"),
        ]
        for marker, key in aliases:
            if marker in system and key in self.responses:
                return self.responses[key]

        for key, payload in self.responses.items():
            if key in system or key in user:
                return payload
        return self.responses.get("default", {"items": []})
