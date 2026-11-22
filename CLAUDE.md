# CLAUDE.md – BelegAssistent (Repo ki-belegerfassung; früher PraktikantAI / beleg-poc)

Hinweise für Claude in künftigen Sitzungen. Technischer Ablauf für Entwickler: [docs/TECHNIK.md](docs/TECHNIK.md);
Plattform-Konzept (TS/React/Postgres, mehrere Firmen): [docs/KONZEPT_PLATTFORM.md](docs/KONZEPT_PLATTFORM.md). Bei Änderungen
an Ablauf oder Datenablage `docs/TECHNIK.md` mitpflegen (dort auch Dateien, Einrichtung, Entscheidungen).
[README.md](README.md) ist die kurze öffentliche Projektseite – nur bei größeren Änderungen anpassen. Der
komplette Prüf- und Rechenablauf in [PRUEFABLAUF.md](PRUEFABLAUF.md) – beide bei Änderungen mitpflegen.

## Wozu die App dient

**BelegAssistent** (powered by RE-ALIS; früher „PraktikantAI“ – interne Bezeichner wie `praktikant-tour` heißen weiter so) ist ein interner **Proof of Concept für Stufe 1 eines Agentic RAG**,
das die Buchhaltung der RE-ALIS GmbH unterstützen soll. Langfristig ein „KI-Kollege“, der Belege
zuverlässig einordnet, daraus Entwürfe in **sevDesk** anlegt und später weitere sevDesk-Aufgaben übernimmt.

Stufe 1 = **Testumgebung**: Wie zuverlässig erkennt ein Vision-LLM Belege (Bewirtung, Tanken, Übernachtung,
eigene Kategorien …), liest die Daten ab und erkennt, wann ein Mensch nachschauen muss? Jede menschliche
Prüfung wird gesammelt – als Messgrundlage und als Lernmaterial, um die Anweisungen an die KI zu verbessern.

- **Nutzer:** nur der Inhaber und der Entwickler (Philipp); fachliche Ansprechpartnerin Buchhaltung: Annika.
  Texte so schreiben, dass auch Nicht-Techniker sie verstehen.
- **Lebensdauer:** Mit sevDesk-Anbindung und dem „richtigen“ Agenten wird diese App ersetzt oder stark
  umgebaut. Pragmatisch bauen, nicht auf Skalierung/Langlebigkeit über-engineeren, keine
  Compliance-Features (Löschfristen o. ä.) vorschlagen, solange der Nutzerkreis so klein bleibt.
- **Betrieb:** Streamlit Community Cloud, deployt automatisch bei Push auf `main`
  (Repo `ignazka/ki-belegerfassung`). Login über Google (`st.login`), Ablage in einem Firmen-Google-Drive-Ordner.

## Was die App heute kann (Stand 2026-11-18)

Tabs (in `App.py`):

1. **Belege hochladen** – ein Beleg (auch mehrere Dateien/Seiten = ein Beleg) oder Stapel bis 30 Belege.
   Während der Analyse zeigt der Knopf einen Spinner und die anderen Tabs sind gesperrt (ein Klick würde
   das Skript neu starten und die Analyse abbrechen). **Jeder** analysierte Beleg wird abgelegt
   (`analysen/` + Original in `belege/`). Geprüft wird hier nicht mehr – nur Ergebnis + Hinweis auf „Belege“.
2. **Belege** – alle Belege an einer Stelle: Filter *Nachfragen offen · Ungeprüft ·
   Korrigiert · Mit Kommentar · Alle* (offene Arbeit als farbige Zahl-Plakette, `:orange-badge[]`/`:blue-badge[]` + CSS), Blätterleiste, links das Original (Klick = große Ansicht), rechts
   Prüfformular („Stimmt die Belegart …? Ja/Nein“ ohne Vorauswahl, Felder, Begründung) bzw. bei geprüften
   Belegen die Tabelle „KI hat gelesen / Richtig ist“ mit „Korrigieren“/„Abbrechen“.
3. **Kategorien** – Belegarten anlegen/bearbeiten/löschen (Versionen, Entwurf/aktiv), KI-Assistent
   (Freitext → Regeln + Rückfragen), Probelauf „Hilft meine Änderung?“ mit Beispielbelegen aus Drive.
   Aktive Kategorien fließen in den System-Prompt; Prompt-Version enthält einen Wissens-Hash.
   Jede Kategorie hat ein **SKR04-Konto** für sevDesk (`skr04.py`: Vorlage aus der Papierkram-Kontenliste,
   frei änderbar/eigene Nummer) plus optionale **Konto-Ausnahmen** („wenn … → Konto“, Tabelle). Standardkonto
   allein steht nicht im Prompt; nur Ausnahmen – dann wählt die KI je Beleg, `BelegAnalyse._konto_festlegen`
   lässt nur Konten der Kategorie zu (Registrierung `konten_registrieren`), unsicher → Nachfrage. Das Konto
   ist Prüffeld (`FEEDBACK_FELDER`, Typ `konto`).
