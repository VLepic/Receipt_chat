import asyncio
import copy
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.auth import UserManager
from app.core.config import settings
from app.core.db import async_session_maker
from app.core.make_admin import promote
from app.main import app
from app.models.inference import InferenceRoutingSettings
from app.schemas.processing import ProcessingOptions
from app.schemas.servers import ServerSettingsUpdate
from app.services.inference_routing import get_or_create_inference_routing, get_role_server, processing_options
from app.services.ollama import OllamaClient
from app.services.ollama_servers import get_routing_server
from app.services.server_settings import decrypt_credential, merge_server_settings


def register(client, *, admin=False):
    email = f"configuration-{uuid.uuid4()}@example.com"
    response = client.post("/api/auth/register", json={"email": email, "password": "StrongPass123"})
    assert response.status_code == 201, response.text
    if admin:
        asyncio.run(promote(email))
    response = client.post("/api/auth/login", data={"username": email, "password": "StrongPass123"})
    assert response.status_code == 204, response.text


async def routing_values():
    async with async_session_maker() as session:
        routing = await get_or_create_inference_routing(session)
        values = {column.name: copy.deepcopy(getattr(routing, column.name)) for column in routing.__table__.columns}
        await session.commit()
        return values


@pytest.fixture(autouse=True)
def restore_routing(monkeypatch):
    previous = asyncio.run(routing_values())

    async def models(self):
        return [{"name": "qwen", "selected": False}, {"name": "embedder", "selected": False}]

    monkeypatch.setattr(OllamaClient, "list_models", models)
    yield

    async def restore():
        async with async_session_maker() as session:
            routing = await session.get(InferenceRoutingSettings, "default")
            for field, value in previous.items():
                setattr(routing, field, value)
            await session.commit()

    asyncio.run(restore())


@pytest.fixture
def admin():
    with TestClient(app) as client:
        register(client, admin=True)
        yield client


def server_payload():
    return [
        {"id": "server_1", "name": "GPU", "enabled": True, "base_url": "http://gpu:8000", "api_type": "openai", "api_key": "test-api-key"},
        {"id": "server_2", "name": "CPU", "enabled": False, "base_url": "", "api_type": "ollama"},
    ]


def test_shared_configuration_requires_admin_and_masks_secrets(admin):
    response = admin.put("/api/inference/servers", json=server_payload())
    assert response.status_code == 200, response.text
    assert response.json()["server_settings"][0]["has_api_key"] is True
    assert "test-api-key" not in response.text
    assert "encrypted" not in response.text

    with TestClient(app) as client:
        register(client)
        assert client.get("/api/users/me").json()["is_superuser"] is False
        assert client.get("/api/inference").json()["server_settings"] == []
        assert client.put("/api/inference/servers", json=server_payload()).status_code == 403
        assert client.put("/api/inference/processing", json=ProcessingOptions().model_dump()).status_code == 403
        routing = admin.get("/api/inference").json()["routing"]
        assert client.put("/api/inference", json=routing).status_code == 403

    with TestClient(app) as client:
        assert client.put("/api/inference/servers", json=server_payload()).status_code == 401


def test_server_credentials_are_encrypted_and_used_from_database(admin):
    assert admin.put("/api/inference/servers", json=server_payload()).status_code == 200
    stored = asyncio.run(routing_values())["server_configs"][0]
    assert stored["api_key_encrypted"] != "test-api-key"
    assert decrypt_credential(stored["api_key_encrypted"]) == "test-api-key"

    async def role_server():
        async with async_session_maker() as session:
            return await get_role_server(session, "chat")

    server = asyncio.run(role_server())
    assert server.base_url == "http://gpu:8000"
    assert server.api_type == "openai"
    assert server.api_key == "test-api-key"

    payload = admin.get("/api/inference").json()["server_settings"]
    payload[0]["name"] = "Renamed GPU"
    assert admin.put("/api/inference/servers", json=payload).status_code == 200
    assert asyncio.run(role_server()).api_key == "test-api-key"

    payload[0]["base_url"] = "http://different-gpu:8000"
    response = admin.put("/api/inference/servers", json=payload)
    assert response.status_code == 200
    assert response.json()["server_settings"][0]["has_api_key"] is False
    assert asyncio.run(role_server()).api_key is None


