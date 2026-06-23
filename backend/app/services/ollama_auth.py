from functools import lru_cache

import httpx

from app.core.config import settings
from app.services.ollama_servers import OllamaServerConfig


@lru_cache(maxsize=8)
def _cached_auth(scheme: str, username: str, password: str) -> httpx.Auth:
    if scheme.strip().lower() == "basic":
        return httpx.BasicAuth(username, password)
    return httpx.DigestAuth(username, password)


def ollama_auth(server: OllamaServerConfig | None = None) -> httpx.Auth | None:
    username = server.username if server else settings.ollama_username
    password = server.password if server else settings.ollama_password
    scheme = server.auth_scheme if server else settings.ollama_auth_scheme
    if username and password:
        return _cached_auth(scheme, username, password)
    return None
