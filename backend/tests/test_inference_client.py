import json

import httpx
import pytest
from fastapi import HTTPException

from app.services.ollama import OllamaClient
from app.services.ollama_servers import OllamaServerConfig


def mock_http(monkeypatch, handler):
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )


def openai_client(base_url="http://inference:8000", **kwargs):
    return OllamaClient(OllamaServerConfig("server_1", "GPU", base_url, api_type="openai", **kwargs))


@pytest.mark.asyncio
@pytest.mark.parametrize("base_url", ["http://inference:8000", "http://inference:8000/v1/"])
async def test_openai_model_discovery_and_bearer_auth(monkeypatch, base_url):
    def handler(request):
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(200, json={"data": [{"id": "/models/qwen.gguf"}]})

    mock_http(monkeypatch, handler)
    client = openai_client(base_url, api_key="test-key")
    assert await client.list_models() == [{"name": "/models/qwen.gguf", "selected": False}]
    assert (await client.health())["reachable"] is True


@pytest.mark.asyncio
async def test_multimodal_structuring_converts_images_without_mutating_messages(monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "/models/qwen.gguf"
        assert payload["stream"] is False
        assert payload["messages"][-1]["content"] == [
            {"type": "text", "text": "OCR text"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,cG5n"}},
        ]
        assert "images" not in payload["messages"][-1]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"total":123}'}}]})

    mock_http(monkeypatch, handler)
    images = ["cG5n"]
    answer = await openai_client().extract_json_with_images("OCR text", images, model="/models/qwen.gguf")
    assert answer == '{"total":123}'
    assert images == ["cG5n"]


@pytest.mark.asyncio
async def test_openai_chat_ignores_separate_reasoning(monkeypatch):
    def handler(request):
        payload = json.loads(request.content)
        assert payload["messages"] == [{"role": "user", "content": "Ahoj"}]
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ahoj", "reasoning_content": "internal"}}]})

    mock_http(monkeypatch, handler)
    assert await openai_client().chat([{"role": "user", "content": "Ahoj"}], model="qwen") == "Ahoj"


@pytest.mark.asyncio
async def test_openai_embedding_uses_dedicated_model(monkeypatch):
    def handler(request):
        assert request.url.path == "/v1/embeddings"
        assert json.loads(request.content) == {"model": "embedder", "input": "receipt", "encoding_format": "float"}
        return httpx.Response(200, json={"data": [{"embedding": [0.25, -0.5]}]})

    mock_http(monkeypatch, handler)
    assert await openai_client().embed("receipt", model="embedder") == [0.25, -0.5]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}])
async def test_openai_rejects_missing_chat_content(monkeypatch, payload):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=payload))
    with pytest.raises(HTTPException) as error:
        await openai_client().chat([], model="qwen")
    assert error.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 404, 500])
async def test_openai_upstream_errors_do_not_expose_response_body(monkeypatch, status_code):
    mock_http(monkeypatch, lambda request: httpx.Response(status_code, text="sensitive response"))
    with pytest.raises(HTTPException) as error:
        await openai_client().chat([], model="qwen")
    assert error.value.status_code == 502
    assert "sensitive" not in error.value.detail


@pytest.mark.asyncio
async def test_openai_timeout_maps_to_gateway_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    mock_http(monkeypatch, handler)
    with pytest.raises(HTTPException) as error:
        await openai_client().chat([], model="qwen")
    assert error.value.status_code == 504


@pytest.mark.asyncio
async def test_ollama_protocol_is_preserved(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/chat"
        assert json.loads(request.content)["messages"][0]["content"] == "Ahoj"
        return httpx.Response(200, json={"message": {"content": "Ahoj"}})

    mock_http(monkeypatch, handler)
    client = OllamaClient(OllamaServerConfig("server_2", "CPU", "http://cpu:11434"))
    assert await client.chat([{"role": "user", "content": "Ahoj"}], model="qwen") == "Ahoj"


@pytest.mark.asyncio
async def test_openai_reranking_fails_with_actionable_error():
    with pytest.raises(HTTPException) as error:
        await openai_client().rerank_score("query", "document", "reranker")
    assert error.value.status_code == 422
    assert "Ollama" in error.value.detail
