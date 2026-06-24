import uuid

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.inference import _normalize_routing
from app.core.config import settings
from app.main import app
from app.models.settings import UserSettings
from app.services.chat_agent import sources_from_chunks


PASSWORD = "StrongPass123"


@pytest.fixture(autouse=True)
def disable_real_reranker(monkeypatch):
    async def passthrough(_session, _query, chunks):
        return chunks, False

    monkeypatch.setattr("app.services.chat_agent.rerank_document_chunks", passthrough)


def test_sources_use_reranker_best_band():
    user_settings = UserSettings(
        rag_source_strategy="best_band",
        rag_best_band=0.08,
        rag_reranker_best_band=0.10,
        rag_top_n=3,
    )
    chunks = [
        {"document_id": uuid.uuid4(), "filename": "a.pdf", "distance": 0.4, "reranker_score": 0.90},
        {"document_id": uuid.uuid4(), "filename": "b.pdf", "distance": 0.1, "reranker_score": 0.84},
        {"document_id": uuid.uuid4(), "filename": "c.pdf", "distance": 0.2, "reranker_score": 0.70},
    ]

    sources = sources_from_chunks(chunks, user_settings)

    assert [source["filename"] for source in sources] == ["a.pdf", "b.pdf"]


def _register_and_login(client: TestClient, email: str) -> None:
    register_response = client.post(
        "/api/auth/register",
        json={"email": email, "password": PASSWORD},
    )
    assert register_response.status_code in {200, 201}, register_response.text

    login_response = client.post(
        "/api/auth/login",
        data={"username": email, "password": PASSWORD},
    )
    assert login_response.status_code in {200, 204}, login_response.text
    assert "sp2_session" in client.cookies


def test_chat_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/chat/conversations")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_401"


def test_authenticated_user_can_create_and_read_conversation():
    email = f"user-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        create_response = client.post(
            "/api/chat/conversations",
            json={"title": "Faze 2 kontrakt"},
        )
        assert create_response.status_code == 201, create_response.text
        conversation = create_response.json()
        assert conversation["title"] == "Faze 2 kontrakt"
        assert conversation["messages"] == []

        read_response = client.get(f"/api/chat/conversations/{conversation['id']}")
        assert read_response.status_code == 200, read_response.text
        assert read_response.json()["id"] == conversation["id"]


def test_authenticated_user_can_list_ollama_models(monkeypatch):
    async def fake_list_models(self):
        return [
            {"name": "llama3.2", "selected": True},
            {"name": "phi4", "selected": False},
        ]

    monkeypatch.setattr("app.api.chat.OllamaClient.list_models", fake_list_models)
    email = f"models-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.get("/api/chat/models")

    assert response.status_code == 200, response.text
    assert response.json()[0] == {"name": "llama3.2", "selected": True}


def test_inference_configuration_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/inference")

    assert response.status_code == 401


def test_authenticated_user_can_read_and_update_inference_routing(monkeypatch):
    async def fake_list_models(self):
        names = ["phi4", settings.rag_embedding_model, settings.rag_reranker_model]
        return [
            {"name": name, "selected": name == "phi4"}
            for name in dict.fromkeys(name for name in names if name)
        ]

    monkeypatch.setattr("app.api.inference.OllamaClient.list_models", fake_list_models)
    email = f"inference-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.get("/api/inference")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["servers"][0]["id"] == "server_1"
        assert all("phi4" in server["models"] for server in payload["servers"])
        assert all("base_url" not in server for server in payload["servers"])

        update_response = client.put(
            "/api/inference",
            json=payload["routing"],
        )

    assert update_response.status_code == 200, update_response.text


