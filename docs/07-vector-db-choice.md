# Volba vektorove databaze: pgvector vs Qdrant

## Kontext

Projekt bude mit RAG nad uctenkami a fakturami. Vektorova vrstva bude slouzit k ulozeni embeddingu OCR textu a k vyhledavani relevantnich casti dokumentu pri chatovani.

Prvni RAG verze bude bezet lokalne pres Docker Compose. V systemu uz bude PostgreSQL kvuli uzivatelum, autentizaci, historii chatu a metadatum dokumentu.

## Kratke srovnani

| Oblast | pgvector | Qdrant |
| --- | --- | --- |
| Typ | PostgreSQL extension | Samostatna vektorova databaze |
| Provoz | Jeden `postgres` kontejner | Extra `qdrant` kontejner |
| Data a metadata | SQL tabulky, JOINy, transakce | Points, vectors, JSON payload |
| Indexy | Exact search, HNSW, IVFFlat | HNSW, payload indexy, optimalizace pro vector search |
| Filtrovani | SQL `WHERE`, indexy, partial indexy, partitioning | Payload filters navrzene primo pro vector search |
| Migrace | Alembic/SQL migrace ve stejnem DB schematu | Samostatne kolekce a schema mimo hlavni DB |
| Komplexita MVP | Nizsi | Vyssi |
| Skalovani retrievalu | Dobre pro mensi az stredni objem | Lepsi specializovana cesta pro vetsi RAG |
| Vendor/runtime lock-in | Vazba na PostgreSQL | Vazba na Qdrant API |

## pgvector

Silne stranky:

- Staci jeden databazovy system pro aplikacni data i embeddings.
- Jednoduche spusteni v Docker Compose.
- Embeddings lze vazat primo na `document_id`, `user_id`, `conversation_id` a dalsi relacni data.
- SQL dotazy, transakce, backupy a migrace zustavaji na jednom miste.
- Podporuje exact search i approximate nearest neighbor indexy HNSW a IVFFlat.

Slabsi stranky:

- Pri velkem objemu dat muze byt potreba vice ladeni PostgreSQL.
- Filtrovani u approximate indexu je citlive na nastaveni a datovy model.
- Mene specializovanych retrieval funkci nez u dedikovane vector DB.

## Qdrant

Silne stranky:

- Je navrzeny primo jako vector search engine.
- Ma prirozeny model `collection -> point -> vector + payload`.
- Payload filtry jsou primo soucast search API.
- Dobre sedi na slozitejsi filtrovani, vice kolekci, vice vektoru na jeden objekt, hybridni a pokrocile retrieval scenare.
- Samostatny retrieval kontejner lze skalovat oddelene od aplikacni databaze.

Slabsi stranky:

- Pridava dalsi sluzbu do Docker Compose.
- Metadata dokumentu budou rozdelena mezi PostgreSQL a Qdrant, takze je potreba synchronizace.
- Je potreba resit konzistenci mezi hlavni databazi a vector DB.
- Pro male MVP muze byt zbytecne robustni.

## Doporučení pro tento projekt

Zacit s `PostgreSQL + pgvector`.

Duvod: prvni cil je chat-only MVP a potom RAG nad osobnimi/firemnim doklady. Ocekavany objem dat na zacatku nebude tak velky, aby ospravedlnil samostatnou vector DB. pgvector zjednodusi Docker Compose, migrace, zalohy i vazbu embeddings na uzivatelska prava.

## Kdy prejit na Qdrant

Qdrant pridat, pokud nastane nektera z techto situaci:

- vyhledavani nad dokumenty zacne byt pomale i po indexech a ladeni PostgreSQL;
- bude hodne dokumentu, chunku nebo uzivatelu;
- bude potreba slozite filtrovani podle mnoha metadat;
- bude potreba samostatne skalovat retrieval;
- aplikace zacne pouzivat vice typu embeddingu, hybridni search nebo pokrocile reranking pipeline;
- synchronizace dat mezi PostgreSQL a vector DB bude prijatelna cena za vyssi retrieval vykon.

## Navrzeny mezikrok

RAG modul navrhnout pres vlastni interface:

- `VectorStore.add_chunks(...)`
- `VectorStore.search(...)`
- `VectorStore.delete_document(...)`

Prvni implementace muze byt `PgVectorStore`. Pokud bude potreba, pozdeji lze pridat `QdrantVectorStore` bez prepisu chat service.

## Rozhodnutí

Aktualni rozhodnuti: `pgvector` pro MVP a prvni RAG fazi.

Qdrant zustava planovana alternativa pro skalovani a pokrocily retrieval.

## Stav implementace

Prvni implementace pouziva tabulku `document_chunks` v PostgreSQL s pgvector sloupcem `embedding`. Chunk je zatim jeden na doklad a obsahuje deterministicky slozeny `rag_text`: summary, dulezita strukturovana pole a polozky. Cely OCR text se do embeddingu nedava, aby se neoslaboval vyznam dotazu dlouhym sumem a pravnimi patickami.

Embedding model je konfigurovany pres `RAG_EMBEDDING_MODEL`; v Docker Compose je vychozi `qwen3-embedding:latest`.
