# SP2 ReceiptChat

A web application for text chat over personal documents such as receipts and invoices. The system can upload a document, process it with OCR, structure it with an AI model, store it in a RAG index, and then answer questions about it in Czech.

## Features

- Login with a secure HTTP-only cookie.
- Upload of receipts, invoices, photos, and PDFs.
- OCR processing for documents.
- Multimodal document structuring from OCR text and the original image.
- RAG over the authenticated user's personal documents.
- Optional reranker for more accurate source selection.
- Text chat over indexed documents.
- User settings for default chat model and source selection strategy.
- Optional routing of inference roles across Ollama and OpenAI-compatible servers (including llama.cpp): chat, embedding, reranking, OCR, and document structuring.

## Architecture

- `receiptchat` - one application container with the built React frontend, nginx, FastAPI API, and OCR/structuring worker.
- `postgres` - a separate PostgreSQL/pgvector container for metadata, chat history, and vector search.
- Ollama and llama.cpp remain external configurable inference servers. No model server is started by Compose.

The application exposes one HTTP port (default `5173`). nginx serves the frontend and forwards `/api` to the internal backend. Supervisor manages the three processes; migrations run once before they start. The final image serves built static assets and runs without a Vite development server.

Query flow:

```text
user -> backend agent -> document retrieval -> optional reranker -> chat model -> answer with sources
```

## Documentation

- [Product vision](docs/01-product-vision.md)
- [Architecture](docs/02-architecture.md)
- [Technology stack](docs/03-stack.md)
- [Roadmap and implementation history](docs/04-roadmap.md)
- [Backlog notes](docs/05-backlog.md)
- [Decisions and open questions](docs/06-decisions-and-questions.md)
- [Vector database choice](docs/07-vector-db-choice.md)
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
Backend API:   http://localhost:5173/api
```

On a fresh database, the first registered account becomes the administrator. Open **Settings** to configure model servers, role assignments, models, OCR, and retrieval. Other users keep their own chat and document-processing preferences but cannot change shared infrastructure.

## Deployment Configuration

The Unraid application template, [`.env.unraid.example`](.env.unraid.example), needs only six variables:

```env
APP_NAME=ReceiptChat
SECRET_KEY=replace-with-a-long-random-secret
DATABASE_URL=postgresql+asyncpg://receiptchat:replace-password@POSTGRES_HOST:5432/receiptchat
COOKIE_SECURE=true
DOCUMENT_STORAGE_DIR=/app/storage/documents
DOCUMENT_MAX_UPLOAD_BYTES=10485760
```

Map container port **8080** in Unraid and persist the document directory and `/root/.EasyOCR`. Use `COOKIE_SECURE=false` only for local HTTP testing. URL-encode special characters in the database password when constructing `DATABASE_URL`.

Compose additionally uses `APP_PORT` for the host port, `POSTGRES_PASSWORD` for the database container, and `SP2_DATA_DIR` for production host storage. The frontend uses relative `/api`, so changing the reverse-proxy domain requires no frontend rebuild or CORS setup.

Keep `SECRET_KEY` stable and backed up: it signs login sessions and encrypts server passwords/API keys stored in PostgreSQL. The API returns only credential-presence flags, never stored secrets. Changing a server URL, API type, HTTP authentication scheme, or username clears its retained credentials unless replacements are entered. There are no SpeechCloud variables.

For an existing installation with no administrator, grant access to a registered account from the container console:

```bash
docker exec -it RECEIPTCHAT_CONTAINER python -m app.core.make_admin your-account@example.com
```

Old inference environment variables remain readable for direct-backend compatibility but are no longer passed by the application Compose files. Configure servers in the GUI after upgrading from env-only deployment; role assignments and document data are retained.

## llama.cpp on GPU and Helper Models on CPU

In Settings, each of the two server slots has its own URL, name, enabled switch, API type, HTTP authentication, and optional OpenAI bearer key. OpenAI-compatible mode supports model discovery, chat, multimodal structuring, and dedicated embedding models. Reranking currently requires the Ollama adapter.

Example GUI configuration for a preloaded llama.cpp model:

| Setting | Value |
| --- | --- |
| Server 1 | GPU llama.cpp, `http://192.168.40.201:8000`, OpenAI-compatible API |
| Chat and structuring roles | Server 1 |
| Chat and structuring model | Select the actual model ID returned by the server |
| Server 2 | CPU Ollama, `http://CPU_SERVER:11434`, Ollama API; enable when available |
| Embedding role | Server 2, select a dedicated embedding model |
| Reranking | Off, or Server 2 with a dedicated Qwen reranker |
| OCR | EasyOCR (CPU) or Tesseract (CPU) |
| Structuring input | OCR text and images; text-only if vision is unavailable |

