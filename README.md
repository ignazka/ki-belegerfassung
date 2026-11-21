# Beleg-Klassifizierung – PoC

Einfache Streamlit-Oberfläche: Mitarbeiter laden Belege hoch, ein Vision-LLM ordnet sie ein und
extrahiert die Daten, der Mitarbeiter gibt Feedback, was richtig erkannt wurde.

**Langfristiges Ziel:** ein Agentic RAG, das die Buchhaltung einer Firma unterstützt:
1. Belege verschiedener Arten klassifizieren (aktuell: Bewirtung)
2. Entwürfe in **sevDesk** anlegen
3. Firmenwissen (Kontierungsregeln, frühere Buchungen pro Lieferant) per RAG einbeziehen

Der aktuelle Stand ist bewusst nur **Schritt 1 als Testumgebung**: Wie gut erkennt das Modell Belege?

## Starten

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# .env anlegen mit: OPENROUTER_API_KEY=sk-or-...
streamlit run App.py
pip install -r requirements-dev.txt
python -m pytest       # alle Tests, ohne API/Drive/Secrets (ca. 10 s)
```

## Aufbau

**Wie gelesen, gerechnet und geprüft wird: siehe [PRUEFABLAUF.md](PRUEFABLAUF.md).**

**Technischer Ablauf für Entwickler (wie die KI „lernt“, wie gespeichert wird):
[docs/TECHNIK.md](docs/TECHNIK.md).** Weiterentwicklung zur Plattform: [docs/KONZEPT_PLATTFORM.md](docs/KONZEPT_PLATTFORM.md).

| Datei | Zweck |
|---|---|
| `App.py` | Nur Oberfläche. Tabs „Belege hochladen“ (Upload → Ergebnis, jeder Beleg wird abgelegt), „Belege“ (alle Belege durchsehen, prüfen, korrigieren; Filter u. a. „Nachfragen offen“), „Kategorien“ (anlegen/bearbeiten/löschen, Probelauf) und „Auswertung“ (Kennzahlen, „Aus Korrekturen lernen“) |
| `prompts.py` | System-Prompt + `PROMPT_VERSION` |
| `beleg_schema.py` | `KATEGORIEN`, `FEEDBACK_FELDER`, Pydantic-Modell `BelegAnalyse` (+ `Steuerzeile`), Parsing/Vergleich. **Summen (MwSt., Netto) und Trinkgeld rechnet der Code** in `_ableiten` |
| `pipeline.py` | Ablauf einer Analyse: doppelt lesen (Original + Kontrast-Variante, parallel), vergleichen, bei Zweifel Schiedsrichter-Modell in höherer Auflösung |
| `kategorien.py` | Kategorien aus der App: Versionen (nur anhängen), Standard + eigene, Prompt-Abschnitt, Fingerabdruck für die Prompt-Version, KI-Assistent (Freitext → Regeln + Rückfragen) |
| `skr04.py` | SKR04-Kontenvorlage (Papierkram-Liste) und Prüfung der Kontonummer. Jede Kategorie hat ein Standardkonto (`skr04_konto`, `skr04_bezeichnung`) für die spätere Übergabe an sevDesk und optional `konto_ausnahmen` („wenn … → Konto“). Nur Ausnahmen gehen in den Prompt; die KI wählt dann je Beleg (`konto`, `konto_unsicher`), `BelegAnalyse` lässt nur Konten der Kategorie zu. Konto ist auch Prüffeld |
| `testlauf.py` | Testlauf einer Kategorie: Beispielbelege mit gespeichertem vs. geändertem Kategorie-Wissen analysieren und vergleichen, inkl. gewähltem Konto je Variante (auch ungespeicherte Konto-Ausnahmen) |
| `kalender.py` | Abgleich Bewirtung/Übernachtung ↔ Termin im Firmen-Google-Kalender (Regeln, Teilnehmer-Vorschlag); Zugriff in `storage.kalender_abgleichen` |
| `einfuehrung.py` + `assets/einfuehrung.js` | Interaktive Einführung (startet beim ersten Öffnen in einem Browser automatisch, danach über „Einführung starten“ in der Seitenleiste): Tour mit driver.js (per CDN), hebt Bereiche hervor, erklärt sie in Popups und wechselt dabei selbst die Tabs. Schritte und Texte in `assets/einfuehrung.js` |
| `browser_skripte.py` + `assets/belegansicht.js` | Browser-Skripte einbetten; Belegansicht neben dem Formular: Seite groß, bei mehreren Seiten ‹ Seite x von n › und Mini-Vorschauen, Blättern direkt im Browser |
| `lesequalitaet.py` | Lesequalität: vergleicht bei geprüften Belegen jede gespeicherte Lesung (Original, Kontrast, Schiedsrichter) mit dem richtigen Wert – je Feld, Feldart und Belegtyp; Anzeige im Tab „Auswertung“ |
| `marke.py` + `assets/thema.js` | Titel „PraktikantAI“ + „powered by RE-ALIS“, Fußzeile der Login-Seite; Umschalter Hell/Dunkel (Mond/Sonne) oben rechts neben dem Menü |
| `checks.py` | Rechenprüfungen (Steuerzeilen = Gesamtbetrag, MwSt. passt zum Satz, EC ≥ Rechnung, Datum) und `nachfragen_gruende` (Regeln, wann ein Mensch draufschauen muss) |
| `extraction.py` | `MODEL`, Bildaufbereitung (PDF → Bilder, EXIF-Drehung, max. 2000 px bzw. 1600 px ab 6 Seiten, JPEG), mehrere Dateien = ein Beleg (`dateien_zu_bildern`, max. `MAX_SEITEN` = 20), API-Call, JSON-Extraktion |
| `auth.py` | Google-Login über `st.login`, nur E-Mails aus `[zugang].erlaubte_emails`. Fail closed: ohne `[auth]` oder mit leerer Liste ist die App gesperrt |
| `storage.py` | Ein gemeinsamer Ordner für alle Benutzer. Mit `[google_drive]`: Drive-Ordner `belege/`, `analysen/` (jede Analyse) + `feedback/` (eine JSON-Datei pro Prüfung). Dazu `nachfragen/` und `entscheidungen/` (ältere Versionen, nur gelesen), `kategorien/` (alles nur anhängen) und lesbare Kategorie-Docs in `Anlage KI Assistent/<Kategorie>/`. Sonst lokal `data/` (bzw. `BELEG_DATENORDNER`): `feedback.jsonl`, `nachfragen.jsonl`, `belege/`, Rechte 0700/0600 |
| `drive_token_holen.py` | Einmalig lokal: Refresh-Token für den Drive-Zugriff erzeugen und Ordnerzugriff prüfen |
| `assets/` | RE-ALIS-Logo und -Symbol (SVG, von re-alis.com, Farben direkt eingetragen). Design in `.streamlit/config.toml`: helles und dunkles Theme (`[theme.light]`/`[theme.dark]`), Marken-Orange (abgedunkelt auf `#C25100` für lesbare Buttons), Source Sans 3 |
| `tests/` | `pytest`-Tests: `test_logik.py` (Parsing, Vergleich, JSON-Extraktion, Pydantic, Ableitungen, Prüfungen inkl. echter Fälle Domhof/Aral), `test_pipeline.py`, `test_storage_lokal.py`, `test_kategorien_lernen.py`, `test_einfuehrung.py`, `test_ui_*.py` (Oberfläche mit `AppTest` und vorgetäuschter Ablage aus `attrappe.py`); `browser/` manuelle Browser-Tests der Einführung. Läuft auch per GitHub Actions bei jedem Push |

