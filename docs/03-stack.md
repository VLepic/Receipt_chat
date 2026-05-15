# Technologický stack

## Doporučený stack pro MVP

| Vrstva | Doporučení | Poznamka |
| --- | --- | --- |
| Frontend | React + Vite + TypeScript | Rychly vyvoj SPA, jednoduche napojeni na API |
| UI | Tailwind CSS + vlastni design tokens | Styl musi navazovat na `http://127.0.0.1:4173/` a `https://hdsrecorder.vaclavlepic.com/` |
| Backend | Python + FastAPI | Vhodne pro API, streaming a integrace s ML nastroji |
| Validace | Pydantic | Prirozene sedi k FastAPI |
| Databaze | PostgreSQL | Stabilni zaklad pro uzivatele, chat a dokumenty |
| ORM/migrace | SQLAlchemy + Alembic | Kontrolovatelny schema vyvoj |
| Auth | FastAPI Users + SQLAlchemy adapter | MVP: email + heslo, secure HTTP-only cookie |
| Password hashing | pwdlib Argon2 | Vychozi hashing ve FastAPI Users, s kompatibilitou pro bcrypt |
| Social login | Authlib pro Google/OIDC | Volitelna pozdejsi faze, ne blokator MVP |
| LLM runtime | Externi Ollama server | Backend a speech-dialog se pripojuji pres `OLLAMA_BASE_URL`; extrakce dokladu pouziva hybridni OCR text + obrazky |
| Voice ASR/TTS | SpeechCloud.dialog | Hlavni knihovna pro hlasovy dialog, ASR, TTS a WebSocket dialog manager |
| RAG index | PostgreSQL + pgvector | Jeden databazovy system pro metadata i embeddings |
| Background jobs | RQ/Celery + Redis nebo FastAPI background tasks | Redis az ve fazi OCR/RAG pipeline |
| File storage | Lokalni filesystem v dev, pozdeji S3/MinIO | Dokumenty neukladat primo do relacni DB |
| OCR | Ollama `glm-ocr:latest` + EasyOCR/Tesseract fallback | Vychozi OCR engine vola externi Ollama vision model; EasyOCR (`cs,en`) a Tesseract (`ces+eng`) zustavaji jako lokalni fallback |
| Dev env | Docker Compose | Databaze, backend, frontend a speech-dialog spustitelne jednotne; Ollama externi nebo volitelny profil |

## Docker Compose sluzby

Navrzeny lokalni compose stack:

- `frontend`: React/Vite webova aplikace.
- `backend`: Python/FastAPI API.
- `speech-dialog`: Python SpeechCloud.dialog manager vychazejici z `example`.
- `postgres`: PostgreSQL s rozsirenim `pgvector`.
- `ollama`: volitelny lokalni LLM server jen pres compose profile `local-ollama`.
- `redis`: volitelne pro background jobs ve fazi OCR/RAG.
- `minio`: volitelne pro S3-like uloziste dokumentu v pozdejsi fazi.

Pro MVP je povinne `frontend`, `backend`, `speech-dialog` a `postgres`. Ollama se primarne pouziva jako externi server pres `OLLAMA_BASE_URL`. `redis` a `minio` muzou prijit az s OCR pipeline.

## Vektorova databaze

Vychozi volba je `PostgreSQL + pgvector`. Technicky to neni samostatna specializovana vektorova databaze, ale PostgreSQL rozsirene o vektorove sloupce a indexy. Pro tento projekt je to dobra prvni volba, protoze:

- metadata dokumentu, uzivatele, chat i embeddings zustanou v jednom systemu;
- jednoduse se provozuje v Docker Compose;
- dobre sedi k SQLAlchemy/Alembic migracim;
- pro mensi a stredni objem uctenek/faktur bude dostacujici.

Specializovanou vektorovou databazi, napriklad Qdrant, Chroma nebo Milvus, dava smysl pridat az ve chvili, kdy pgvector nebude stacit vykonem, filtrovani metadat bude prilis slozite, nebo bude potreba samostatna retrieval infrastruktura. Detailni srovnani je v [Volba vektorove databaze](07-vector-db-choice.md).

## Doporučení pro první implementaci

Pro chat-only MVP staci:

