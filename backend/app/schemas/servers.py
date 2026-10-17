from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator


class ServerSettingsUpdate(BaseModel):
    id: Literal["server_1", "server_2"]
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = False
    base_url: str = Field(default="", max_length=500)
    api_type: Literal["ollama", "openai"] = "ollama"
    auth_scheme: Literal["none", "basic", "digest"] = "none"
    username: str | None = Field(default=None, max_length=160)
    password: str | None = Field(default=None, max_length=1000)
    api_key: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_address(self):
        self.base_url = self.base_url.strip().rstrip("/")
        if self.enabled or self.base_url:
            parsed = urlsplit(self.base_url)
            _ = parsed.port
            if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Server URL must be an HTTP(S) address without credentials, query or fragment")
        return self


class ServerSettingsRead(BaseModel):
    id: str
    name: str
    enabled: bool
    base_url: str
    api_type: str
    auth_scheme: str
    username: str | None
    has_password: bool
    has_api_key: bool
