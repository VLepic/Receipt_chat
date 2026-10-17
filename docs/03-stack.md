# Technologický stack

## Aktualni stack

| Vrstva | Doporučení | Poznamka |
| --- | --- | --- |
| Frontend | React + Vite + TypeScript | Rychly vyvoj SPA, jednoduche napojeni na API |
| UI | Vlastni CSS + design tokens | Styl musi navazovat na `http://127.0.0.1:4173/` a `https://hdsrecorder.vaclavlepic.com/` |
| Backend | Python + FastAPI | Vhodne pro API, streaming a integrace s ML nastroji |
| Validace | Pydantic | Prirozene sedi k FastAPI |
| Databaze | PostgreSQL | Stabilni zaklad pro uzivatele, chat a dokumenty |
| ORM/migrace | SQLAlchemy + Alembic | Kontrolovatelny schema vyvoj |
| Auth | FastAPI Users + SQLAlchemy adapter | Email + heslo, secure HTTP-only cookie |
| Password hashing | pwdlib Argon2 | Vychozi hashing ve FastAPI Users, s kompatibilitou pro bcrypt |
| Social login | Authlib pro Google/OIDC | Volitelne rozsireni, neni soucast aktualniho provozu |
| LLM runtime | Ollama nebo llama.cpp | Protokol `ollama` nebo `openai` se konfiguruje pro kazdy server; strukturace muze pouzit OCR text i obrazky |
| RAG index | PostgreSQL + pgvector | Jeden databazovy system pro metadata i embeddings |
| Background jobs | Samostatny worker proces v `receiptchat` | OCR a zpracovani dokumentu bezi mimo request/response flow |
| File storage | Lokalni filesystem v dev, pozdeji S3/MinIO | Dokumenty neukladat primo do relacni DB |
| OCR | EasyOCR, Tesseract nebo externi vision model | Vychozi engine je EasyOCR na CPU; engine, model a prompt vybira spravce v GUI |
| Provoz | Docker Compose | Jeden aplikacni kontejner a samostatna databaze; oba typy modelovych serveru jsou externi |

## Docker Compose sluzby

- `receiptchat`: nginx, staticky React frontend, FastAPI API a OCR worker v jednom image.
- `postgres`: samostatna PostgreSQL databaze s pgvector.

Modelove servery Ollama i llama.cpp jsou externi a konfiguruji se v GUI (vcetne URL a pristupovych udaju). Zadny modelovy server Compose nespousti. Supervisor ridi aplikacni procesy; migrace se provadeji pred jejich spustenim. Vychozi verejny port je 5173, kontejner nasloucha na 8080 a API je dostupne na stejne domene pod `/api`.

## Vektorova databaze

Vychozi volba je `PostgreSQL + pgvector`. Technicky to neni samostatna specializovana vektorova databaze, ale PostgreSQL rozsirene o vektorove sloupce a indexy. Pro tento projekt je to dobra prvni volba, protoze:

- metadata dokumentu, uzivatele, chat i embeddings zustanou v jednom systemu;
- jednoduse se provozuje v Docker Compose;
- dobre sedi k SQLAlchemy/Alembic migracim;
- pro mensi a stredni objem uctenek/faktur bude dostacujici.

Specializovanou vektorovou databazi, napriklad Qdrant, Chroma nebo Milvus, dava smysl pridat az ve chvili, kdy pgvector nebude stacit vykonem, filtrovani metadat bude prilis slozite, nebo bude potreba samostatna retrieval infrastruktura. Detailni srovnani je v [Volba vektorove databaze](07-vector-db-choice.md).

## Aktualni provozni doporuceni

- FastAPI backend.
- React/Vite frontend.
- PostgreSQL s `pgvector`.
- Externi Ollama nebo OpenAI kompatibilni server nastavitelny v aplikaci.
- Volitelny druhy server pro oddeleni chat/embedding/reranking/OCR/structuring roli.
- Auth pres email + heslo, idealne pres FastAPI Users.
- Jednoduchy `.env` config.

## Autentizace

Vychozi varianta:

