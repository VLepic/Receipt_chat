import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException

from app.core.config import settings
from app.schemas.servers import ServerSettingsRead, ServerSettingsUpdate


def encrypt_credential(value: str | None) -> str | None:
    if not value:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key).encrypt(value.encode()).decode()


def decrypt_credential(value: str | None) -> str | None:
    if not value:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    try:
        return Fernet(key).decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(503, "Uložené přístupové údaje nelze dešifrovat. Obnovte původní SECRET_KEY nebo údaje zadejte znovu.") from exc


def merge_server_settings(payload: ServerSettingsUpdate, previous: dict) -> dict:
    record = payload.model_dump(exclude={"password", "api_key"})
    same_destination = all(
        record.get(field) == previous.get(field)
        for field in ("base_url", "api_type", "auth_scheme", "username")
    )
    for field in ("password", "api_key"):
        value = getattr(payload, field)
        # Never forward an existing credential to a newly configured destination.
        record[f"{field}_encrypted"] = (
            previous.get(f"{field}_encrypted") if value is None and same_destination else encrypt_credential(value)
        )
    return record


def public_server_settings(record: dict) -> ServerSettingsRead:
    return ServerSettingsRead(
        **{key: record.get(key) for key in ("id", "name", "enabled", "base_url", "api_type", "auth_scheme", "username")},
        has_password=bool(record.get("password_encrypted")),
        has_api_key=bool(record.get("api_key_encrypted")),
    )