**Ablauf:** Upload → `dateien_zu_bildern` → `beleg_lesen` (doppelt lesen, ggf. Schiedsrichter; Modell liest nur
ab) → `BelegAnalyse` (Code rechnet Summen/Trinkgeld) → `pruefen` + `nachfragen_gruende` → sofort
`analyse_speichern` (jeder Beleg) → Tab „Belege“: Mensch prüft/korrigiert → `feedback_speichern`.

## Fachliche Vorgaben der Buchhaltung (Bewirtung)

- Quittung muss **lesbar** sein, **Steuersatz** (7 % und/oder 19 %) ausweisen, **Datum** erkennbar.
  **Bei Abweichungen immer einen Menschen fragen** → Tab/Ordner „Nachfragen“.
- Wichtig: Belegnummer, Restaurantname, Belegdatum, Netto und Brutto.
- Restaurant- + EC-Beleg: Differenz = Trinkgeld. Abgleich von Tag, Datum, Uhrzeit, Adresse, Name
  (`ec_passt_zur_rechnung`).
- Auf den Bewirtungsbeleg (Google-Doc „Bewirtungsbeleg“): Belegnummer, Restaurant, Bewirtungskosten brutto,
  MwSt., Trinkgeld, Tag der Bewirtung. Zusätzlich manuell: Firmenadresse + Bewirtender (meist Simon Jäger
  oder Asllan Ruko), bewirtete Personen (künftig aus dem Kalender), Anlass, Anlagen = „Quittungsbeleg
  <Restaurant>, <Ort>“, Ort und Datum der Erstellung.