- prihlasovaci identita: `email`;
- heslo: hashovane pres Argon2;
- knihovna: `FastAPI Users` se SQLAlchemy adapterem;
- transport: secure HTTP-only cookie;
- cookie atributy: `HttpOnly`, `SameSite=Lax` pro lokalni web flow, `Secure` v produkci za HTTPS;
- nepouzivat `localStorage` pro auth tokeny.

Google login:

- nepridavat jako povinnost;
- pripravit datovy model tak, aby pozdeji slo pripojit OAuth ucet ke stejnemu uzivateli;
- pokud se prida, pouzit `Authlib` pro Google OpenID Connect/OAuth flow.

Rozhodnuti pro prvni implementaci: email + heslo + secure HTTP-only cookie. Google OAuth az po stabilizaci zakladniho prihlaseni, chatu a dokumentove pipeline.

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

OCR prompt je konfigurovatelny v nastaveni OCR a zpracovani.
Vychozi prompt pro GLM-OCR je `Text Recognition:`, protoze pro naslednou LLM strukturaci je dulezitejsi kompletnost celeho dokladu nez samotne tabulky.
Pro ciste tabulkove vyrezy lze testovat `Table Recognition:`. Pro DeepSeek-OCR lze testovat `<|grounding|>Convert the document to markdown.`.

Kandidati a aktualni nastaveni pro embeddings v RAG fazi:

- Prvni implementace vola Ollama embedding endpoint a uklada vysledek do PostgreSQL/pgvector.
- Embedding model se vybira v GUI ze seznamu na prirazenem serveru; neni predem zapnuty velky model.
- Pokud neni embedding model vybrany nebo tabulka `document_chunks` jeste neexistuje, vektorove vyhledavani se preskoci; strukturovane vyhledavani nad dokumenty je samostatna cesta.
- Ollama embedding model lze pozdeji zmenit podle kvality hledani nad ceskymi dotazy a doklady.
- Alternativne specializovany sentence-transformer model pres Python sluzbu.

Reranker:

- Volitelne se pouziva model kompatibilni s generovanim `yes`/`no` nad dvojici dotaz-dokument.
- Backend z `logprobs` tokenu `yes` a `no` pocita skore relevance.
- Vychozi minimalni prah je `0.50`; hodnota `0.1` se v drivejsim nasazeni osvedcila pro navazujici dotazy. Prah je potreba overit na vlastnich datech.
- Reranker lze pres nastaveni aplikace priradit na jiny Ollama server nez chat nebo embedding.

## Produkcni compose

Produkce pouziva `docker-compose.prod.yml`, jeden aplikacni image se statickym frontendem a externi reverse proxy pro frontend a backend API. API a worker dedi stejnou konfiguraci jednoho aplikacniho kontejneru.

## Alternativy

- Frontend lze misto React/Vite postavit v Next.js, pokud bude potreba SSR, jednodussi routing s auth middlewarem nebo deployment na platformy typu Vercel.
- RAG lze postavit pres LlamaIndex nebo LangChain, ale pro prvni verzi je vhodne drzet adapter tenky a nevazat business logiku primo na framework.
- Pro mensi lokalni verzi lze misto PostgreSQL pouzit SQLite, ale pgvector a produkcni smer mluvi pro PostgreSQL uz od zacatku.

## OpenAI kompatibilni API

Typ API `OpenAI kompatibilni / llama.cpp` v nastaveni serveru pouziva `/v1/models`, `/v1/chat/completions` a `/v1/embeddings`. Zakladni URL muze byt s `/v1` i bez nej. Volitelny bearer klic se zadava v GUI, uklada se sifrovane a API jej nevraci. Stare inference env promenne zustavaji pouze kompatibilni pro primo spousteny backend, Compose je nepredava.

Chat a strukturovani lze priradit prednactenemu GPU modelu v llama.cpp; embeddingy a reranking samostatnemu CPU Ollama serveru. EasyOCR a Tesseract bezi na CPU. Reranking pres OpenAI kompatibilni endpoint zatim implementovany neni.