- FastAPI backend.
- React/Vite frontend.
- PostgreSQL s pripravenou moznosti `pgvector`; v chat-only MVP se embeddings jeste nemusi pouzivat.
- Externi Ollama server dostupny pres konfiguraci `OLLAMA_BASE_URL`.
- SpeechCloud.dialog manager dostupny na verejne nebo proxy dostupne WebSocket adrese pro SpeechCloud platformu.
- Auth pres email + heslo, idealne pres FastAPI Users.
- Jednoduchy `.env` config.

## Autentizace

Vychozi varianta pro MVP:

- prihlasovaci identita: `email`;
- heslo: hashovane pres Argon2;
- knihovna: `FastAPI Users` se SQLAlchemy adapterem;
- transport: secure HTTP-only cookie;
- cookie atributy: `HttpOnly`, `SameSite=Lax` pro lokalni web flow, `Secure` v produkci za HTTPS;
- nepouzivat `localStorage` pro auth tokeny.

Google login:

- nepridavat do prvniho MVP jako povinnost;
- pripravit datovy model tak, aby pozdeji slo pripojit OAuth ucet ke stejnemu uzivateli;
- pokud se prida, pouzit `Authlib` pro Google OpenID Connect/OAuth flow.

Rozhodnuti pro prvni implementaci: email + heslo + secure HTTP-only cookie. Google OAuth az po stabilizaci zakladniho prihlaseni, chatu a SpeechCloud/Ollama flow.

## Modely v Ollama

Kandidati pro chat na externim Ollama serveru:

- `llama3.1` nebo novejsi dostupny na serveru.
- `qwen2.5` / `qwen3` podle dostupnosti a vykonu.
- Mensi model pro rychlost, vetsi model pro presnost.

Kandidati pro OCR a strukturovani dokladu:

- `glm-ocr:latest` jako vychozi OCR engine pro komplexni dokumenty a tabulky; podle Ollama podporuje prompty `Text Recognition:`, `Table Recognition:` a `Figure Recognition:`.
- `deepseek-ocr:latest` jako alternativa pro prevod obrazku/PDF stranky na text nebo markdown.
- `gemma4:26b` jako kandidat pro nasledne strukturovani OCR textu do JSONu a tvorbu popisku.
- Flow pro nejblizsi verzi je OCR model -> text -> multimodalni LLM strukturace z OCR textu i obrazku. Spolehlivost ma prednost pred rychlosti a uspornymi rezimy.

OCR prompt je konfigurovatelny pres `OLLAMA_OCR_PROMPT`.
Vychozi prompt pro GLM-OCR je `Text Recognition:`, protoze pro naslednou LLM strukturaci je dulezitejsi kompletnost celeho dokladu nez samotne tabulky.
Pro ciste tabulkove vyrezy lze testovat `Table Recognition:`. Pro DeepSeek-OCR lze testovat `<|grounding|>Convert the document to markdown.`.

Kandidati a aktualni nastaveni pro embeddings v RAG fazi:

- Prvni implementace vola Ollama embedding endpoint a uklada vysledek do PostgreSQL/pgvector.
- Vychozi Docker Compose hodnota je `RAG_EMBEDDING_MODEL=qwen3-embedding:latest`, protoze tento embedding model je dostupny na pouzivanem externim Ollama serveru.
- Pokud `RAG_EMBEDDING_MODEL` neni nastaveny nebo tabulka `document_chunks` jeste neexistuje, RAG se bezpecne preskoci a chat funguje bez dokumentoveho kontextu.
- Ollama embedding model lze pozdeji zmenit podle kvality hledani nad ceskymi dotazy a doklady.
- Alternativne specializovany sentence-transformer model pres Python sluzbu.

## Alternativy

- Frontend lze misto React/Vite postavit v Next.js, pokud bude potreba SSR, jednodussi routing s auth middlewarem nebo deployment na platformy typu Vercel.
- RAG lze postavit pres LlamaIndex nebo LangChain, ale pro prvni verzi je vhodne drzet adapter tenky a nevazat business logiku primo na framework.
- Pro mensi lokalni verzi lze misto PostgreSQL pouzit SQLite, ale pgvector a produkcni smer mluvi pro PostgreSQL uz od zacatku.
