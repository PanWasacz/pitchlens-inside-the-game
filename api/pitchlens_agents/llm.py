"""Minimal Azure OpenAI / Microsoft Foundry chat client (standard library only).

Configured from environment variables (App Service settings in Azure,
api/local.settings.json locally):

    AZURE_OPENAI_ENDPOINT     https://<resource>.openai.azure.com/  (or a Foundry
                              https://<resource>.services.ai.azure.com/ endpoint;
                              a URL ending in /openai/v1 uses the v1 API)
    AZURE_OPENAI_API_KEY      key of that resource
    AZURE_OPENAI_DEPLOYMENT   model deployment name, e.g. gpt-4o-mini
    AZURE_OPENAI_API_VERSION  optional, default below
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

DEFAULT_API_VERSION = "2024-10-21"

# Deployments known to be reasoning models, remembered across requests in this worker.
_REASONING: set[str] = set()


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, timeout: float = 20.0):
        self.endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip().rstrip("/")
        self.key = os.environ.get("AZURE_OPENAI_API_KEY", "").strip()
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "").strip()
        self.api_version = os.environ.get("AZURE_OPENAI_API_VERSION", DEFAULT_API_VERSION).strip()
        self.timeout = timeout
        # Switched on when the deployment rejects max_tokens / temperature.
        self.reasoning = self.deployment in _REASONING
        self.calls = 0
        self.tokens = 0

    @property
    def available(self) -> bool:
        return bool(self.endpoint and self.key and self.deployment)

    def _url(self) -> str:
        if self.endpoint.endswith("/openai/v1"):
            return f"{self.endpoint}/chat/completions"
        return f"{self.endpoint}/openai/deployments/{self.deployment}/chat/completions?api-version={self.api_version}"

    def chat(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 500,
        timeout: float | None = None,
    ) -> dict:
        """One chat completion; returns the assistant message dict."""
        for attempt in range(2):
            body: dict = {"messages": messages}
            if self.reasoning:
                # Reasoning models (o-series, gpt-5) reject max_tokens and custom temperature.
                body["max_completion_tokens"] = max_tokens * 4
            else:
                body["max_tokens"] = max_tokens
                body["temperature"] = temperature
            if self.endpoint.endswith("/openai/v1"):
                body["model"] = self.deployment
            if tools:
                body["tools"] = tools
                body["tool_choice"] = "auto"
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            req = urllib.request.Request(
                self._url(),
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "api-key": self.key},
                method="POST",
            )
            self.calls += 1
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:300]
                if e.code == 400 and attempt == 0 and not self.reasoning and ("max_tokens" in detail or "temperature" in detail):
                    self.reasoning = True
                    _REASONING.add(self.deployment)
                    continue
                raise LLMError(f"model returned HTTP {e.code}: {detail}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise LLMError(f"model unreachable: {e}") from e
        self.tokens += int(payload.get("usage", {}).get("total_tokens", 0))
        try:
            return payload["choices"][0]["message"]
        except (KeyError, IndexError) as e:
            raise LLMError("unexpected model response") from e

    def chat_json(self, messages: list[dict], **kw) -> dict:
        msg = self.chat(messages, json_mode=True, **kw)
        return parse_json(msg.get("content") or "")


def parse_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating code fences or extra prose."""
    text = text.strip()
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise LLMError("model did not return JSON")
        try:
            out = json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise LLMError("model did not return valid JSON") from e
    if not isinstance(out, dict):
        raise LLMError("model returned JSON that is not an object")
    return out


class Budget:
    """Wall-clock budget for one request, so the viewer never waits much longer than ~40 s."""

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + seconds

    @property
    def left(self) -> float:
        return self.deadline - time.monotonic()

    def allows(self, seconds: float) -> bool:
        return self.left > seconds
