# SP2 - dokumentace projektu

Projekt: webova aplikace pro chat nad uctenkami a fakturami. Cilovy stav pocita s OCR, RAG vrstvou, chatovacim rozhranim nad Ollama serverem, autentizaci a pozdejsim napojenim rozpoznavani a generovani hlasu.

Aktualni faze je planovani a priprava chat-only MVP. Tato verze jeste neresi OCR ani hlas, ale poklada zaklad pro backend, autentizaci, perzistentni chat a budouci napojeni dokumentove pipeline.

## Dokumenty

- [Produktovy zamer](docs/01-product-vision.md)
- [Architektura](docs/02-architecture.md)
- [Technologicky stack](docs/03-stack.md)
- [Faze vyvoje](docs/04-roadmap.md)
- [Backlog](docs/05-backlog.md)
- [Rozhodnuti a otevrene otazky](docs/06-decisions-and-questions.md)
- [Volba vektorove databaze](docs/07-vector-db-choice.md)
- [SpeechCloud integrace](docs/08-speechcloud-integration.md)
- [Designovy jazyk](docs/09-design-language.md)

## Nejblizsi cil

Vytvorit webovou aplikaci a dialogovy backend, kde se prihlaseny uzivatel muze bavit s Ollama modelem textove i pres SpeechCloud ASR/TTS. OCR a vlastni RAG vrstva zustavaji soucasti dalsich fazi; ignoruje se pouze ukazkova implementace RAG ve slozce `example`.

## Faze 1 skeleton

Aktualni implementacni zaklad obsahuje:

- `backend`: FastAPI API, FastAPI Users auth pres email + heslo + HTTP-only cookie, chat endpointy, Ollama adapter.
- `frontend`: React/Vite aplikace s design tokeny podle HDS Recorderu.
- `speech-dialog`: SpeechCloud dialog manager podle ukazky `example/example_cviceni_chat.py`, bez hardcodovanych hesel.
- `docker-compose.yml`: lokalni stack pro PostgreSQL, backend, frontend a speech-dialog. Ollama je externi endpoint pres `OLLAMA_BASE_URL`; lokalni Ollama kontejner je jen volitelny profil.
- `docker-compose.test.yml`: zaklad pro kontejnerove testy.

Prvni spusteni:

```bash
cp .env.example .env
docker compose up --build
```

Pokud chces misto externiho serveru spustit lokalni Ollama kontejner:

```bash
OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile local-ollama up --build
```

Testy:

```bash
docker compose -f docker-compose.test.yml run --rm backend-test
docker compose -f docker-compose.test.yml run --rm frontend-test
```

Poznamka: Ollama model je nutne mit na externim nebo lokalnim Ollama serveru dostupny podle `OLLAMA_MODEL`.