def test_inference_routing_rejects_unconfigured_server(monkeypatch):
    async def fake_list_models(self):
        return []

    monkeypatch.setattr("app.api.inference.OllamaClient.list_models", fake_list_models)
    email = f"inference-invalid-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.put(
            "/api/inference",
            json={
                "chat_server_id": "server_3",
                "embedding_server_id": "server_1",
                "reranker_server_id": None,
                "ocr_server_id": "server_1",
                "structuring_server_id": "server_1",
            },
        )

    assert response.status_code == 422


def test_inference_routing_normalizes_stale_server_selection():
    routing = SimpleNamespace(
        chat_server_id="server_2",
        embedding_server_id="server_2",
        embedding_model="qwen3-embedding:8b",
        reranker_server_id="server_2",
        reranker_model="dengcao/Qwen3-Reranker-8B:Q5_K_M",
        ocr_server_id="server_2",
        structuring_server_id="server_2",
    )
    snapshots = [
        SimpleNamespace(
            id="server_1",
            name="Server 1",
            reachable=True,
            models=["phi4", "qwen3-embedding:8b"],
        )
    ]

    _normalize_routing(routing, snapshots)

    assert routing.chat_server_id == "server_1"
    assert routing.ocr_server_id == "server_1"
    assert routing.structuring_server_id == "server_1"
    assert routing.embedding_server_id == "server_1"
    assert routing.embedding_model == "qwen3-embedding:8b"
    assert routing.reranker_server_id is None
    assert routing.reranker_model is None


