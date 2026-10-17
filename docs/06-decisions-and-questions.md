# Rozhodnutí a otevřené otázky

## Navržená rozhodnutí

### D1: Backend bude ve FastAPI

FastAPI dobre sedi na Python API, validaci pres Pydantic, OpenAPI dokumentaci a budouci streaming odpovedi z modelu.

### D2: Ollama bude za adapterem

Kod chatu nebude volat Ollama primo z mnoha mist. Vznikne `llm` modul, ktery schova HTTP komunikaci, konfiguraci modelu, timeouty a format odpovedi.

### D2a: Ollama bude primarne externi server

Backend podporuje externi Ollama i OpenAI kompatibilni endpoint. Protokol, URL a pristupove udaje kazdeho serveru nastavuje spravce v GUI. Modelove servery nejsou soucasti Compose stacku.

### D3: RAG bude oddelená služba uvnitř backendu

Chat service si vyzada relevantni kontext pres `rag` modul. Diky tomu pujde prvni chat-only verzi postavit bez RAG a pozdeji ji doplnit bez prepisu UI.

### D4: PostgreSQL bude hlavní databáze

PostgreSQL pokryje uzivatele, chat, dokumentova metadata a pres pgvector i budouci embeddings. Tim se omezi pocet infrastrukturnich komponent v prvnich fazich.

### D5: Vektorova vrstva bude nejdriv pgvector

Pro RAG se nejdriv pouzije `pgvector` v PostgreSQL kontejneru. Specializovana vektorova databaze jako Qdrant, Chroma nebo Milvus zustava alternativa pro pozdejsi fazi, pokud naroste objem dokumentu nebo naroky na retrieval.

### D6: Lokalni prostredi pobezi pres Docker Compose

Frontend, backend API a OCR worker bezi jako procesy jednoho aplikacniho kontejneru; PostgreSQL zustava samostatne. Ollama i llama.cpp jsou externi endpointy. Pozdeji lze pridat Redis pro job queue a MinIO pro dokumentove soubory.

### D8: MVP prihlasovani bude email + heslo

Prvni verze pouzije email jako prihlasovaci identitu a heslo hashovane pres Argon2. Doporučená knihovna je `FastAPI Users` se SQLAlchemy adapterem, protoze poskytuje hotove routery pro registraci, login/logout, aktualniho uzivatele, reset hesla, overeni emailu a OAuth rozsireni. Google prihlaseni bude volitelna pozdejsi faze pres `Authlib` nebo OAuth router ve FastAPI Users.

### D9: Auth transport bude secure HTTP-only cookie

Webova aplikace bude pouzivat secure HTTP-only cookie. Frontend nebude ukladat auth tokeny do `localStorage`. V produkci musi cookie bezet pres HTTPS se `Secure`; pro bezny web flow pouzit `SameSite=Lax`, pokud se pozdeji neukaze potreba jineho nastaveni.

### D10: OCR text bude vstup pro LLM post-processing

Raw a normalizovany OCR text se uklada kvuli auditu a debugovani. Pro strukturovana data a semanticke vyhledavani se pouzije dalsi LLM krok pres Ollama s few-shot promptem. Vysledkem bude JSON s poli dokladu a kratky lidsky popisek.

### D11: Popisek dokladu bude reviewovatelny

Vygenerovany popisek a hlavni extrahovana pole nebudou automaticky povazovana za schvalena. Uzivatel je po nahrani zkontroluje, upravi nebo schvali. Pro RAG se preferuje schvaleny popisek; draft hodnoty mohou byt oznacene jako nejiste.

### D12: Chat bude odkazovat na detail celeho dokladu

Pokud model v chatu pouzije data z dokladu, odpoved musi umet vratit odkaz na detail dokladu ve strance Doklady. UI nebude zobrazovat pouze textovou citaci, ale klikatelny odkaz na celou "slozku" dokladu.

## Otevřené otázky

1. Ma byt aplikace primarne lokalni pro jednoho uzivatele, nebo od zacatku multi-user?
2. Ma byt frontend React/Vite, nebo chces Next.js?
3. Ktere modelove servery a autentizaci nakonfigurovat v GUI pro produkcni provoz?
4. Jake typy dokumentu budou prvni: PDF faktury, fotky uctenek, skeny, nebo vse najednou?
5. Je prioritou cestina, nebo i anglictina/nemcina na fakturach?
6. Chces ve fazi RAG citace na konkretni dokument a pasaz?
7. Ktere modely budou vychozi pro chat, OCR post-processing, extrakci a embeddings?
8. Ma se neschvaleny popisek pouzivat v RAG, nebo az po rucnim schvaleni?
9. Ma aplikace umet export do CSV/Excel nebo napojeni na ucetni system?

## Rizika

- OCR kvalita u fotek uctenek muze byt vyrazne horsi nez u PDF faktur.
- Mensi LLM modely mohou mit potize se spolehlivou extrakci strukturovanych dat.
- RAG bez citaci muze davat odpovedi, ktere se hure overuji.
- Pokud se auth strategie zmeni pozde, muze to znamenat upravy frontend i backend architektury.

## Doporučené další rozhodnutí

Pro prakticky provoz overit presny model z `/v1/models`, podporu obrazku a vykon pomocnych modelu na CPU. Auth metoda i transport jsou rozhodnute: email + heslo + secure HTTP-only cookie.
