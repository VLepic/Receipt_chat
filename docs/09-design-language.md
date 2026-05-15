# Designovy jazyk

## Reference

Design aplikace ma navazovat na:

- `http://127.0.0.1:4173/`
- `https://hdsrecorder.vaclavlepic.com/`

Lokální reference `http://127.0.0.1:4173/` ma title `WaWoD Studio` a pouziva tmavy, technicky, panelovy design s glassmorphism prvky. Verejna reference `hdsrecorder.vaclavlepic.com` zustava povinna vizualni reference pro rucni kontrolu pri implementaci.

## Charakter

Rozhrani ma pusobit jako seriozni pracovni aplikace pro hlasovy chat, dokumenty, OCR a pozdejsi RAG. Ne jako marketingova landing page.

Klicove vlastnosti:

- tmavy technicky vzhled;
- jemne prusvitne panely;
- teply zlaty/medeny akcent;
- konakovo-medeny gradient do modre a z modre do cerne;
- kompaktni pracovni layout;
- jasne stavy nahravani, zpracovani a odpovedi;
- prvky vhodne pro opakovane pouzivani, ne dekorativni hero sekce.

## Barvy

Zaklad vychazi z lokalni reference a CSS tokenu z HDS Recorderu. Pozadi neni obecne tmave ani ciste modre; hlavni dojem ma byt konakovo-medeny gradient prechazejici do modre a z modre do cerne.

- text hlavni: `#f8f6f2`
- text tlumeny: `rgba(248, 246, 242, .72)`
- akcent: `#c59d5f`
- silny akcent: `#8c543a`
- tmava modra: `#00002d`
- hneda/medena plocha: `#7d4b32`
- cerna: `#000000`
- panel border: `rgba(255, 255, 255, .16)`
- panel surface: `rgba(255, 255, 255, .06)`

Pozadi muze pouzit kombinaci radialnich a linear gradientu, ale musi zustat klidne a citelne. Dominantni smer: konak/med -> tmava modra -> cerna. Nepouzivat vyrazne fialove/purple gradienty, ciste modry dashboard ani svetly beige dashboard.

## Referencni CSS tokeny

Tyto tokeny pochazeji z HDS Recorderu a maji byt zaklad pro frontend theme:

```css
:root {
  color-scheme: dark;
  --foreground-rgb: 255, 255, 255;
  --background-start-rgb: 0, 0, 45;
  --background-end-rgb: 125, 75, 50;
  --main-font: "Source Sans Pro", sans-serif;
  --secondary-font: "The Nautigal", cursive;
  --body-font: "Cabin", sans-serif;
  --main-font-color-dark: #252525;
  --secondary-font-color: #c59d5f;
  --body-font-color: #ffffff;
  --surface-color: rgba(255, 255, 255, 0.07);
  --surface-border: rgba(255, 255, 255, 0.18);
  --text: #f8f6f2;
  --muted: rgba(255, 255, 255, 0.72);
  --primary: #c59d5f;
  --primary-strong: #8c543a;
  --secondary: rgba(255, 255, 255, 0.08);
  --panel: linear-gradient(180deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.04));
  --sentence-panel:
    linear-gradient(180deg, rgba(0, 0, 0, 0.28), rgba(0, 0, 0, 0.52)),
    linear-gradient(135deg, rgba(8, 12, 36, 0.94) 0%, rgba(16, 18, 28, 0.96) 58%, rgba(58, 35, 24, 0.92) 100%);
  --panel-border: rgba(255, 255, 255, 0.16);
  --shadow: 0 24px 80px rgba(0, 0, 0, 0.4);
  --bg-accent:
    radial-gradient(circle at top left, rgba(197, 157, 95, 0.18), transparent 24%),
    radial-gradient(circle at right center, rgba(35, 64, 140, 0.22), transparent 30%),
    linear-gradient(135deg, rgb(125, 75, 50) 0%, rgb(0, 0, 45) 48%, rgb(0, 0, 0) 100%);
  --canvas-bg:
    linear-gradient(180deg, rgba(197, 157, 95, 0.12), rgba(0, 0, 0, 0.18)),
    linear-gradient(120deg, rgba(8, 19, 64, 0.72), rgba(20, 20, 20, 0.9));
}
```

Pri implementaci se maji tokeny prenest do globalniho CSS/Tailwind theme a komponenty maji pouzivat tyto promenne misto vlastnich nahodnych barev.

## Typografie

Preferovane fonty podle reference:

- `Source Sans Pro`
- `Aptos`
- `Segoe UI Variable`
- `Trebuchet MS`
- fallback `sans-serif`

Text ma byt citelny a pracovni. Nadpisy nemaji byt zbytecne hero-scale uvnitr aplikacnich panelu.

## Tvary a komponenty

- Hlavni panely: glass efekt, border `rgba(255,255,255,.16)`, blur, tmave pozadi.
- Tlačítka: pill nebo zaoblene ikonove prvky, tmavy gradient, hover posun o 1px.
- Aktivni akce: zlaty/medeny gradient.
- Inputy: tmave, zaoblene, s jemnym borderem.
- Status prvky: pill/chip styl.
- Karty: pouzivat jen pro skutecne opakovane polozky, modaly a tool panely.

## Layout pro nasi aplikaci

MVP obrazovky:

- login/registrace;
- hlavni chat;
- hlasovy stavovy panel;
- seznam konverzaci;
- nastaveni modelu/Ollama/SpeechCloud;
- pozdeji dokumenty a OCR upload.

Layout ma byt spise aplikacni:

- levy panel pro konverzace/dokumenty;
- hlavni plocha pro chat;
- pravy nebo horni panel pro stav hlasu, model a system;
- status line pro SpeechCloud/Ollama stav;
- bez marketingoveho hero bloku.

## Hlasovy UI stav

SpeechCloud integrace musi mit jasne vizualni stavy:

- `idle`
- `listening`
- `recognizing`
- `thinking`
- `speaking`
- `error`

Stavy maji byt viditelne jako status pill nebo kompaktni panel. Nesmí prekryvat hlavni chat.

## Implementacni pravidla

- Vytvorit centralni design tokens v CSS/Tailwind konfiguraci.
- Neopisovat nahodne styly primo do jednotlivych komponent.
- Pred dokoncenim frontend faze vizualne porovnat s obema referencemi.
- Udrzet responsivitu pro desktop i mobil.
- Text v tlacitkach a panelech nesmi pretekat.
- Nepouzivat `localStorage` pro auth tokeny; cookie auth nema mit viditelny dopad na UI krom prihlaseneho stavu.

## Testy a kontrola

Pri frontend zmenach kontrolovat:

- screenshot login obrazovky;
- screenshot hlavniho chat UI;
- screenshot hlasoveho stavu;
- mobilni sirku;
- kontrast textu na tmavem pozadi;
- vizualni podobnost s referencemi.

## Rozhodnuti

Designovy jazyk projektu ma byt kompatibilni s `WaWoD Studio` lokalni referenci a verejnou referenci `hdsrecorder.vaclavlepic.com`. Vsechny nove frontend komponenty maji pouzivat tento jazyk od zacatku.
