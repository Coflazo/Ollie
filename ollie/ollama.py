"""Thin async client for the local Ollama API.

Deliberately small. Ollie needs five things from Ollama — is it alive, what is installed,
generate, generate-as-JSON, and embed — and wrapping more than that would be inventing a
dependency we then have to maintain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx

from . import config


class OllamaDown(RuntimeError):
    """Ollama is not reachable. The UI turns this into 'start Ollama', not a stack trace."""


@dataclass
class ModelInfo:
    tag: str
    size_bytes: int
    family: str = ""

    @property
    def size_gb(self) -> float:
        return self.size_bytes / 1e9


class Ollama:
    def __init__(self, base_url: str | None = None, timeout: float = 300.0) -> None:
        self.base = (base_url or config.OLLAMA_URL).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def version(self) -> str:
        try:
            r = await self._client.get(f"{self.base}/api/version", timeout=5)
            r.raise_for_status()
            return r.json().get("version", "unknown")
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaDown(str(exc)) from exc

    async def alive(self) -> bool:
        try:
            await self.version()
            return True
        except OllamaDown:
            return False

    async def tags(self) -> list[ModelInfo]:
        try:
            r = await self._client.get(f"{self.base}/api/tags", timeout=15)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaDown(str(exc)) from exc
        return [
            ModelInfo(m["name"], m.get("size", 0),
                      (m.get("details") or {}).get("family", ""))
            for m in r.json().get("models", [])
        ]

    async def chat(self, model: str, messages: list[dict], *, temperature: float = 0.85,
                   num_ctx: int = 4096, schema: dict | None = None,
                   stop: list[str] | None = None) -> str:
        """One completion. `schema` switches Ollama into constrained JSON output."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": num_ctx,
                # Repetition is the most visible failure mode on small models, and a
                # character with verbal tics needs the penalty low enough to keep them.
                "repeat_penalty": 1.08,
                "top_p": 0.92,
            },
        }
        if stop:
            payload["options"]["stop"] = stop
        if schema is not None:
            payload["format"] = schema
            payload["options"]["temperature"] = 0.1
        try:
            r = await self._client.post(f"{self.base}/api/chat", json=payload)
            r.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaDown(str(exc)) from exc
        return r.json()["message"]["content"]

    async def chat_json(self, model: str, messages: list[dict], schema: dict,
                        num_ctx: int = 4096) -> dict | None:
        """Structured output. Returns None rather than raising — a failed extraction must
        never take down the conversation that produced it."""
        try:
            raw = await self.chat(model, messages, schema=schema, num_ctx=num_ctx)
            return json.loads(raw)
        except (OllamaDown, json.JSONDecodeError, KeyError):
            return None

    async def stream(self, model: str, messages: list[dict], *, temperature: float = 0.85,
                     num_ctx: int = 4096) -> AsyncIterator[str]:
        payload = {
            "model": model, "messages": messages, "stream": True,
            "options": {"temperature": temperature, "num_ctx": num_ctx,
                        "repeat_penalty": 1.08, "top_p": 0.92},
        }
        async with self._client.stream("POST", f"{self.base}/api/chat",
                                       json=payload) as r:
            async for line in r.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if piece := chunk.get("message", {}).get("content"):
                    yield piece

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        r = await self._client.post(
            f"{self.base}/api/embed",
            json={"model": model or config.EMBED_MODEL, "input": texts},
        )
        r.raise_for_status()
        return r.json()["embeddings"]

    async def pull(self, tag: str) -> AsyncIterator[dict]:
        """Streams pull progress. Only ever called after the user approves a download."""
        async with self._client.stream("POST", f"{self.base}/api/pull",
                                       json={"model": tag}, timeout=None) as r:
            async for line in r.aiter_lines():
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


async def select_model(client: Ollama, tier: config.Tier,
                       override: str | None = None) -> tuple[str | None, list[str]]:
    """Pick the best installed model for this tier.

    Returns (chosen_tag, installed_tags). Never pulls: if nothing in the tier's preference
    list is installed, the caller shows the user what to download and waits for a yes.
    """
    installed = [m.tag for m in await client.tags()]
    if override:
        return (override if override in installed else override), installed

    for want in tier.candidates:
        for tag in installed:
            if tag == want or tag.startswith(want.split(":")[0] + ":") and want in tag:
                return tag, installed
    # Exact matches failed; accept a same-family tag before giving up.
    for want in tier.candidates:
        family = want.split(":")[0]
        for tag in installed:
            if tag.startswith(family + ":"):
                return tag, installed
    return None, installed