Replace `CPU_SERVER` with the actual CPU runtime address. Verify the model ID with `curl http://192.168.40.201:8000/v1/models`; the returned ID is used without renaming. Both a root URL and a URL ending in `/v1` are accepted. Optional API keys are sent as bearer credentials. With no selected default model, the first available server model is used.

In Settings, assign **chat** and **structuring** to GPU llama.cpp, **embedding** to CPU Ollama, and optionally **reranking** to CPU Ollama with its dedicated model. Select the chat and structuring models again if previous user settings still name old models. Existing role assignments persist across deployment; changing environment defaults does not replace them. The CPU Ollama process must itself be configured without GPU access; choosing a role in ReceiptChat only selects its server.

EasyOCR runs on CPU (`gpu=False`), as does Tesseract. For image input, llama.cpp must have vision enabled and the matching multimodal projector loaded. Otherwise select text-only input in Settings. The same section controls the external OCR model/prompt, retrieval and reranking candidate counts, and model request timeout. The chat model does not replace a dedicated retrieval embedding model; after changing embedding models, reindex existing documents by saving or rerunning structuring. CPU latency depends on model size and hardware and should be measured.

## RAG and Reranker

After OCR and structuring, each document is converted into text suitable for RAG. The indexed text includes the summary, metadata, merchant, date, amounts, items, quantities, unit prices, raw item text, and user notes.

The reranker is an optional second stage applied to candidates from vector search. The model receives a query-document pair and is instructed to answer `yes` or `no`; the backend uses the logprobs of the `yes` and `no` tokens to compute a relevance score. The default minimum threshold is `0.50`. A lower value such as `0.1` helped short follow-up questions in a previous deployment; tune this against your own documents. If token logprobs are unavailable, the Ollama adapter falls back to a binary yes/no score.

## Tests

Backend:

```bash
docker compose -f docker-compose.test.yml run --build --rm backend-test
```

Frontend:

```bash
docker compose -f docker-compose.test.yml run --build --rm frontend-test
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
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build --remove-orphans
```

Point one reverse-proxy host to `http://DOCKER_HOST:5173` (or your `APP_PORT`). The same domain serves the web UI and `/api`; no separate API port is published. Keep `COOKIE_SECURE=true` behind production HTTPS.

Logs and health:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 -f receiptchat
curl http://localhost:5173/api/health
docker compose --env-file .env.production -f docker-compose.prod.yml exec receiptchat supervisorctl -c /app/docker/supervisord.conf status
```

The container healthcheck verifies nginx, the API, and the worker. Supervisor restarts crashed processes. On worker restart, interrupted OCR/structuring jobs return to the queue; a database advisory lock prevents two workers from processing the same database concurrently. Deploy one application instance per database.

For the first upgrade from separate frontend/backend/worker containers, back up data and stop the old stack before starting the combined service:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml down --remove-orphans
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build --remove-orphans
```

Do not add `-v` to `down`. Existing production data paths and local named volumes are preserved.

When upgrading, migration `0019_remove_voice` removes the former voice-session table and TTS preference. Existing text chat history and documents are preserved. Back up the database before upgrading. The compose command removes obsolete application containers; ports 8000 and 8888 are no longer published.

See [production deployment notes](docs/11-production-deploy.md) for details.

## Security Notes

- Real `.env` and `.env.production` files must not be committed.
- PostgreSQL is not exposed through a public port in the production compose file.