- **Auslandsbelege:** abweichende Handhabe → immer Nachfrage (`ausland`).
- Bewirtung strikt von **Tanken** und **Übernachtung** trennen (eigene Kategorien).

## Login (Google) und Ablage (Google Drive)

Secrets-Vorlage: `.streamlit/secrets.toml.example` (lokal nach `.streamlit/secrets.toml`, in Streamlit
Cloud unter Settings → Secrets). Lokal ohne Login entwickeln: `LOGIN_DEAKTIVIERT=1` in `.env`
(wirkt nur über die Umgebung, nie über Secrets).

- OAuth-Client (Typ „Webanwendung“) in der Google Cloud Console, Weiterleitungs-URIs
  `https://<app>.streamlit.app/oauth2callback` und `http://localhost:8501/oauth2callback`.
- Zusätzlich Weiterleitungs-URI `http://localhost:8080/` für `drive_token_holen.py`.
- **Ablage auf Streamlit Cloud = Google Drive**, weil das Dateisystem dort nicht dauerhaft ist (`data/` geht bei
  Neustart, Redeploy oder Schlafmodus verloren). Die App schreibt mit einem Refresh-Token des Ordner-Besitzers
  (kein Service-Account: der hat bei privaten Gmail-Konten kein Speicherkontingent). Zustimmungsbildschirm
  auf „In Produktion“, sonst läuft der Token nach 7 Tagen ab. Halb konfiguriertes oder nicht erreichbares
  Drive sperrt die App, statt still lokal zu speichern.

## Wichtige Entscheidungen

- **Modell:** `qwen/qwen3-vl-30b-a3b-instruct` über OpenRouter (offene Gewichte, später lokal
  betreibbar), liest jeden Beleg doppelt. **Schiedsrichter** bei Zweifel: `qwen3-vl-235b-a22b-instruct`
  (Cloud). Ziel-Hardware lokal: **RTX 3090 (24 GB)** – dort passt nur das 30B-Modell (4-Bit ca. 18–19 GB),
  also `SCHIEDSRICHTER_MODELL` auf das 30B-Modell setzen (liest dann nur in höherer Auflösung nach).
- **Datenschutz:** `extra_body={"provider": {"data_collection": "deny"}}`, damit nur Anbieter ohne
  Datenspeicherung/Training genutzt werden. `data/` enthält echte Belege → nie committen.