def test_empty_install_can_open_settings_without_model_server(admin):
    payload = server_payload()
    payload[0].update(enabled=False, api_key="")
    response = admin.put("/api/inference/servers", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["servers"] == []
    assert len(response.json()["server_settings"]) == 2
    assert admin.get("/api/chat/models").status_code == 422
    assert admin.put("/api/inference/processing", json=ProcessingOptions(ocr_engine="tesseract").model_dump()).status_code == 200


def test_lost_secret_does_not_prevent_reentering_credentials(admin, monkeypatch):
    assert admin.put("/api/inference/servers", json=server_payload()).status_code == 200
    email = admin.get("/api/users/me").json()["email"]
    monkeypatch.setattr(settings, "secret_key", "a-different-key")
    assert admin.post("/api/auth/login", data={"username": email, "password": "StrongPass123"}).status_code == 204
    response = admin.get("/api/inference")
    assert response.status_code == 200, response.text
    assert response.json()["servers"][0]["reachable"] is False
    assert response.json()["server_settings"][0]["has_api_key"] is True
    response = admin.put("/api/inference/servers", json=server_payload())
    assert response.status_code == 200, response.text
    assert response.json()["servers"][0]["reachable"] is True


def test_processing_settings_persist_and_validate_models(admin):
    assert admin.put("/api/inference/servers", json=server_payload()).status_code == 200
    options = ProcessingOptions(ocr_engine="tesseract", extraction_mode="text_only", rag_search_limit=7, reranker_candidate_limit=4, inference_timeout_seconds=90)
    response = admin.put("/api/inference/processing", json=options.model_dump())
    assert response.status_code == 200, response.text
    assert admin.get("/api/inference").json()["processing"] == options.model_dump()
    row = SimpleNamespace(processing_options=asyncio.run(routing_values())["processing_options"])
    assert processing_options(row) == options
    invalid = options.model_dump() | {"ocr_engine": "ollama", "ocr_model": "missing"}
    assert admin.put("/api/inference/processing", json=invalid).status_code == 422
    invalid["ocr_model"] = "qwen"
    assert admin.put("/api/inference/processing", json=invalid).status_code == 200
    invalid["inference_timeout_seconds"] = 0
    assert admin.put("/api/inference/processing", json=invalid).status_code == 422

    routing = admin.get("/api/inference").json()["routing"]
    routing.update(embedding_model=None, reranker_server_id=None)
    assert admin.put("/api/inference", json=routing).status_code == 200
    assert admin.get("/api/inference").json()["routing"]["embedding_model"] is None


def test_ocr_route_change_requires_a_model_available_on_new_server(admin, monkeypatch):
    async def models(self):
        return [{"name": "qwen" if self.server.id == "server_1" else "ocr-cpu", "selected": False}]

    monkeypatch.setattr(OllamaClient, "list_models", models)
    payload = server_payload()
    payload[1].update(enabled=True, base_url="http://cpu:11434")
    assert admin.put("/api/inference/servers", json=payload).status_code == 200
    options = ProcessingOptions(ocr_engine="ollama", ocr_model="qwen").model_dump()
    assert admin.put("/api/inference/processing", json=options).status_code == 200
    routing = admin.get("/api/inference").json()["routing"]
    routing["ocr_server_id"] = "server_2"
    assert admin.put("/api/inference", json=routing).status_code == 422
    routing["processing"] = options | {"ocr_model": "ocr-cpu"}
    response = admin.put("/api/inference", json=routing)
    assert response.status_code == 200, response.text
    assert response.json()["processing"]["ocr_model"] == "ocr-cpu"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://user:pass@server", "http://server:bad", "https://server?key=secret", "https://server/#secret"])
def test_server_urls_reject_embedded_credentials_and_invalid_addresses(url):
    with pytest.raises(ValidationError):
        ServerSettingsUpdate(id="server_1", name="GPU", enabled=True, base_url=url)


def test_explicitly_clearing_password_and_disabled_server_isolation():
    payload = ServerSettingsUpdate(id="server_1", name="CPU", enabled=True, base_url="http://cpu:11434", auth_scheme="basic", username="user", password="test-password")
    stored = merge_server_settings(payload, {})
    cleared = merge_server_settings(payload.model_copy(update={"password": ""}), stored)
    assert cleared["password_encrypted"] is None
    broken = stored | {"id": "server_2", "password_encrypted": "invalid", "enabled": False}
    server = get_routing_server(SimpleNamespace(server_configs=[stored, broken]), "server_1")
    assert server.password == "test-password"


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_users", [0, 2])
async def test_only_first_registered_account_becomes_admin(monkeypatch, existing_users):
    from app.api import auth

    connection = SimpleNamespace(execute=AsyncMock())

    class ConnectionContext:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(auth, "engine", SimpleNamespace(connect=ConnectionContext))
    user = SimpleNamespace(is_superuser=False)
    database = SimpleNamespace(session=SimpleNamespace(scalar=AsyncMock(return_value=existing_users)), update=AsyncMock(return_value=user))
    monkeypatch.setattr(auth.BaseUserManager, "create", AsyncMock(return_value=user))
    await UserManager(database).create(SimpleNamespace(), safe=True)
    assert database.update.await_count == (1 if existing_users == 0 else 0)
    assert connection.execute.await_count == 2


@pytest.mark.asyncio
async def test_default_model_is_discovered_and_timeout_is_configurable():
    from app.services.ollama_servers import OllamaServerConfig

    client = OllamaClient(OllamaServerConfig("server_1", "GPU", "http://gpu:8000", api_type="openai"), timeout=42)
    client.model = ""
    assert await client.resolve_model() == "qwen"
    assert client.timeout == 42
    assert await client.resolve_model("explicit") == "explicit"
