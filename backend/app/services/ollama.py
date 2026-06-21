import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.services.ollama_auth import ollama_auth


def _ollama_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    detail = (payload.get("error") or payload.get("detail")) if isinstance(payload, dict) else None
    return str(detail)[:500] if detail else None


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = settings.ollama_timeout_seconds

    def _auth(self) -> httpx.Auth | None:
        return ollama_auth()

    async def health(self) -> dict[str, str | bool]:
        try:
            async with httpx.AsyncClient(timeout=5.0, auth=self._auth()) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return {"status": "ok", "reachable": True}
        except httpx.HTTPError as exc:
            return {"status": "error", "reachable": False, "detail": str(exc)}

    async def list_models(self) -> list[dict[str, str | bool]]:
        try:
            async with httpx.AsyncClient(timeout=5.0, auth=self._auth()) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Ollama timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _ollama_error_detail(exc.response)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Ollama server error: {detail}" if detail else "Ollama server error",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ollama server error",
            ) from exc

        models = []
        for item in data.get("models", []):
            name = item.get("name") or item.get("model")
            if name:
                models.append(
                    {
                        "name": name,
                        "selected": name == self.model or item.get("model") == self.model,
                    }
                )
        return models

    async def chat(self, messages: list[dict[str, object]], model: str | None = None) -> str:
        payload = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, auth=self._auth()) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Ollama timeout",
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = _ollama_error_detail(exc.response)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Ollama server error: {detail}" if detail else "Ollama server error",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ollama server error",
            ) from exc

        content = data.get("message", {}).get("content")
        if not content:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ollama returned an empty response",
            )
        return content

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        embedding_model = model or settings.rag_embedding_model
        if not embedding_model:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout, auth=self._auth()) as client:
                response = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": embedding_model, "prompt": text},
                )
                if response.status_code == status.HTTP_404_NOT_FOUND:
                    response = await client.post(
                        f"{self.base_url}/api/embed",
                        json={"model": embedding_model, "input": text},
                    )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Ollama embedding timeout",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ollama embedding server error",
            ) from exc

        embedding = data.get("embedding")
        if embedding is None:
            embeddings = data.get("embeddings") or []
            embedding = embeddings[0] if embeddings else None
        if not embedding:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ollama returned an empty embedding",
            )
        return [float(value) for value in embedding]

    async def extract_json(self, prompt: str, model: str | None = None) -> str:
        return await self.chat(
            [
                {
                    "role": "system",
                    "content": "Vracej pouze validni JSON bez markdownu, komentaru a vysvetleni.",
                },
                {"role": "user", "content": prompt},
            ],
            model=model,
        )

    async def extract_json_with_images(self, prompt: str, images: list[str], model: str | None = None) -> str:
        return await self.chat(
            [
                {
                    "role": "system",
                    "content": "Vracej pouze validni JSON bez markdownu, komentaru a vysvetleni.",
                },
                {"role": "user", "content": prompt, "images": images},
            ],
            model=model,
        )
