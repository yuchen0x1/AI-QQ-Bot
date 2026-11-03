"""多供应商 AI 客户端实现：OpenAI 兼容 / Anthropic / Gemini / Ollama。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.http import new_client

logger = logging.getLogger("qbot.ai")

DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "anthropic": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "ollama": "http://localhost:11434",
    "custom": "",
}

PROVIDER_PRESETS = [
    {"kind": "openai", "name": "OpenAI", "base_url": DEFAULT_BASE_URLS["openai"], "needs_key": True},
    {"kind": "deepseek", "name": "DeepSeek", "base_url": DEFAULT_BASE_URLS["deepseek"], "needs_key": True},
    {"kind": "qwen", "name": "通义千问 Qwen", "base_url": DEFAULT_BASE_URLS["qwen"], "needs_key": True},
    {"kind": "moonshot", "name": "Moonshot Kimi", "base_url": DEFAULT_BASE_URLS["moonshot"], "needs_key": True},
    {"kind": "gemini", "name": "Google Gemini", "base_url": DEFAULT_BASE_URLS["gemini"], "needs_key": True},
    {"kind": "anthropic", "name": "Anthropic Claude", "base_url": DEFAULT_BASE_URLS["anthropic"], "needs_key": True},
    {"kind": "ollama", "name": "Ollama 本地模型", "base_url": DEFAULT_BASE_URLS["ollama"], "needs_key": False},
    {"kind": "custom", "name": "自定义兼容接口", "base_url": "", "needs_key": False},
]


class AIError(RuntimeError):
    pass


class AITimeout(AIError):
    pass


@dataclass
class ChatResult:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _estimate_tokens(text: str) -> int:
    # 粗略估算：中文约 1.5 字/token，英文约 4 字符/token
    if not text:
        return 0
    return max(1, int(len(text) / 2))


class BaseAIProvider:
    kind = "base"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model_name: str,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URLS.get(self.kind, "")).rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    async def chat(self, messages: list[dict[str, str]], system: str | None = None) -> ChatResult:
        raise NotImplementedError

    async def ping(self) -> str:
        result = await self.chat([{"role": "user", "content": "ping"}], system="只回复 pong")
        return result.content

    # ------------------------------------------------------------------
    async def _post(self, url: str, *, headers: dict[str, str], json_body: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            async with new_client(timeout=self.timeout) as client:
                response = await client.post(url, headers={**self.extra_headers, **headers}, json=json_body)
        except httpx.TimeoutException as exc:
            raise AITimeout(f"请求超时（{self.timeout}s）：{exc}") from exc
        except httpx.HTTPError as exc:
            raise AIError(f"网络错误：{exc}") from exc
        elapsed = int((time.perf_counter() - started) * 1000)
        if response.status_code >= 400:
            body = response.text[:500]
            raise AIError(f"HTTP {response.status_code}: {body}")
        try:
            data = response.json()
        except ValueError as exc:
            raise AIError("返回内容不是合法 JSON") from exc
        data["_elapsed_ms"] = elapsed
        return data


class OpenAICompatibleProvider(BaseAIProvider):
    """OpenAI / DeepSeek / Qwen / Moonshot / 自定义兼容接口。"""

    def _endpoint(self) -> str:
        base = self.base_url
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1") or base.endswith("/compatible-mode/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    async def chat(self, messages: list[dict[str, str]], system: str | None = None) -> ChatResult:
        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = await self._post(
            self._endpoint(),
            headers=headers,
            json_body={
                "model": self.model_name,
                "messages": payload_messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
            },
        )
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"响应结构异常：{str(data)[:300]}") from exc
        if isinstance(content, list):  # 部分实现返回分段内容
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or _estimate_tokens("".join(m["content"] for m in payload_messages)))
        completion_tokens = int(usage.get("completion_tokens") or _estimate_tokens(content or ""))
        return ChatResult(
            content=content or "",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model=data.get("model") or self.model_name,
            latency_ms=int(data.get("_elapsed_ms") or 0),
            raw=data,
        )


class AnthropicProvider(BaseAIProvider):
    async def chat(self, messages: list[dict[str, str]], system: str | None = None) -> ChatResult:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        }
        body: dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "messages": messages,
        }
        if system:
            body["system"] = system
        data = await self._post(f"{self.base_url}/v1/messages", headers=headers, json_body=body)
        blocks = data.get("content") or []
        content = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        usage = data.get("usage") or {}
        return ChatResult(
            content=content,
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
            model=data.get("model") or self.model_name,
            latency_ms=int(data.get("_elapsed_ms") or 0),
            raw=data,
        )


class GeminiProvider(BaseAIProvider):
    async def chat(self, messages: list[dict[str, str]], system: str | None = None) -> ChatResult:
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature, "maxOutputTokens": self.max_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"{self.base_url}/v1beta/models/{self.model_name}:generateContent?key={self.api_key or ''}"
        data = await self._post(url, headers={"Content-Type": "application/json"}, json_body=body)
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError(f"响应结构异常：{str(data)[:300]}") from exc
        usage = data.get("usageMetadata") or {}
        return ChatResult(
            content=content,
            prompt_tokens=int(usage.get("promptTokenCount") or 0),
            completion_tokens=int(usage.get("candidatesTokenCount") or 0),
            model=self.model_name,
            latency_ms=int(data.get("_elapsed_ms") or 0),
            raw=data,
        )


class OllamaProvider(BaseAIProvider):
    async def chat(self, messages: list[dict[str, str]], system: str | None = None) -> ChatResult:
        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)
        data = await self._post(
            f"{self.base_url}/api/chat",
            headers={"Content-Type": "application/json"},
            json_body={
                "model": self.model_name,
                "messages": payload_messages,
                "stream": False,
                "options": {"temperature": self.temperature, "num_predict": self.max_tokens},
            },
        )
        content = (data.get("message") or {}).get("content") or ""
        return ChatResult(
            content=content,
            prompt_tokens=int(data.get("prompt_eval_count") or 0),
            completion_tokens=int(data.get("eval_count") or 0),
            model=data.get("model") or self.model_name,
            latency_ms=int(data.get("_elapsed_ms") or 0),
            raw=data,
        )


PROVIDER_CLASSES: dict[str, type[BaseAIProvider]] = {
    "openai": OpenAICompatibleProvider,
    "deepseek": OpenAICompatibleProvider,
    "qwen": OpenAICompatibleProvider,
    "moonshot": OpenAICompatibleProvider,
    "custom": OpenAICompatibleProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
}


def build_provider(
    kind: str,
    *,
    base_url: str,
    api_key: str | None,
    model_name: str,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: float = 60.0,
    extra_headers: dict[str, str] | None = None,
) -> BaseAIProvider:
    cls = PROVIDER_CLASSES.get(kind, OpenAICompatibleProvider)
    return cls(
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        extra_headers=extra_headers,
    )