def test_authenticated_user_can_send_message_to_selected_model(monkeypatch):
    async def fake_chat(self, messages, model=None):
        assert model == "llama3.2"
        assert messages[-1]["content"] == "Ahoj"
        return '{"action":"answer","content":"Ahoj, jsem testovaci odpoved."}'

    monkeypatch.setattr("app.api.chat.OllamaClient.chat", fake_chat)
    email = f"chat-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        create_response = client.post("/api/chat/conversations", json={"title": "Ollama smoke"})
        assert create_response.status_code == 201, create_response.text

        response = client.post(
            f"/api/chat/conversations/{create_response.json()['id']}/messages",
            json={"content": "Ahoj", "model": "llama3.2"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["assistant_message"]["content"] == "Ahoj, jsem testovaci odpoved."
    assert payload["assistant_message"]["model"] == "llama3.2"
    assert [message["role"] for message in payload["conversation"]["messages"]] == ["user", "assistant"]


def test_chat_adds_document_rag_context_when_available(monkeypatch):
    captured = {}
    source_document_id = str(uuid.uuid4())
    weak_document_id = str(uuid.uuid4())

    async def fake_search(session, user_id, query):
        assert query == "Kdy jsem kupoval sekačku?"
        return [
            {
                "document_id": source_document_id,
                "chunk_index": 0,
                "content": "Faktura HECHT MOTORS za robotickou sekačku, 4 990 CZK.",
                "metadata_json": {},
                "embedding_model": "nomic-embed-text",
                "distance": 0.12,
                "filename": "hecht.pdf",
                "summary": "Faktura HECHT MOTORS za robotickou sekačku.",
            },
            {
                "document_id": weak_document_id,
                "chunk_index": 0,
                "content": "Nesouvisejici doklad BAUHAUS.",
                "metadata_json": {},
                "embedding_model": "nomic-embed-text",
                "distance": 0.24,
                "filename": "bauhaus.pdf",
                "summary": "Nesouvisejici doklad BAUHAUS.",
            },
        ]

    async def fake_chat(self, messages, model=None):
        captured["messages"] = messages
        return "Sekačka je v dokladu doc-123."

    monkeypatch.setattr("app.services.chat_agent.search_document_chunks", fake_search)
    monkeypatch.setattr("app.api.chat.OllamaClient.chat", fake_chat)
    email = f"rag-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        create_response = client.post("/api/chat/conversations", json={"title": "RAG smoke"})
        assert create_response.status_code == 201, create_response.text

        response = client.post(
            f"/api/chat/conversations/{create_response.json()['id']}/messages",
            json={"content": "Kdy jsem kupoval sekačku?", "model": "phi4"},
        )

    assert response.status_code == 200, response.text
    assert captured["messages"][0]["role"] == "system"
    assert "Relevantni doklady" in captured["messages"][0]["content"]
    assert source_document_id in captured["messages"][0]["content"]
    assert weak_document_id not in captured["messages"][0]["content"]
    assert "document_id nikdy neopisuj" in captured["messages"][0]["content"]
    assert captured["messages"][-1]["content"] == "Kdy jsem kupoval sekačku?"
    payload = response.json()
    assert payload["assistant_message"]["sources"] == [
        {
            "document_id": source_document_id,
            "title": "Faktura HECHT MOTORS za robotickou sekačku.",
                "filename": "hecht.pdf",
                "distance": 0.12,
                "reranker_score": None,
            }
    ]
    assert all(source["document_id"] != weak_document_id for source in payload["assistant_message"]["sources"])
    assert payload["conversation"]["messages"][-1]["sources"][0]["document_id"] == source_document_id


def test_document_question_without_sources_does_not_answer_from_history(monkeypatch):
    captured = {"calls": 0}

    async def fake_search(session, user_id, query):
        return []

    async def fake_chat(self, messages, model=None):
        captured["calls"] += 1
        return '{"action":"search_documents","search":{"rag_queries":["betonový výrobek"],"structured":{}}}'

    monkeypatch.setattr("app.services.chat_agent.search_document_chunks", fake_search)
    monkeypatch.setattr("app.api.chat.OllamaClient.chat", fake_chat)
    email = f"no-sources-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        conversation = client.post("/api/chat/conversations", json={"title": "No sources"}).json()
        response = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages",
            json={"content": "Koupil jsem něco betonového?", "model": "phi4"},
        )

    assert response.status_code == 200, response.text
    assert captured["calls"] == 1
    assert response.json()["assistant_message"]["content"] == (
        "V uložených dokladech jsem k tomuto dotazu nenašel relevantní záznam."
    )
    assert response.json()["assistant_message"]["sources"] == []


def test_chat_can_use_top_n_source_strategy(monkeypatch):
    first_document_id = str(uuid.uuid4())
    second_document_id = str(uuid.uuid4())
    third_document_id = str(uuid.uuid4())

    async def fake_search(session, user_id, query):
        return [
            {
                "document_id": first_document_id,
                "chunk_index": 0,
                "content": "Prvni doklad.",
                "metadata_json": {},
                "embedding_model": "nomic-embed-text",
                "distance": 0.1,
                "filename": "first.pdf",
                "summary": "Prvni doklad.",
            },
            {
                "document_id": second_document_id,
                "chunk_index": 0,
                "content": "Druhy doklad.",
                "metadata_json": {},
                "embedding_model": "nomic-embed-text",
                "distance": 0.35,
                "filename": "second.pdf",
                "summary": "Druhy doklad.",
            },
            {
                "document_id": third_document_id,
                "chunk_index": 0,
                "content": "Treti doklad.",
                "metadata_json": {},
                "embedding_model": "nomic-embed-text",
                "distance": 0.5,
                "filename": "third.pdf",
                "summary": "Treti doklad.",
            },
        ]

    async def fake_chat(self, messages, model=None):
        return "Top N odpoved."

    monkeypatch.setattr("app.services.chat_agent.search_document_chunks", fake_search)
    monkeypatch.setattr("app.api.chat.OllamaClient.chat", fake_chat)
    email = f"rag-topn-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        settings_response = client.put(
            "/api/settings",
            json={
                "ocr_processing_model": None,
                "rag_source_strategy": "top_n",
                "rag_best_band": 0.08,
                "rag_top_n": 2,
            },
        )
        create_response = client.post("/api/chat/conversations", json={"title": "Top N smoke"})
        response = client.post(
            f"/api/chat/conversations/{create_response.json()['id']}/messages",
            json={"content": "Najdi doklady", "model": "phi4"},
        )

    assert settings_response.status_code == 200, settings_response.text
    assert response.status_code == 200, response.text
    source_ids = [source["document_id"] for source in response.json()["assistant_message"]["sources"]]
    assert source_ids == [first_document_id, second_document_id]


