import os


class Settings:
    host: str = os.getenv("SPEECH_DIALOG_HOST", "0.0.0.0")
    port: int = int(os.getenv("SPEECH_DIALOG_PORT", "8888"))
    static_path: str = os.getenv("SPEECH_STATIC_PATH", "./static")

    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "phi4")
    ollama_username: str | None = os.getenv("OLLAMA_USERNAME") or None
    ollama_password: str | None = os.getenv("OLLAMA_PASSWORD") or None
    system_prompt: str = os.getenv("SPEECH_SYSTEM_PROMPT", "Odpovidej strucne v cestine.")


settings = Settings()

