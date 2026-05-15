import logging

import httpx
from ollama import Client

from app.config import settings
from dialog import Dialog, SpeechCloudWS


class AssistantDialog(Dialog):
    async def main(self):
        auth = None
        if settings.ollama_username and settings.ollama_password:
            auth = httpx.DigestAuth(settings.ollama_username, settings.ollama_password)

        self.client = Client(host=settings.ollama_base_url, auth=auth)
        self.messages = [{"role": "system", "content": settings.system_prompt}]

        await self.synthesize_and_wait(
            text="Dobry den, jsem hlasovy asistent. Co si prejete?"
        )

        while True:
            result = await self.recognize_and_wait_for_asr_result(timeout=5.0)
            user_words = None if result is None else result.get("word_1best")

            if not user_words:
                await self.synthesize_and_wait(text="Nic jsem nezachytil.")
                continue

            if "konec" in user_words.lower():
                await self.synthesize_and_wait(text="Koncim, dekuji.")
                break

            self.messages.append({"role": "user", "content": user_words})
            logging.info("SpeechCloud ASR: %s", user_words)

            response = ""
            for chunk in self.client.chat(
                model=settings.ollama_model,
                messages=self.messages,
                stream=True,
            ):
                response += chunk.get("message", {}).get("content", "")

            response = response.strip() or "Model nevratil zadnou odpoved."
            self.messages.append({"role": "assistant", "content": response})
            logging.info("Ollama response length: %s", len(response))

            await self.synthesize_and_wait(text=response)


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