4. **Auswertung** – nur Kennzahlen: Belege/geprüft, Nachfragen, *unnötige* Nachfragen, Trefferquote
   (Belegart, Felder, pro Feld/Belegart, Verwechslungen) und **„Aus Korrekturen lernen“**: großes Modell
   ordnet Korrekturen Ursachen zu und schlägt Ergänzungen für Kategorien vor; Übernahme nur als
   ungespeicherte Änderung im Kategorien-Tab (Mensch prüft, testet, speichert).
   Dazu **„Lesequalität“** (`lesequalitaet.py`): welche Lesung je Feld richtig lag – Grundlage für die
   Entscheidung über ein zusätzliches OCR-Modell (Plan: Stufe 2, Vergleichsskript mit lokalem OCR).

**Einführung:** startet beim allerersten Öffnen in einem Browser automatisch (Merker
`praktikantai_tour_gesehen` im localStorage) und jederzeit über „Einführung starten“ in der Seitenleiste. Tour (driver.js 1.3.1 per CDN,
`einfuehrung.py` + `assets/einfuehrung.js`). Neue oder umbenannte Bereiche dort nachziehen. Eigenheiten:
Tabs werden über ihre Position gewählt und per Zeiger-Ereignissen geöffnet; jeder Schritt wird mit
`highlight()` einzeln gezeigt, weil Ziele in unsichtbaren Tabs erst nach dem Wechsel existieren; im
Skript jedes `<` vor Buchstaben als `<` maskieren (sonst entfernt Streamlits HTML-Filter das `<script>`).

**Belegansicht** (`_beleg_vorschau`): die aktuelle Seite groß neben dem Formular (Belegspalte so hoch wie
die rechte Spalte), bei mehreren Seiten darunter „‹ Seite x von n ›“ (`.belegnav`, per `st.html`) und
Mini-Vorschauen (`belegdaumen_`). Alle Seiten werden in `belegbild_` gezeichnet; `assets/belegansicht.js`
blendet nur die gewählte ein – Blättern ohne Neuberechnung durch Streamlit. Kein Vollbild-Klick mehr. Eingebettet werden Browser-Skripte
über `browser_skripte.py` (maskiert `<` für Streamlits HTML-Filter). Kurze Rückmeldung bei Wartezeiten: was
im Browser geht, im Browser lösen statt einen Spinner vor einen Server-Durchlauf zu setzen.

**Rückmeldung bei Wartezeiten:** Knöpfe für längere Vorgänge (Analyse, Verbesserungsvorschläge, KI-Assistent,
Probelauf) laufen über `_lauf_knopf(label, name, …)` in `App.py`: Nach dem Klick ist derselbe Knopf
ausgegraut mit Spinner, die anderen Tabs sind gesperrt (CSS auf `st-key-laufknopf_…`), danach `st.rerun()`
(im Dialog `scope="fragment"`); Fehler über `st.session_state["meldung_<name>"]` + `_lauf_meldung`. Neue
lange Vorgänge genauso bauen. Zusätzlich zeigt ein orangefarbener Ladebalken oben jeden Server-Durchlauf
(CSS auf Streamlits `stStatusWidgetRunningIcon`).

Weitere Bausteine: doppeltes Lesen + Schiedsrichter-Modell (`pipeline.py`), Rechnen nur im Code mit
Decimal/Cent (`beleg_schema.py`), Rechenprüfungen und Nachfrage-Regeln (`checks.py`), Abgleich mit dem
Firmen-Google-Kalender für Bewirtung/Übernachtung (`kalender.py`, noch nicht eingerichtet, s. u.),
RE-ALIS-Design (`marke.py`, `.streamlit/config.toml`, `assets/`).

