# Backlog

## Epic: projektový základ

- Zalozit strukturu backendu.
- Zalozit strukturu frontendu.
- Pripravit `.env.example`.
- Pripravit Docker Compose pro PostgreSQL a aplikacni sluzby.
- Pridat zakladni README pro spusteni.

## Epic: autentizace

- Registrace uzivatele.
- Prihlaseni uzivatele pres email + heslo.
- Odhlaseni.
- Hashovani hesel pres Argon2.
- Secure HTTP-only cookie auth.
- Ochrana API endpointu.
- Frontend stav prihlaseni.
- Datovy model pripravit na pozdejsi OAuth identity.
- Google OAuth nechat jako volitelne rozsireni po MVP.

## Epic: chat

- Vytvoreni konverzace.
- Seznam konverzaci.
- Detail konverzace.
- Odeslani zpravy.
- Zobrazeni odpovedi asistenta.
- Ulozeni historie.
- Mazani nebo archivace konverzace.
- Volitelne streamovani odpovedi.

## Epic: Ollama integrace

- Konfigurace `OLLAMA_BASE_URL`.
- Konfigurace vychoziho modelu.
- Persistentni nastaveni modelu pro chat, OCR post-processing, extrakci a embeddings.
- Health check Ollama serveru.
- Adapter pro chat completion.
- Adapter pro LLM JSON extrakci nad OCR textem.
- Timeouty a srozumitelne chybove odpovedi.
- Logovani modelu pouziteho pro odpoved.

## Epic: SpeechCloud integrace

- Prostudovat `docs/SpeechCloud.dialog.md`.
- Vyuzit `example/dialog.py` jako knihovni zaklad nebo referencni implementaci.
- Vyuzit `example/example_cviceni_chat.py` jako ukazku flow ASR -> Ollama -> TTS.
- Presunout pristupove udaje do `.env` a nikdy je nedrzet natvrdo v kodu.
- Vytvorit `speech-dialog` kontejner pro Docker Compose.
- Nastavit WebSocket endpoint dialog manageru.
- Nastavit staticky SpeechCloud HTML klient nebo napojeni na vlastni frontend.
- Logovat SpeechCloud session id a chyby ASR/TTS.

## Epic: dokumenty pro budoucí fáze

- Navrhnout tabulku `documents`.
- Navrhnout upload endpoint.
- Navrhnout stavovy model zpracovani.
- Pripravit interface pro OCR worker.
- Pripravit interface pro RAG retrieval.
- Navrhnout review workflow pro LLM popisek a strukturovana pole.
- V detailu dokladu zobrazit "slozku" dokladu: original, OCR text, metadata, popisek, extrahovana pole a historii zpracovani.
- Chat odpovedi maji odkazovat na detail dokladu, pokud pouziji jeho data.

## Epic: kvalita

- Unit testy backend sluzeb.
- API testy pro auth a chat.
- Minimalni frontend smoke test.
- Lint a format.
- Zakladni monitoring/logovani pro lokalni vyvoj.
- Testovaci body udrzovat primarne v roadmapě u jednotlivych fazi.

## První sprint návrh

1. Zalozit backend skeleton ve FastAPI.
2. Zalozit frontend skeleton ve React/Vite.
3. Implementovat auth pres email + heslo + secure HTTP-only cookie.
4. Implementovat Ollama health check.
5. Implementovat jednoduchy chat endpoint bez perzistence.
6. Pridat databazi a migrace.
7. Pridat uzivatele, konverzace a zpravy.
8. Zprovoznit SpeechCloud dialog manager podle `example/example_cviceni_chat.py`.
9. Napojit frontend na realne API.