- **Session-State:** Streamlit führt das Skript bei jeder Eingabe neu aus. Das Ergebnis muss deshalb in
  `st.session_state` liegen, sonst verschwindet es beim ersten Klick im Feedback. Es wird verworfen,
  wenn sich der Datei-Hash ändert.
- **Feste Kategorien** (`KATEGORIEN` in `beleg_schema.py`). Unbekannte Werte vom Modell → `sonstiger_beleg`.
- **Das Modell rechnet nicht.** Es liest Gesamtbetrag, EC-Betrag und die MwSt.-Aufstellung pro Satz
  (`steuerzeilen`) ab; MwSt.-/Netto-Summe und Trinkgeld (= EC − Rechnung) rechnet `BelegAnalyse._ableiten`.
  Grund: Das Modell hat sich verrechnet (Domhof: MwSt. 11,40 statt 11,35, Brutto 144,80 statt 133,40).
  Die Steuerzeilen erlauben eine Gegenprobe gegen den Gesamtbetrag (`checks.pruefen`).
- **Keine echten Zahlen im Prompt-Beispiel**, nur Platzhalter – sonst kopiert das Modell sie
  (erfundene Steuerzeile mit 5,59 € aus dem Beispiel).
- **Kein „Vertrauen“-Wert:** Vom LLM selbst geschätzte Werte sind nicht kalibriert. Stattdessen
  `kategorie_unsicher` + Begründung (ja/nein) und harte Prüfungen im Code.
- **Nachfragen** werden direkt nach der Analyse abgelegt (unabhängig vom Feedback), einmal pro Datei-Hash.
- **JSON-Parsing:** erst `response_format=json_object` (mit Fallback ohne), dann direkt parsen,
  Codeblock oder erstes `{…}`. Danach tolerante Pydantic-Validierung.
- **Vergleich im Feedback** (`werte_gleich`): Beträge auf 0,005 genau, `0,00` = leer;
  Text ohne Groß-/Kleinschreibung und doppelte Leerzeichen; Datum in mehreren Formaten.
  Bei Steuersätzen ist das Komma ein **Trennzeichen** (`7,19` = 7 % und 19 %).
- **Mehrere Dateien / Seiten = ein Beleg** (Rechnung + EC-Beleg, mehrseitige Hotelrechnung). Hash bei einer
  Datei = Datei-Hash (wie bisher), bei mehreren = Hash über die Einzel-Hashes. Mehr als 20 Seiten → Nachfrage.
- **Oberfläche deutsch formatiert** (`anzeige`, `datum_de`, `zeitpunkt_de`): 04.09.2026, 17.11.2026 16:20,
  1.234,50 €. Gespeichert wird weiterhin ISO bzw. Zahl. Eingaben werden mit `parse_*` zurückgelesen.
- **Barrierearm:** Prüfergebnisse als Wort („ja“/„nein“), nicht nur Farbe/Symbol; `st.table` statt
  `st.dataframe` für die Ergebnis-Tabellen (HTML, Screenreader); Bildunterschriften als Alternativtext;
  Formularfelder zeilenweise (Tab-Reihenfolge); keine gelben Texte (Kontrast); Akzentfarbe in
  `.streamlit/config.toml`.
- `import pymupdf` statt `import fitz` (veraltet). In Streamlit `width="stretch"` statt
  `use_container_width` (veraltet).

## Konventionen

- Code, Bezeichner und Oberfläche auf **Deutsch**.
- **Bei jeder inhaltlichen Prompt-Änderung `PROMPT_VERSION` erhöhen**, damit die Auswertung
  Versionen vergleichen kann.
- Neue Feedback-Felder: in `FEEDBACK_FELDER` **und** in `BelegAnalyse` und im Prompt ergänzen.
- Feedback-Format nur erweitern, nicht umbenennen. Alte JSONL-Zeilen müssen lesbar bleiben.

## Stand und nächste Schritte

Aktueller Stand, Arbeitsweise und Roadmap stehen in [CLAUDE.md](CLAUDE.md).
