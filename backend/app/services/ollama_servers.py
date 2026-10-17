from dataclasses import dataclass

from app.core.config import settings
from fastapi import HTTPException
from app.services.server_settings import decrypt_credential, encrypt_credential


@dataclass(frozen=True)
class OllamaServerConfig:
    id: str
    name: str
    base_url: str
    username: str | None = None
    password: str | None = None
    auth_scheme: str = "digest"
    api_type: str = "ollama"
    api_key: str | None = None


def configured_ollama_servers() -> list[OllamaServerConfig]:
    servers = [
        OllamaServerConfig(
            id="server_1",
            name=settings.ollama_server_1_name,
            base_url=settings.ollama_base_url.rstrip("/"),
            api_type=settings.ollama_api_type,
            api_key=settings.ollama_api_key,
            username=settings.ollama_username,
            password=settings.ollama_password,
            auth_scheme=settings.ollama_auth_scheme,
        )
    ] if settings.ollama_base_url else []
    if settings.ollama_server_2_base_url:
        servers.append(
            OllamaServerConfig(
                id="server_2",
                name=settings.ollama_server_2_name,
                base_url=settings.ollama_server_2_base_url.rstrip("/"),
                api_type=settings.ollama_server_2_api_type,
                api_key=settings.ollama_server_2_api_key,
                username=settings.ollama_server_2_username,
                password=settings.ollama_server_2_password,
                auth_scheme=settings.ollama_server_2_auth_scheme,
            )
        )
    return servers


def get_ollama_server(server_id: str | None) -> OllamaServerConfig:
    servers = configured_ollama_servers()
    if not servers:
        raise HTTPException(422, "Nejdříve nastavte výpočetní server v aplikaci.")
    return next((server for server in servers if server.id == server_id), servers[0])


def routing_server_records(routing) -> list[dict]:
    if routing.server_configs is not None:
        return routing.server_configs
    legacy = {server.id: server for server in configured_ollama_servers()}
    records = []
    for index in (1, 2):
        server = legacy.get(f"server_{index}")
        records.append({
            "id": f"server_{index}", "name": server.name if server else f"Server {index}",
            "enabled": server is not None, "base_url": server.base_url if server else "",
            "api_type": server.api_type if server else "ollama",
            "auth_scheme": server.auth_scheme if server else "none",
            "username": server.username if server else None,
            "password_encrypted": encrypt_credential(server.password) if server else None,
            "api_key_encrypted": encrypt_credential(server.api_key) if server else None,
        })
    return records


def server_from_record(item: dict) -> OllamaServerConfig:
    return OllamaServerConfig(
        id=item["id"], name=item["name"], base_url=item["base_url"],
        api_type=item["api_type"], auth_scheme=item["auth_scheme"], username=item.get("username"),
        password=decrypt_credential(item.get("password_encrypted")),
        api_key=decrypt_credential(item.get("api_key_encrypted")),
    )


def routing_servers(routing) -> list[OllamaServerConfig]:
    return [server_from_record(item) for item in routing_server_records(routing) if item["enabled"]]


def get_routing_server(routing, server_id: str | None) -> OllamaServerConfig:
    records = [item for item in routing_server_records(routing) if item["enabled"]]
    if not records:
        raise HTTPException(422, "Nejdříve nastavte výpočetní server v aplikaci.")
    return server_from_record(next((item for item in records if item["id"] == server_id), records[0]))
