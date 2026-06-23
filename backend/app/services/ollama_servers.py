from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class OllamaServerConfig:
    id: str
    name: str
    base_url: str
    username: str | None = None
    password: str | None = None
    auth_scheme: str = "digest"


def configured_ollama_servers() -> list[OllamaServerConfig]:
    servers = [
        OllamaServerConfig(
            id="server_1",
            name=settings.ollama_server_1_name,
            base_url=settings.ollama_base_url.rstrip("/"),
            username=settings.ollama_username,
            password=settings.ollama_password,
            auth_scheme=settings.ollama_auth_scheme,
        )
    ]
    if settings.ollama_server_2_base_url:
        servers.append(
            OllamaServerConfig(
                id="server_2",
                name=settings.ollama_server_2_name,
                base_url=settings.ollama_server_2_base_url.rstrip("/"),
                username=settings.ollama_server_2_username,
                password=settings.ollama_server_2_password,
                auth_scheme=settings.ollama_server_2_auth_scheme,
            )
        )
    return servers


def get_ollama_server(server_id: str | None) -> OllamaServerConfig:
    servers = configured_ollama_servers()
    return next((server for server in servers if server.id == server_id), servers[0])
