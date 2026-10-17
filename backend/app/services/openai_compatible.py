import math

import httpx
from fastapi import HTTPException

from app.services.ollama_auth import ollama_auth
from app.services.ollama_servers import OllamaServerConfig


def api_url(server: OllamaServerConfig, endpoint: str) -> str:
    base = server.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"
    return f"{base}/{endpoint}"


def api_headers(server: OllamaServerConfig) -> dict[str, str]:
    return {"Authorization": f"Bearer {server.api_key}"} if server.api_key else {}


def chat_payload(messages: list[dict], model: str) -> dict:
    converted = []
    for message in messages:
        item = {key: value for key, value in message.items() if key != "images"}
        if message.get("images"):
            parts = [{"type": "text", "text": str(message.get("content") or "")}]
            for image in message["images"]:
                mime = "image/jpeg" if image.startswith("/9j/") else "image/png"
                url = image if image.startswith("data:") else f"data:{mime};base64,{image}"
                parts.append({"type": "image_url", "image_url": {"url": url}})
            item["content"] = parts
        converted.append(item)
    return {"model": model, "messages": converted, "stream": False}


def chat_content(data: dict) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Missing chat response content") from exc
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Empty chat response content")
    return content


class OpenAICompatibleClient:
    def __init__(self, server: OllamaServerConfig, timeout: float):
        self.server = server
        self.timeout = timeout

    async def request(self, endpoint: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        try:
            async with httpx.AsyncClient(
                timeout=timeout if timeout is not None else self.timeout,
                auth=ollama_auth(self.server),
                headers=api_headers(self.server),
            ) as client:
                url = api_url(self.server, endpoint)
                response = await client.get(url) if payload is None else await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data
        except httpx.TimeoutException as exc:
            raise HTTPException(504, "Inference server timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"Inference server returned HTTP {exc.response.status_code} for {endpoint}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, "Invalid or unavailable inference server response") from exc

    async def list_models(self, default_model: str) -> list[dict]:
        data = await self.request("models", timeout=5.0)
        try:
            return [{"name": item["id"], "selected": item["id"] == default_model} for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise HTTPException(502, "Invalid inference model list") from exc

    async def chat(self, messages: list[dict], model: str) -> str:
        data = await self.request("chat/completions", chat_payload(messages, model))
        try:
            return chat_content(data)
        except ValueError as exc:
            raise HTTPException(502, "Inference server returned an empty chat response") from exc

    async def embed(self, text: str, model: str) -> list[float]:
        data = await self.request("embeddings", {"model": model, "input": text, "encoding_format": "float"})
        try:
            embedding = [float(value) for value in data["data"][0]["embedding"]]
            if not embedding or not all(math.isfinite(value) for value in embedding):
                raise ValueError("Invalid embedding")
            return embedding
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HTTPException(502, "Inference server returned an invalid embedding") from exc