**Helles/dunkles Design:** `[theme.light]`/`[theme.dark]` in `config.toml` (ohne Wahl folgt Streamlit dem
Betriebssystem). Knopf `thema_wechsel` (nur Symbol Mond/Sonne, `marke.thema_knopf`) fest oben rechts; `thema.js` setzt
ihn laufend links neben Ladeanzeige bzw. Menü (mittig zum Menü; auf Touch-Geräten rendert Streamlit Knöpfe mit
Tooltip doppelt, einer unsichtbar); Tour-Popups haben eine dunkle Variante (`einfuehrung.py`); `assets/thema.js` fängt den Klick ab, schreibt
Streamlits eigenen Merker `stActiveTheme-<pfad>-v2` ("Light"/"Dark") und lädt die Seite neu (nicht
gespeicherte Eingaben gehen verloren). Das Skript setzt `<html data-thema="hell|dunkel">` nach der
Hintergrundfarbe – eigene Farben im CSS deshalb als Variablen (`--akzent`, `--leise` … in `App.py`) mit
Überschreibung unter `html[data-thema="dunkel"]`, nie fest für nur ein Design. Logo dunkel: `marke.py`.

## Datenablage (wichtig für jede Änderung)

Drive-Ordner aus `[google_drive].ordner_id`, sonst lokal `data/`. **Alles nur anhängen, nie überschreiben**;
pro Datei-Hash gilt der **jüngste** Eintrag.

| Unterordner | Inhalt |
|---|---|
| `belege/` | Originaldateien |
| `analysen/` | jede Analyse (Ergebnis, Lesungen, Nachfragegründe `gruende`) – seit 2026-11-18 |
| `nachfragen/` | ältere Nachfragen (vor `analysen/`), nur noch gelesen |
| `feedback/` | jede menschliche Prüfung: `kategorie {modell, korrekt, richtig}`, `felder{key: {modell, korrekt, richtig}}`, `kommentar`, `quelle` (`nachfrage`/`pruefung`/fehlt = altes Feedback), ggf. `korrektur_von`, `kommentar_vorher` |
| `entscheidungen/` | Entscheidungen der ersten Nachfragen-Version, nur noch gelesen |
| `kategorien/` | Kategorie-Versionen; lesbare Kopien als Google-Doc in `Anlage KI Assistent/<Kategorie>/` |

`App._alle_belege()` führt das pro Hash zusammen. Formate nur **erweitern**, nie umbenennen – alte
Einträge müssen lesbar bleiben.

## Konventionen

- Code, Bezeichner, Oberfläche und Antworten an den Nutzer auf **Deutsch**. Anzeige deutsch formatiert
  (17.11.2026 16:20, 1.234,50 €), gespeichert ISO/Zahl.
- **Das Modell liest nur ab, der Code rechnet.** Keine echten Zahlen in Prompt-Beispielen.
- Inhaltliche Prompt-Änderung → `PROMPT_VERSION` in `prompts.py` erhöhen.
- Neues Prüffeld → `FEEDBACK_FELDER`, `BelegAnalyse` und Prompt ergänzen.
- Modelle über OpenRouter: `MODEL` = `qwen/qwen3-vl-30b-a3b-instruct` (liest doppelt),
  Schiedsrichter/Assistent `MODEL_GROSS` = `qwen/qwen3-vl-235b-a22b-instruct`. Ziel: später lokal auf
  einer RTX 3090 (24 GB) → nur das 30B-Modell passt.
- Streamlit 1.67 – Eigenheiten, die schon Zeit gekostet haben:
  - CSS-Haken über `key=` → Klasse `.st-key-<key>`; Tabs sind react-aria (`[role=tab]`, `[data-selected]`).
  - Widget-Werte nach dem Zeichnen nicht mehr setzbar → „pending“-Schlüssel vor dem Widget anwenden
    (z. B. `kategorie_wahl_naechste`, `beleg_wahl_naechste`, `kategorie_vorschlaege_naechste`).
  - In `st.form` gibt es kein bedingtes Ein-/Ausblenden; Expander lassen sich per Code nicht schließen
    (deshalb Auf-/Zu-Buttons über `session_state`).
  - `width="stretch"` statt `use_container_width`; `import pymupdf` statt `fitz`.
- Barrierearm: Status als Wort, nicht nur Farbe; ausreichender Kontrast; Info-Texte als Caption oben.

## Arbeitsweise mit dem Nutzer

- **Committen/Pushen nur auf Aufforderung.** Sagt der Nutzer „committen“, will er meist auch pushen – kurz
  mit nachfragen bzw. beides tun, wenn er „committen und pushen“ sagt. Commit-Messages auf Deutsch.
- **Nie committen:** `.streamlit/secrets.toml`, `.env`, `data/`. Tokens nie ausgeben oder in den Chat
  kopieren lassen – `drive_token_holen.py` schreibt sie direkt in die Secrets.