def test_chat_agent_can_request_document_search(monkeypatch):
    rag_document_id = str(uuid.uuid4())
    structured_document_id = str(uuid.uuid4())
    captured = {"calls": 0, "rag_queries": [], "structured_queries": []}

    async def fake_rag_search(session, user_id, query):
        captured["rag_queries"].append(query)
        return [
            {
                "document_id": rag_document_id,
                "chunk_index": 0,
                "content": "RAG doklad o hnojivu BAUHAUS za 349 CZK.",
                "metadata_json": {},
                "embedding_model": "qwen3-embedding",
                "distance": 0.1,
                "filename": "bauhaus.pdf",
                "summary": "Nákup hnojiva v BAUHAUS.",
            }
        ]

    async def fake_structured_search(session, user_id, query):
        captured["structured_queries"].append(query)
        return [
            {
                "document_id": structured_document_id,
                "chunk_index": 0,
                "content": "Structured doklad BAUHAUS TRAV.HNOJIVO BAUHAUS 349 CZK.",
                "metadata_json": {},
                "embedding_model": "structured-json",
                "distance": 0.0,
                "filename": "bauhaus-structured.pdf",
                "summary": "Structured nákup hnojiva v BAUHAUS.",
            }
        ]

    async def fake_chat(self, messages, model=None):
        captured["calls"] += 1
        if captured["calls"] == 1:
            return """
            {
              "action": "search_documents",
              "search": {
                "rag_queries": ["cena hnojiva BAUHAUS"],
                "structured": {
                  "merchant": "BAUHAUS",
                  "item": "hnojivo",
                  "date": {"mode": null, "value": null, "value_to": null},
                  "amount": {"mode": null, "value": null, "value_to": null}
                }
              }
            }
            """
        captured["final_messages"] = messages
        return "Hnojivo stálo 349 CZK."

    monkeypatch.setattr("app.services.chat_agent.search_document_chunks", fake_rag_search)
    monkeypatch.setattr("app.services.chat_agent.search_document_structured", fake_structured_search)
    monkeypatch.setattr("app.api.chat.OllamaClient.chat", fake_chat)
    email = f"agent-search-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        settings_response = client.put(
            "/api/settings",
            json={
                "ocr_processing_model": None,
                "rag_source_strategy": "top_n",
                "rag_best_band": 0.08,
                "rag_top_n": 2,
            },
        )
        create_response = client.post("/api/chat/conversations", json={"title": "Agent search"})
        response = client.post(
            f"/api/chat/conversations/{create_response.json()['id']}/messages",
            json={"content": "Kolik stálo to hnojivo?", "model": "gemma"},
        )

    assert settings_response.status_code == 200, settings_response.text
    assert response.status_code == 200, response.text
    payload = response.json()
    assert captured["calls"] == 2
    assert captured["rag_queries"] == ["cena hnojiva BAUHAUS"]
    assert captured["structured_queries"] == ["BAUHAUS hnojivo"]
    assert "Structured doklad BAUHAUS" in captured["final_messages"][0]["content"]
    assert payload["assistant_message"]["content"] == "Hnojivo stálo 349 CZK."
    assert payload["assistant_message"]["retrieval"] == {
        "mode": "hybrid",
        "used_rag": True,
        "used_search": True,
        "used_reranker": False,
        "reranker_model": None,
        "source_count": 2,
    }
    assert [source["document_id"] for source in payload["assistant_message"]["sources"]] == [
        structured_document_id,
        rag_document_id,
    ]


