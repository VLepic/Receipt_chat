# Produkcni nasazeni

## Sluzby a sit

`docker-compose.prod.yml` spousti pouze `receiptchat` a `postgres`. Aplikacni kontejner obsahuje nginx, sestaveny frontend, API a OCR/structuring worker. Ollama i llama.cpp zustavaji externi, konfigurovatelne zdroje.

Aplikace publikuje jeden port:

```env
APP_PORT=5173
```

Reverse proxy smeruje `receiptchat.vaclavlepic.com` na `http://DOCKER_HOST:5173`. Web i API jsou na stejne domene, API ma prefix `/api`. Interni backend port 8000 se nepublikuje. Samostatna API domena uz neni potreba; pripadnou puvodni API domenu lze docasne smerovat na stejny aplikacni port.

## Konfigurace

Zkopirujte `.env.production.example` do `.env.production` a nastavte zejmena:

```env
SECRET_KEY=novy-nahodny-secret
POSTGRES_PASSWORD=silne-heslo
SP2_DATA_DIR=/opt/stacks/sp2/data
APP_PORT=5173
COOKIE_SECURE=true
```

HTTPS zajistuje externi reverse proxy. Protoze frontend pouziva relativni `/api`, pro zmenu domeny neni treba rebuildovat image. `VITE_API_BASE_URL`, `BACKEND_PORT` a `BACKEND_PUBLIC_URL` se v novem stacku nepouzivaji. Pokud `APP_PORT` chybi, Compose respektuje puvodni `FRONTEND_PORT`.

Zdrojove servery, jejich adresy a prihlasovaci udaje se nastavuji v GUI. Spravce ma dva sloty pro Ollama nebo OpenAI kompatibilni API (llama.cpp), prirazeni roli, modely a nastaveni OCR/RAG. Druhy server muze zustat vypnuty. Modely se vybiraji ze seznamu dostupneho na prirazenem serveru. Modelove servery nejsou soucasti aplikacniho kontejneru.

Hesla a API klice jsou ulozene v PostgreSQL zasifrovane pomoci `SECRET_KEY`; ten proto nemente pri kazdem nasazeni a zalohujte jej spolu s databazi. Zmena adresy nebo identity serveru zrusi zachovane prihlasovaci udaje, pokud nezadate nove. API ulozena hesla nevraci.

Prvni ucet zaregistrovany v prazdne databazi je spravce. Existujici instalaci bez spravce nastavte po registraci uctu prikazem:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec receiptchat python -m app.core.make_admin vas-email@example.com
```

Stare `OLLAMA_*` a OCR/RAG promenne uz Compose nepredava. Pri prvnim upgradu z env-only nastaveni nakonfigurujte servery v GUI; databaze dokumentu i existujici prirazeni roli zustavaji.

## Unraid Docker UI

Pro aplikaci pouzijte sestaveny image z korenoveho `Dockerfile` a sest promennych z `.env.unraid.example`. Kontejner publikuje HTTP port **8080**. Mapujte dokumenty do `/app/storage/documents` (nebo jineho `DOCUMENT_STORAGE_DIR`) a cache OCR do `/root/.EasyOCR`, napriklad:

| Host | Kontejner |
| --- | --- |
| `/mnt/user/appdata/receiptchat/documents` | `/app/storage/documents` |
| `/mnt/user/appdata/receiptchat/easyocr` | `/root/.EasyOCR` |

PostgreSQL je samostatny kontejner. Pro **novou databazi** lze pouzit `pgvector/pgvector:pg18` s promennymi `POSTGRES_DB=receiptchat`, `POSTGRES_USER=receiptchat` a vlastnim silnym `POSTGRES_PASSWORD`. U PostgreSQL 18 mapujte `/mnt/user/appdata/receiptchat-postgres` do **`/var/lib/postgresql`**; ne do stareho `/var/lib/postgresql/data`. Viz [pgvector image](https://github.com/pgvector/pgvector#docker) a [Postgres image](https://hub.docker.com/_/postgres).

Oba kontejnery pripojte do stejne uzivatelske Docker site a pouzijte jmeno DB kontejneru v `DATABASE_URL`, nebo pouzijte routovatelnou IP/port databaze. Heslo v URL musi byt URL-encoded, obsahuje-li specialni znaky. Databazi nepublikujte na internet. Privileged ani Docker socket nejsou potreba.

Repozitarovy Compose ponechava PostgreSQL 16 kvuli kompatibilite existujicich dat. Existujici PG16 adresar nelze spustit pod PG18 pouze zmenou tagu; nejprve pouzijte dump/restore nebo `pg_upgrade`. Pri novem prazdnem DB kontejneru aplikace provede migrace automaticky.

## Start a aktualizace

Prvni spusteni:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Pri prvnim prechodu ze stareho vicekontejneroveho stacku nejprve zalohujte databazi a dokumenty, aktualizujte repozitar a zastavte stare procesy:

```bash
git pull
docker compose --env-file .env.production -f docker-compose.prod.yml down --remove-orphans
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build --remove-orphans
```

Nepouzivejte `down -v`. Produkcni adresare i puvodni lokalni named volumes zustavaji zachovane. Aktualizace zastavi rozpracovane pozadavky; po restartu worker vrati prerusene OCR/structuring joby do fronty. Provozujte jednu aplikacni instanci na databazi.

Migrace bezi jednou pred startem procesů. Historicka migrace `0019_remove_voice` odstrani pouze hlasove sessions a TTS preference; textove konverzace a dokumenty zustanou. Stare samostatne porty 8000 a 8888 uz nejsou potreba.

## Perzistentni data

```text
/opt/stacks/sp2/data/postgres
/opt/stacks/sp2/data/documents
/opt/stacks/sp2/data/easyocr
```

PostgreSQL nema publikovany hostitelsky port. Kontejner aplikace neni privileged a nevyzaduje Docker socket ani GPU. Modelove servery se pripojuji po siti.

## Kontrola a logy

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs --tail=100 -f receiptchat
docker compose --env-file .env.production -f docker-compose.prod.yml exec receiptchat supervisorctl -c /app/docker/supervisord.conf status
curl http://localhost:5173/health
curl http://localhost:5173/api/health
```

Healthcheck overuje vsechny tri procesy i odpoved API pres nginx. Supervisor restartuje spadle procesy; databazovy advisory lock zabranuje soubeznemu behu dvou workeru. Kontejner ma pri zastaveni 90 sekund na ukonceni procesů.

