import asyncio
import logging
import re

import httpx

from app.config import settings
from dialog import Dialog, SpeechCloudWS

DOCUMENT_REFERENCE_RE = re.compile(
    r"\s*[\[(]\s*(?:dokument|document)_id\s*:\s*[0-9a-f-]{36}\s*[\])]",
    re.IGNORECASE,
)


def sanitize_tts_text(text: str) -> str:
    text = DOCUMENT_REFERENCE_RE.sub("", text)
    text = re.sub(r"(?m)^\s*[-*•]\s+", ". ", text)
    text = re.sub(r"\s+[*•]\s+(?=\S)", ". ", text)
    text = text.replace("*", "").replace("`", "")
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r":\s*\.\s*", ": ", text)
    text = re.sub(r"([.!?])(?:\s*\.)+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


class AssistantDialog(Dialog):
    tts_voice: str | None = None

    def __init__(self, sc):
        super().__init__(sc)
        self.is_muted = False
        self._mute_epoch = 0
        self._unmuted = asyncio.Event()
        self._unmuted.set()

    async def _notify(self, state: str, **payload):
        await self.send_message({"type": "voice_status", "state": state, **payload})

    async def _speak(self, text: str) -> None:
        text = sanitize_tts_text(text)
        options = {"voice": self.tts_voice} if self.tts_voice else {}
        await self.synthesize_and_wait(text=text, **options)

    def on_receive_message(self, data):
        if not isinstance(data, dict) or data.get("type") != "voice_control":
            return
        action = data.get("action")
        if action == "mute" and not self.is_muted:
            self.is_muted = True
            self._mute_epoch += 1
            self._unmuted.clear()
            asyncio.create_task(self.sc.asr_pause())
            asyncio.create_task(self._notify("muted", message="Mikrofon je ztlumený."))
        elif action == "unmute" and self.is_muted:
            self.is_muted = False
            self._unmuted.set()
            asyncio.create_task(self._notify("unmuted", message="Mikrofon je aktivní."))

    @staticmethod
    def _backend_error_detail(exc: httpx.HTTPStatusError) -> str:
        try:
            payload = exc.response.json()
        except ValueError:
            return str(exc)
        detail = payload.get("detail") if isinstance(payload, dict) else None
        return str(detail) if detail else str(exc)

    async def _wait_for_voice_token(self) -> str | None:
        await self._notify("connecting", message="Čekám na propojení s přihlášeným uživatelem.")
        message = await self.pop_message(timeout=settings.voice_attach_timeout_seconds)
        data = message.get("data", {}) if isinstance(message, dict) else {}
        if data.get("type") != "voice_session" or not data.get("token"):
            return None
        return str(data["token"])

    async def _attach_session(self, client: httpx.AsyncClient, token: str) -> dict:
        response = await client.post(
            "/voice/sessions/attach",
            headers={"X-Voice-Session-Token": token},
            json={"speechcloud_session_id": self.session_id},
        )
        response.raise_for_status()
        return response.json()

    async def _send_voice_message(self, client: httpx.AsyncClient, token: str, content: str) -> dict:
        response = await client.post(
            "/voice/messages",
            headers={"X-Voice-Session-Token": token},
            json={"content": content},
        )
        response.raise_for_status()
        return response.json()

    async def main(self):
        timeout = httpx.Timeout(120.0, connect=10.0)
        async with httpx.AsyncClient(base_url=settings.backend_api_base_url.rstrip("/"), timeout=timeout) as client:
            token = await self._wait_for_voice_token()
            if not token:
                await self._notify("error", message="Nepřišel voice session token.")
                await self._speak("Nepodařilo se propojit hovor s aplikací.")
                return

            try:
                attachment = await self._attach_session(client, token)
                self.tts_voice = attachment.get("tts_voice") or None
            except httpx.HTTPError as exc:
                logging.exception("Voice session attach failed")
                await self._notify("error", message=f"Propojení s backendem selhalo: {exc}")
                await self._speak("Nepodařilo se ověřit hlasovou session.")
                return

            await self._notify("listening", message="Hovor je připravený.")
            await self._speak("Dobrý den, jsem hlasový asistent. Co si přejete?")

            while True:
                await self._unmuted.wait()
                await self._notify("listening", message="Poslouchám.")
                recognition_epoch = self._mute_epoch
                result = await self.recognize_and_wait_for_asr_result(timeout=8.0)
                if recognition_epoch != self._mute_epoch:
                    continue
                user_words = None if result is None else result.get("word_1best")

                if not user_words:
                    await self._notify("recognizing", transcript="")
                    await self._speak("Nic jsem nezachytil.")
                    continue

                await self._notify("asr_result", transcript=user_words)
                if "konec" in user_words.lower():
                    await self._notify("ended", message="Hovor ukončen hlasovým příkazem.")
                    await self._speak("Končím, děkuji.")
                    break

                logging.info("SpeechCloud ASR: %s", user_words)
                await self._notify("thinking", transcript=user_words)
                try:
                    payload = await self._send_voice_message(client, token, user_words)
                except httpx.HTTPError as exc:
                    logging.exception("Voice message failed")
                    detail = self._backend_error_detail(exc) if isinstance(exc, httpx.HTTPStatusError) else str(exc)
                    await self._notify("error", message=f"Zpracování dotazu selhalo: {detail}")
                    await self._speak("Vybraný jazykový model se nepodařilo použít. Zvolte prosím jiný model.")
                    continue

                assistant_message = payload.get("assistant_message") or {}
                answer = assistant_message.get("content") or "Model nevrátil žádnou odpověď."
                sources = assistant_message.get("sources") or []
                await self._notify("assistant_response", answer=answer, sources=sources, conversation=payload.get("conversation"))
                await self._notify("speaking", answer=answer)
                await self._speak(answer)


def run() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)-10s %(message)s",
        level=logging.INFO,
    )
    SpeechCloudWS.run(
        AssistantDialog,
        address=settings.host,
        port=settings.port,
        static_path=settings.static_path,
    )


if __name__ == "__main__":
    run()
