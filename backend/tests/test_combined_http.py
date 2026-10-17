"""Optional HTTP checks against a running, disposable combined deployment."""

import os
import re
import secrets
import uuid

import httpx
import pytest


@pytest.fixture
def deployed_client():
    base_url = os.environ.get("RECEIPTCHAT_TEST_URL")
    if not base_url:
        pytest.skip("Set RECEIPTCHAT_TEST_URL to test a running combined container")
    with httpx.Client(base_url=base_url, timeout=180) as client:
        yield client


def test_combined_static_assets_and_api_proxy(deployed_client):
    page = deployed_client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', page.text)
    assert assets
    for asset in assets:
        response = deployed_client.get(asset)
        assert response.status_code == 200
        assert "immutable" in response.headers["cache-control"]
    assert deployed_client.get("/assets/does-not-exist.js").status_code == 404
    assert deployed_client.get("/documents/deep-link").text == page.text
    assert "no-cache" in page.headers["cache-control"]
    for path in ("/health", "/api/health"):
        response = deployed_client.get(path)
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    assert deployed_client.get("/api/does-not-exist.js").status_code == 404
    assert deployed_client.get("/api/chat/conversations").status_code == 401


def test_combined_cookie_auth_and_conversations(deployed_client):
    email = f"combined-{uuid.uuid4()}@example.com"
    password = secrets.token_urlsafe(24)
    response = deployed_client.post("/api/auth/register", json={"email": email, "password": password})
    assert response.status_code in (200, 201), response.text
    response = deployed_client.post("/api/auth/login", data={"username": email, "password": password})
    assert response.status_code in (200, 204), response.text
    assert deployed_client.get("/api/users/me").json()["email"] == email
    assert deployed_client.get("/api/settings").status_code == 200
    conversation = deployed_client.post("/api/chat/conversations", json={"title": "Combined deployment check"})
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    try:
        response = deployed_client.get(f"/api/chat/conversations/{conversation_id}")
        assert response.status_code == 200
        assert response.json()["messages"] == []
        model = os.environ.get("RECEIPTCHAT_TEST_MODEL")
        if model:
            models = deployed_client.get("/api/chat/models")
            assert models.status_code == 200, models.text
            assert model in [item["name"] for item in models.json()]
            answer = deployed_client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={"content": "Ahoj, odpověz krátkým pozdravem.", "model": model},
            )
            assert answer.status_code == 200, answer.text
            assert answer.json()["assistant_message"]["content"]
            assert [item["role"] for item in answer.json()["conversation"]["messages"]] == ["user", "assistant"]
    finally:
        assert deployed_client.delete(f"/api/chat/conversations/{conversation_id}").status_code == 204
        assert deployed_client.post("/api/auth/logout").status_code in (200, 204)
    assert deployed_client.get("/api/users/me").status_code == 401