- **UI-Änderungen sichtbar prüfen:** App lokal nur auf `127.0.0.1` (Port 8503) mit `LOGIN_DEAKTIVIERT=1`
  starten (wirkt nur über die Umgebung), per Headless-Chrome (CDP) Screenshot machen, Server danach stoppen.
- **Einführung (Tour) immer mitdenken:** Kommt eine Funktion oder ein Bereich dazu, wird etwas umbenannt,
  verschoben oder entfernt (Tabs, Knöpfe, `key=`-Namen, Texte), die Schritte in `assets/einfuehrung.js`
  anpassen bzw. ergänzen und die Tour einmal durchklicken (alle Schritte treffen das richtige Element,
  keine JS-Fehler). Bei größeren neuen Funktionen dem Nutzer einen passenden Tour-Schritt vorschlagen.
  `tests/test_einfuehrung.py` schlägt an, wenn ein Tour-Ziel (`.st-key-…`, Knopftext) nicht mehr existiert.
  Durchklicken im Browser: `tests/browser/tour_durchklicken.mjs` (Anleitung im Dateikopf).
- **Tests:** `python -m pytest` (ca. 10 s, ohne API, ohne Drive, ohne Secrets; `pip install -r
  requirements-dev.txt`). Laufen auch per GitHub Actions bei jedem Push (`.github/workflows/tests.yml`) –
  Streamlit Cloud deployt trotzdem sofort, ein rotes Kreuz heißt also „schnell beheben“.
  - `tests/test_logik.py` Rechnen/Prüfen/Parsen, `test_pipeline.py` doppelt lesen + Schiedsrichter,
    `test_storage_lokal.py` lokale Ablage, `test_kategorien_lernen.py`, `test_einfuehrung.py`,
    `test_ui_*.py` Oberfläche mit `AppTest`.
  - UI-Tests über `tests/attrappe.py`: `A.app(analysen=[…], feedback=[…], ki={…})` startet die App mit
    vorgetäuschter Ablage/KI; `storage._drive` ist dort gesperrt. Neue `storage`-Funktionen, die die App
    nutzt, **dort ebenfalls ersetzen**.
  - Neue Funktionen bekommen Tests (mindestens ein UI-Test für neue Abläufe). **Nie in die echte Ablage
    schreiben**; echte Drive-Daten lesen ist in Ordnung. Echte Modellaufrufe sparsam.
- Der Nutzer entscheidet Design-Fragen gern selbst und ändert sie auch wieder – bei echten Alternativen
  kurz fragen, sonst umsetzen und per Screenshot zeigen.

## Offene Punkte und Pläne

Kurzfristig:
- **Kalenderabgleich einrichten** (Aufgabe des Nutzers): `[kalender].kalender_id` in den Secrets,
  Calendar API aktivieren, `python drive_token_holen.py --kalender` mit einem Konto, das den
  Firmenkalender sehen darf (z. B. Annika).
- **Texterkennung (OCR), Stufe 2:** Wenn „Lesequalität“ mit genug Belegen (einige Dutzend) eine klare
  Schwachstelle zeigt (bisher: Textfelder/Adresse in den ersten Lesungen), Vergleichsskript außerhalb der App:
  geprüfte Belege + Beispielordner mit 1–2 lokalen OCR-Kandidaten (z. B. PaddleOCR, Surya, docTR) lesen und
  gegen die richtigen Werte messen; bei Erfolg OCR-Text als zusätzliche Gegenprobe in `pipeline.py`.
- **Verbesserungsrunden:** Prüfungen sammeln (ab ca. 20–30 Korrekturen), „Aus Korrekturen lernen“
  ausführen, Vorschläge im Kategorien-Tab testen und übernehmen; Wirkung über die Prompt-Version in der
  Auswertung vergleichen.
- Optional angeboten, nicht umgesetzt: „Beleg entfernen“ für versehentliche Uploads; Schiedsrichter bei
  rein fachlichen Nachfragegründen überspringen.

Danach (Roadmap):
1. Bewirtungsbeleg (Google-Doc „Bewirtungsbeleg“) aus den abgelesenen Daten + Kalender (Teilnehmer, Anlass)
   vorausfüllen.
2. Datenmodell an sevDesk-Voucher ausrichten → **Entwürfe in sevDesk** anlegen; später weitere
   sevDesk-Aufgaben.
3. RAG über Kontierungsregeln und frühere Buchungen; die gesammelten Prüfungen sind der Testdatensatz.
4. Modelle lokal betreiben (RTX 3090).