def test_chat_agent_can_answer_without_retrieval(monkeypatch):
    captured = {"calls": 0}

    async def fake_rag_search(session, user_id, query):
        raise AssertionError("RAG search should not run for direct agent answer")

    async def fake_chat(self, messages, model=None):
        captured["calls"] += 1
        return '{"action":"answer","content":"Ahoj, jak můžu pomoct?"}'

    monkeypatch.setattr("app.services.chat_agent.search_document_chunks", fake_rag_search)
    monkeypatch.setattr("app.api.chat.OllamaClient.chat", fake_chat)
    email = f"agent-direct-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        create_response = client.post("/api/chat/conversations", json={"title": "Agent direct"})
        response = client.post(
            f"/api/chat/conversations/{create_response.json()['id']}/messages",
            json={"content": "Ahoj", "model": "gemma"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert captured["calls"] == 1
    assert payload["assistant_message"]["content"] == "Ahoj, jak můžu pomoct?"
    assert payload["assistant_message"]["sources"] == []
    assert payload["assistant_message"]["retrieval"] == {
        "mode": "none",
        "used_rag": False,
        "used_search": False,
        "used_reranker": False,
        "reranker_model": None,
        "source_count": 0,
    }


def test_authenticated_user_can_delete_own_conversation():
    email = f"delete-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        create_response = client.post("/api/chat/conversations", json={"title": "Ke smazani"})
        assert create_response.status_code == 201, create_response.text
        conversation_id = create_response.json()["id"]

        delete_response = client.delete(f"/api/chat/conversations/{conversation_id}")
        assert delete_response.status_code == 204, delete_response.text

        read_response = client.get(f"/api/chat/conversations/{conversation_id}")

    assert read_response.status_code == 404
    assert read_response.json()["detail"] == "Conversation not found"


def test_user_cannot_delete_another_users_conversation():
    first_email = f"delete-owner-{uuid.uuid4()}@example.com"
    second_email = f"delete-intruder-{uuid.uuid4()}@example.com"

    with TestClient(app) as owner:
        _register_and_login(owner, first_email)
        create_response = owner.post("/api/chat/conversations", json={"title": "Cizi vlakno"})
        assert create_response.status_code == 201, create_response.text
        conversation_id = create_response.json()["id"]

    with TestClient(app) as intruder:
        _register_and_login(intruder, second_email)
        delete_response = intruder.delete(f"/api/chat/conversations/{conversation_id}")

    assert delete_response.status_code == 404
    assert delete_response.json()["detail"] == "Conversation not found"


def test_user_cannot_read_another_users_conversation():
    first_email = f"owner-{uuid.uuid4()}@example.com"
    second_email = f"intruder-{uuid.uuid4()}@example.com"

    with TestClient(app) as owner:
        _register_and_login(owner, first_email)
        create_response = owner.post(
            "/api/chat/conversations",
            json={"title": "Soukrome vlakno"},
        )
        assert create_response.status_code == 201, create_response.text
        conversation_id = create_response.json()["id"]

    with TestClient(app) as intruder:
        _register_and_login(intruder, second_email)
        read_response = intruder.get(f"/api/chat/conversations/{conversation_id}")

    assert read_response.status_code == 404
    assert read_response.json()["detail"] == "Conversation not found"


def test_validation_errors_have_stable_shape():
    email = f"validation-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        response = client.post(
            "/api/chat/conversations",
            json={"title": "x" * 200},
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"] == "Validation error"
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["fields"]


def test_voice_session_requires_authenticated_user():
    with TestClient(app) as client:
        response = client.post("/api/voice/sessions", json={"conversation_id": None})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "http_401"


def test_authenticated_user_can_create_and_attach_voice_session():
    email = f"voice-create-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        settings_response = client.put("/api/settings", json={"tts_voice": "Iva210"})
        assert settings_response.status_code == 200, settings_response.text
        create_response = client.post("/api/voice/sessions", json={"conversation_id": None})
        assert create_response.status_code == 201, create_response.text
        payload = create_response.json()

        assert payload["token"]
        assert payload["conversation"]["title"] == "Hlasový hovor"
        attach_response = client.post(
            "/api/voice/sessions/attach",
            headers={"X-Voice-Session-Token": payload["token"]},
            json={"speechcloud_session_id": "sc-test-session"},
        )

    assert attach_response.status_code == 200, attach_response.text
    assert attach_response.json()["voice_session_id"] == payload["voice_session_id"]
    assert attach_response.json()["conversation_id"] == payload["conversation"]["id"]
    assert attach_response.json()["tts_voice"] == "Iva210"


def test_voice_message_uses_token_conversation_and_chat_flow(monkeypatch):
    used_models = []
    system_prompts = []

    async def fake_chat(self, messages, model=None):
        used_models.append(model)
        system_prompts.append(messages[0]["content"])
        return '{"action":"answer","content":"Hlasova odpoved z backendu."}'

    monkeypatch.setattr("app.services.chat_agent.OllamaClient.chat", fake_chat)
    email = f"voice-message-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        settings_response = client.put(
            "/api/settings",
            json={"default_chat_model": "voice-default"},
        )
        assert settings_response.status_code == 200, settings_response.text
        assert settings_response.json()["default_chat_model"] == "voice-default"
        conversation_response = client.post("/api/chat/conversations", json={"title": "Voice active"})
        voice_response = client.post(
            "/api/voice/sessions",
            json={"conversation_id": conversation_response.json()["id"]},
        )
        token = voice_response.json()["token"]

    with TestClient(app) as speech_client:
        response = speech_client.post(
            "/api/voice/messages",
            headers={"X-Voice-Session-Token": token},
            json={"content": "Kolik jsem zaplatil?"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["user_message"]["content"] == "Kolik jsem zaplatil?"
    assert payload["assistant_message"]["content"] == "Hlasova odpoved z backendu."
    assert used_models and set(used_models) == {"voice-default"}
    assert any("Odpoved bude prectena nahlas" in prompt for prompt in system_prompts)
    assert any("Doklad: receipt" in prompt for prompt in system_prompts)
    assert [message["role"] for message in payload["conversation"]["messages"]] == ["user", "assistant"]
    assert payload["conversation"]["id"] == conversation_response.json()["id"]


def test_voice_message_rejects_invalid_and_ended_tokens():
    email = f"voice-token-{uuid.uuid4()}@example.com"

    with TestClient(app) as client:
        _register_and_login(client, email)
        voice_response = client.post("/api/voice/sessions", json={"conversation_id": None})
        session = voice_response.json()
        invalid_response = client.post(
            "/api/voice/messages",
            headers={"X-Voice-Session-Token": "not-a-real-token"},
            json={"content": "Ahoj"},
        )
        end_response = client.post(f"/api/voice/sessions/{session['voice_session_id']}/end")
        ended_response = client.post(
            "/api/voice/messages",
            headers={"X-Voice-Session-Token": session["token"]},
            json={"content": "Ahoj"},
        )

    assert invalid_response.status_code == 401
    assert end_response.status_code == 200, end_response.text
    assert end_response.json()["status"] == "ended"
    assert ended_response.status_code == 403


def test_user_cannot_end_another_users_voice_session():
    owner_email = f"voice-owner-{uuid.uuid4()}@example.com"
    intruder_email = f"voice-intruder-{uuid.uuid4()}@example.com"

    with TestClient(app) as owner:
        _register_and_login(owner, owner_email)
        voice_response = owner.post("/api/voice/sessions", json={"conversation_id": None})
        voice_session_id = voice_response.json()["voice_session_id"]

    with TestClient(app) as intruder:
        _register_and_login(intruder, intruder_email)
        response = intruder.post(f"/api/voice/sessions/{voice_session_id}/end")

    assert response.status_code == 404
