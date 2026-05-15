import uuid

from fastapi.testclient import TestClient

from app.main import app


PASSWORD = "StrongPass123"


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


def test_authenticated_user_can_send_message_to_selected_model(monkeypatch):
    async def fake_chat(self, messages, model=None):
        assert model == "llama3.2"
        assert messages[-1]["content"] == "Ahoj"
        return "Ahoj, jsem testovaci odpoved."

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

    monkeypatch.setattr("app.api.chat.search_document_chunks", fake_search)
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
    assert weak_document_id in captured["messages"][0]["content"]
    assert "document_id nikdy neopisuj" in captured["messages"][0]["content"]
    assert captured["messages"][-1]["content"] == "Kdy jsem kupoval sekačku?"
    payload = response.json()
    assert payload["assistant_message"]["sources"] == [
        {
            "document_id": source_document_id,
            "title": "Faktura HECHT MOTORS za robotickou sekačku.",
            "filename": "hecht.pdf",
            "distance": 0.12,
        }
    ]
    assert all(source["document_id"] != weak_document_id for source in payload["assistant_message"]["sources"])
    assert payload["conversation"]["messages"][-1]["sources"][0]["document_id"] == source_document_id


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

    monkeypatch.setattr("app.api.chat.search_document_chunks", fake_search)
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
