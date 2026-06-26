# SP2 ReceiptChat

A web application for text and voice chat over personal documents such as receipts and invoices. The system can upload a document, process it with OCR, structure it with an AI model, store it in a RAG index, and then answer questions about it in Czech.

The voice part uses SpeechCloud as the technical ASR/TTS layer. User identity, document access, RAG, reranking, and answer generation are handled by the application backend.

## Features

- Login with a secure HTTP-only cookie.
- Upload of receipts, invoices, photos, and PDFs.
- OCR processing for documents.
- Multimodal document structuring from OCR text and the original image.
- RAG over the authenticated user's personal documents.
- Optional reranker for more accurate source selection.
- Text chat over indexed documents.
- Voice call through SpeechCloud with a floating overlay above the chat.
- Voice questions and assistant answers are stored in the same conversation history as text chat.
- User settings for default chat model, TTS voice, and source selection strategy.
- Optional routing of inference roles across multiple Ollama servers: chat, embedding, reranking, OCR, and document structuring.

## Architecture

- `backend` - FastAPI API, authentication, documents, chat agent, RAG, reranker, and voice session API.
- `frontend` - React/Vite app for chat, documents, settings, and the voice overlay.
- `speech-dialog` - SpeechCloud dialog manager connecting ASR/TTS to the backend.
- `postgres` - PostgreSQL with pgvector for metadata, chat history, and vector search.
- `ocr-worker` - asynchronous worker for OCR and document processing.

Simplified voice query flow:

```text
user -> SpeechCloud ASR -> speech-dialog -> backend chat/RAG -> speech-dialog -> SpeechCloud TTS -> user
```

## Documentation

- [Product vision](docs/01-product-vision.md)
- [Architecture](docs/02-architecture.md)
- [Technology stack](docs/03-stack.md)
- [Roadmap and implementation history](docs/04-roadmap.md)
- [Backlog notes](docs/05-backlog.md)
- [Decisions and open questions](docs/06-decisions-and-questions.md)
- [Vector database choice](docs/07-vector-db-choice.md)
- [SpeechCloud integration](docs/08-speechcloud-integration.md)
- [Design language](docs/09-design-language.md)
- [Production deployment](docs/11-production-deploy.md)

## Local Setup

Create a local `.env` file:

```bash
cp .env.example .env
```

Start the stack:

```bash
docker compose up --build
```

Default local URLs:

```text
Frontend:      http://localhost:5173
Backend API:   http://localhost:8000/api
Speech dialog: ws://localhost:8888/ws
```

Ollama runs outside the default compose stack and is configured through `OLLAMA_BASE_URL`. To use the optional local Ollama compose profile:

```bash
OLLAMA_BASE_URL=http://ollama:11434 docker compose --profile local-ollama up --build
```

## Important Environment Variables

Chat and document processing:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
RAG_EMBEDDING_MODEL=qwen3-embedding:latest
RAG_RERANKER_MODEL=
OCR_ENGINE=ollama
OLLAMA_OCR_MODEL=glm-ocr:latest
```

SpeechCloud frontend configuration:

```env
VITE_SPEECHCLOUD_SCRIPT_URL=https://speechcloud.kky.zcu.cz:9444/speechcloud-3.0.js
VITE_SPEECHCLOUD_MODEL_URI=https://speechcloud.kky.zcu.cz:9443/v1/speechcloud/edu-hds-all
VITE_SPEECH_DIALOG_LOCAL_DM=ws://localhost:8888/ws
```

In production, the SpeechCloud dialog manager is exposed through the frontend nginx container:

```env
VITE_SPEECH_DIALOG_LOCAL_DM=/ws
```

Frontend `VITE_*` variables are build-time variables. Rebuild the frontend image after changing them.

## RAG and Reranker

After OCR and structuring, each document is converted into text suitable for RAG. The indexed text includes the summary, metadata, merchant, date, amounts, items, quantities, unit prices, raw item text, and user notes.

The reranker is an optional second stage applied to candidates from vector search. The model receives a query-document pair and is instructed to answer `yes` or `no`; the backend uses the logprobs of the `yes` and `no` tokens to compute a relevance score. In practice, the minimum threshold should stay low, for example around `0.1`, so short follow-up questions still work.

## Tests

Backend:

```bash
docker compose -f docker-compose.test.yml run --rm backend-test
```

Frontend:

```bash
docker compose -f docker-compose.test.yml run --rm frontend-test
```

Standalone frontend type check:

```bash
cd frontend
npx tsc --noEmit --pretty false
```

## Production Deployment

Production uses a separate compose file:

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Typical public domains:

```text
https://receiptchat.example.com     -> frontend
https://api.example.com             -> backend API
https://receiptchat.example.com/ws  -> speech-dialog websocket through frontend nginx
```

The reverse proxy must enable WebSocket support for the frontend domain, because `/ws` is proxied from the frontend nginx container to `speech-dialog`.

See [production deployment notes](docs/11-production-deploy.md) for details.

## Security Notes

- Real `.env` and `.env.production` files must not be committed.
- The SpeechCloud account is only a technical ASR/TTS account and does not determine document access.
- Voice sessions use short-lived bearer tokens; only their hash is stored in the database.
- PostgreSQL is not exposed through a public port in the production compose file.
