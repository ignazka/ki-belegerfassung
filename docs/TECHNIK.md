# BelegAssistent – technischer Ablauf

Für Entwickler: wie der Code aufgebaut ist, wo was passiert und wie Daten gespeichert werden. **Was** fachlich
passiert (Regeln, Prüfungen, Nachfragegründe) steht in [PRUEFABLAUF.md](../PRUEFABLAUF.md), die Arbeitsweise im
Projekt in [CLAUDE.md](../CLAUDE.md).

---

## 1. Überblick

| | |
|---|---|
| Sprache / Oberfläche | Python 3.11, Streamlit 1.67 (eine Seite, vier Tabs) |
| KI | OpenRouter (OpenAI-kompatible API). Lesen: `qwen/qwen3-vl-30b-a3b-instruct`; Schiedsrichter, Kategorie-Assistent, Lernvorschläge: `qwen/qwen3-vl-235b-a22b-instruct` |
| Ablage | Google-Drive-Ordner der Firma (lokal ersatzweise `data/`) – JSON-Dateien, nur anhängen |
| Login | Google über `st.login`, Freigabeliste in den Secrets |
| Betrieb | Streamlit Community Cloud, Deploy bei jedem Push auf `main`; Tests per GitHub Actions |

**Grundsatz:** Das Modell **liest nur ab**, der **Code rechnet und prüft**. Das Modell wird nie nachtrainiert –
„Lernen“ heißt: Der Prompt wird aus gepflegtem Kategorie-Wissen zusammengesetzt und anhand von Korrekturen
verbessert.

## 2. Dateien

| Datei | Aufgabe |
|---|---|
| `App.py` | Gesamte Oberfläche. Wird **bei jeder Eingabe komplett neu ausgeführt** (Zustand in `st.session_state`) |
| `pipeline.py` | Eine Analyse: doppelt lesen, vergleichen, ggf. Schiedsrichter |
| `extraction.py` | Bilder aufbereiten, Modell-Aufruf, JSON aus der Antwort holen |
| `beleg_schema.py` | Datenmodell `BelegAnalyse` (Pydantic), Felder, Rechnen mit `Decimal`, deutsche Formate, Vergleich |
| `checks.py` | Rechenprüfungen, Nachfragegründe, Abgleich bekannter Aussteller |
| `prompts.py` | System-Prompt-Vorlage, `PROMPT_VERSION` |
| `kategorien.py` | Kategorie-Versionen → aktueller Stand → Prompt-Abschnitt; KI-Assistent; Lern-Prompt |
| `merkmale.py` | Bekannte Aussteller (von Hand + aus Prüfungen), toleranter Abgleich |
| `testlauf.py` | Probelauf einer Kategorie-Änderung (vorher/nachher) |
| `lernen.py` | „Aus Korrekturen lernen“ ohne Oberfläche: Vorsortieren, veraltete Fälle, Wirkung, Testbelege |
| `lesequalitaet.py` | Welche Lesung lag richtig? Wann hilft der Schiedsrichter? |
| `kalender.py`, `kalender_verbindung.py` | Kalenderabgleich; „Kalender verbinden“ (OAuth, verschlüsselter Zugang) |
| `storage.py` | Ablage (Drive bzw. lokal), Kalenderzugriff |
| `skr04.py` | Kontenvorlage SKR04 |
| `auth.py`, `marke.py`, `datenschutz.py` | Login, Branding, Datenschutzseite |
| `einfuehrung.py`, `browser_skripte.py`, `assets/*.js` | Browser-Skripte: Tour, Blättern in der Belegansicht, hell/dunkel |
| `tests/` | pytest – Logik, Pipeline, Ablage, Oberfläche mit vorgetäuschter Ablage/KI (`tests/attrappe.py`) |

## 3. Ablauf einer Analyse

```text
Upload ─► Bilder ─► 2 Lesungen parallel ─► Vergleich + Prüfungen ─┬─► fertig (stimmig)
                                                                  ├─► fertig + Nachfrage (rein fachlicher Grund)
                                                                  └─► Schiedsrichter ─► erneut prüfen
        ─► Kalenderabgleich ─► ablegen (belege/ + analysen/) ─► Ergebnis anzeigen
```

1. **Upload** (`App.py`): Stapel (`MAX_STAPEL` = 30, `STAPEL_PARALLEL` = 3 Threads) oder ein Beleg aus mehreren
   Dateien. Die Auswahl hat bewusst keine Vorbelegung (`index=None`) – eine falsche Standardwahl hatte
   zweiseitige Belege zerlegt. Lange Vorgänge laufen über `_lauf_knopf` (siehe Abschnitt 6).
2. **Beleg-Kennung** `datei_sha256`: SHA-256 der Datei, bei mehreren Dateien über die Einzel-Hashes. Verbindet
   alle Einträge zu einem Beleg.
3. **Bilder** (`extraction.dateien_zu_bildern`): PDF mit 150 dpi (pymupdf), Fotos nach EXIF drehen, längste
   Kante 2000 px (ab 6 Seiten 1600 px), höchstens `MAX_SEITEN` = 20.
4. **Zwei Lesungen** (`pipeline.beleg_lesen`): Original + `kontrast_variante`, parallel, mit
   `SYSTEM_PROMPT_AKTUELL`. Aufruf (`extraction._modell_aufrufen`): `temperature=0.1`,
   `response_format=json_object`, `provider.data_collection=deny`. Antwort → `BelegAnalyse`; deren
   Validator `_ableiten` rechnet Summen, Trinkgeld und Konto.
5. **Belegart richtigstellen** (`checks.belegart_richtigstellen`): „Sonstiger Beleg“ + von Hand bekannter
   Aussteller → Belegart auf einer Kopie setzen, Vermerk `LeseErgebnis.richtiggestellt`. Die Lesungen bleiben
   unverändert gespeichert.
6. **Prüfen** (`checks.py`): `abweichungen` zwischen den Lesungen, `pruefen` (Rechenprüfungen),
   `nachfragen_gruende` (inkl. `_aussteller_abgleich`). `nur_fachliche_gruende` entscheidet, ob der
   Schiedsrichter etwas bringen kann.
7. **Schiedsrichter** (`MODEL_GROSS`, 2800 px): Sein Ergebnis gilt, danach erneut prüfen; nicht bestätigte
   Abweichungen → „Unsicher gelesen“. `schiedsrichter=False` (Schalter in der Seitenleiste): Lesung 1 gilt,
   Zweifel gehen direkt zur Nachfrage.
8. **Kalenderabgleich** (`storage.kalender_abgleichen`, Regeln in `kalender.py`).
9. **Ablegen** (`App._beleg_ablegen`): Original nach `belege/`, Eintrag nach `analysen/` – immer.

## 4. Prüfen durch den Menschen (Tab „Belege“)

- `App._alle_belege()` führt pro `datei_sha256` zusammen: jüngste Analyse (bzw. ältere Nachfrage), jüngste
  Prüfung, alte Entscheidungen. Einmal pro Durchlauf berechnet (`_LAUF_CACHE`).
- `App._belege_suchen` filtert nach Text, Belegart, Zeitraum – bei geprüften Belegen auf den korrigierten
  Werten (`_beleg_werte`).
- `App._beleg_formular`: Belegart-Frage (`_belegart_frage`, ohne Vorauswahl), Felder (`FEEDBACK_FELDER`),
  Begründung, optional „Aussteller merken“ (`_merken_moeglich` / `_aussteller_merken` → neue
  Kategorie-Version). Speichern = neuer Eintrag in `feedback/`; je Feld `modell`, `korrekt`, `richtig`.
  Verglichen wird immer mit der KI-Lesung.
- „Beleg entfernen“ (`_beleg_entfernen` → `storage.beleg_in_papierkorb`): siehe Abschnitt 5.2.

## 5. Kategorien, Lernen, Messen

### 5.1 Kategorie-Wissen → Prompt

- Jede Änderung ist eine **neue Version** in `kategorien/`. `kategorien.aktueller_stand` nimmt pro Schlüssel
  die **höchste Versionsnummer** (nicht die späteste Uhrzeit: alte Cloud-Einträge stehen in UTC, siehe 5.2).
- `kategorien.prompt_abschnitt` setzt **nur aktive** Kategorien in den Prompt (`prompts.system_prompt`);
  `kategorien_registrieren(labels(...))` legt fest, welche Belegarten die KI ausgeben darf. Entwürfe sind für
  die KI unsichtbar.
- **Prompt-Version** = `PROMPT_VERSION` + `+k` + `kategorien.wissens_hash` (z. B. `2026-11-27.1+k3af32b`).
  Jede Analyse und Prüfung speichert sie → die Auswertung kann vorher/nachher vergleichen.
- **Konto:** Standardkonto setzt der Code (`BelegAnalyse._konto_festlegen`), nur Konto-Ausnahmen stehen im
  Prompt. Erlaubte Konten je Kategorie: `konten_registrieren(kategorien.konten(stand))`.
- **Bekannte Aussteller:** `App._merkmale_bereitstellen` setzt bei jedem Durchlauf die Liste
  (`merkmale.aus_kategorien` + `aus_bewertungen` → `registrieren`, globale Variable `merkmale._BEKANNT`).
  Nicht im Prompt. Ausführlich mit Beispiel: [AUSWERTUNG_BEKANNTE_AUSSTELLER.md](AUSWERTUNG_BEKANNTE_AUSSTELLER.md).

### 5.2 Probelauf

`testlauf.ausfuehren` analysiert Belege mit altem und neuem Wissen. Testbelege: geprüfte Belege der Kategorie
(`lernen.testbelege_auswaehlen`, Originale über `App._gepruefte_daten`) oder Beispielbelege aus
`Anlage KI Assistent/<Ordner>/`; Musterlösung = vorhandene Prüfung (`testlauf.felder_vergleichen`).
Kategorien und Konten des Probelaufs gelten nur in den eigenen Threads (`beleg_schema.sonderstand`,
ContextVar; `pipeline` reicht den Kontext per `copy_context()` weiter) – echte Analysen anderer Sitzungen
bleiben unberührt. Es wird nichts gespeichert.

### 5.3 Aus Korrekturen lernen

1. `App._lernfaelle`: geprüfte Belege mit Korrektur, Kommentar oder Nachfrage (`_MAX_LERNFAELLE` = 60).
   `lernen.vorsortiert` nimmt eindeutige Lesefehler heraus; `lernen.wissensaenderungen` + `veraltet` lassen
   Fälle aus, deren Kategorie seit der Analyse geändert wurde.
2. Ein Aufruf des großen Modells (`kategorien.LERN_PROMPT`), abgesichert durch `lern_antwort_pruefen`.
3. „Übernehmen“ → ungespeicherte Änderung im Kategorien-Tab; gespeichert mit `aus_lernrunde`.
   `lernen.wirkung` zeigt die Fehlerquote vorher/nachher. Jede Runde liegt in `lernrunden/`.

### 5.4 Messen

`App.zeige_auswertung`: Trefferquoten; „unnötige Nachfrage“ = alles richtig und kein Grund aus
`checks.immer_berechtigt`. `lesequalitaet.auswerten` vergleicht jede gespeicherte Lesung mit dem richtigen
Wert; `schiedsrichter_wirkung` rechnet die Auslöser aus den ersten Lesungen nach (`mit_merkmalen=False`, weil es
die heutige Aussteller-Liste damals nicht gab).

## 6. Datenablage

### 6.1 Wo

Mit `[google_drive]` in den Secrets ein gemeinsamer Drive-Ordner; die App schreibt mit dem Refresh-Token des
Ordner-Besitzers (`drive_token_holen.py`). Ohne Drive: lokal `data/`. Halb konfiguriertes oder nicht
erreichbares Drive **sperrt** die App – das Dateisystem auf Streamlit Cloud ist nicht dauerhaft.

```text
<Drive-Ordner>/
├── belege/            Originaldateien: <sha256[:16]><endung>
├── analysen/          eine JSON-Datei je Analyse
├── feedback/          eine JSON-Datei je Prüfung
├── kategorien/        eine JSON-Datei je Kategorie-Version
├── lernrunden/        eine JSON-Datei je Runde „Aus Korrekturen lernen“
├── kalender_zugang/   Kalender-Verbindung (verschlüsselt), jüngster Eintrag gilt
├── nachfragen/        ältere Nachfragen (vor 2026-11-18), nur gelesen
├── entscheidungen/    Entscheidungen der ersten Version, nur gelesen
└── Anlage KI Assistent/<Kategorie>/   Beispielbelege + lesbares Google-Doc je Kategorie
```

Dateiname: `<zeitpunkt>_<sha256[:16]>.json`. Lokal stattdessen eine Zeile je Eintrag in `<art>.jsonl`.

### 6.2 Regeln

- **Nur anhängen**, nie überschreiben. Es gilt der jüngste Eintrag pro `datei_sha256`, bei Kategorien die
  höchste Version.
- **Ausnahme „Beleg entfernen“:** alle Einträge dieses Hashs und nicht mehr genutzte Originale in den
  Drive-Papierkorb (30 Tage wiederherstellbar; lokal `data/papierkorb/`), nie endgültig löschen.
- Formate nur **erweitern** – alte Einträge müssen lesbar bleiben.
- **Zeitpunkte** (`beleg_schema.jetzt_iso`): deutsche Zeit ohne Zeitzone. Bis 27.11.2026 schrieb die Cloud UTC
  (Anzeige alter Einträge 1–2 h zu früh); die Reihenfolge stimmt trotzdem.
- **Caching:** Dateiliste je Ordner 5 Minuten, einzelne Dateien dauerhaft (`storage._JSON_CACHE`). Eigene
  Schreibvorgänge leeren den Listen-Cache sofort. Laden parallel (`DRIVE_PARALLEL` = 8).

### 6.3 Einträge (vereinfacht)

**`analysen/`** (`App._beleg_ablegen`):

```json
{
  "zeitpunkt": "2026-11-17T23:39:55", "datei_sha256": "df125137…", "dateiname": "rechnung.pdf",
  "beleg_pfade": ["belege/df125137280035f1.pdf"], "seiten": 2, "kategorie": "restaurant_mit_ec_beleg",
  "gruende": ["Unsicher gelesen – EC-Betrag: 350,00 € / 315,50 €"],
  "analyse": { "…": "Endergebnis (BelegAnalyse)" },
  "lesungen": [ {"modell": "…", "variante": "original", "analyse": { … }, "rohantwort": "…", "fehler": null} ],
  "schiedsrichter": true, "kalender": { … }, "modell": "…", "prompt_version": "…", "dauer_s": 41.2,
  "schiedsrichter_aus": true,          // nur wenn abgeschaltet
  "belegart_richtiggestellt": { … },   // nur wenn per bekanntem Aussteller gesetzt: {ki, neu, aussteller}
  "herkunft": "beispielordner"         // nur bei Belegen aus dem Probelauf-Fenster
}
```

**`feedback/`** (`App._beleg_formular`):

```json
{
  "zeitpunkt": "2026-11-18T09:12:03", "datei_sha256": "df125137…", "analyse": { … },
  "quelle": "nachfrage",               // oder "pruefung"; fehlt = Formular der ersten Version
  "kategorie": {"modell": "restaurant_mit_ec_beleg", "korrekt": "uebernachtung", "richtig": false},
  "felder": { "brutto": {"modell": 315.5, "korrekt": 315.5, "richtig": true} },
  "kommentar": "EC-Beleg auf Seite 2 übersehen", "bearbeiter": "…",
  "korrektur_von": "…", "kommentar_vorher": "…"   // nur bei Korrektur einer früheren Prüfung
}
```

**`kategorien/`** (`App._kategorie_sichern`):

```json
{
  "zeitpunkt": "…", "schluessel": "reisekosten_mitarbeiter", "name": "Reisekosten - Mitarbeiter",
  "beschreibung": "…", "erkennungsmerkmale": "…", "abgrenzung": "…", "pflichtangaben": ["…"],
  "nachfragen_wenn": "…", "status": "aktiv", "version": 3, "bearbeiter": "…",
  "skr04_konto": "6663", "konto_ausnahmen": [{"wenn": "…", "konto": "…"}],
  "bekannte_merkmale": [{"art": "aussteller", "wert": "DB Fernverkehr AG", "anmerkung": "…"}],
  "aus_lernrunde": [{"runde": "…", "feld": "abgrenzung", "text": "…"}]
}
```

**`lernrunden/`**: `erstellt`, `faelle`, `vorschlaege`, `rueckfragen`, `dateien`/`shas`, `anzahl`,
`vorsortiert`, `ausgelassen_veraltet`, `modell`. **`kalender_zugang/`**: `verbunden`, `konto`,
`token_verschluesselt` (Schlüssel aus `[auth].cookie_secret`), `kalender [{id, name}]`.

## 7. Streamlit-Fallstricke

- **Jede Eingabe führt `App.py` neu aus.** Lange Vorgänge über `_lauf_knopf` (gesperrter Knopf mit Spinner,
  gesperrte Tabs, danach `st.rerun()`), sonst bricht ein Klick sie ab. Ergebnisse in `st.session_state`.
- Widget-Werte lassen sich nach dem Zeichnen nicht setzen → „pending“-Schlüssel vor dem Widget
  (`beleg_wahl_naechste`, `kategorie_wahl_naechste` …).
- CSS über `key=` → Klasse `.st-key-<key>`; Tabs sind react-aria (`[role=tab]`).
- JavaScript über `st.html(..., unsafe_allow_javascript=True)`; Streamlits HTML-Filter entfernt Skripte, die
  nach Markup aussehen → `browser_skripte.maskieren`.

## 8. Tests, Betrieb, Einrichtung

- `python -m pytest` (ca. 10 s, ohne API, Drive oder Secrets). UI-Tests starten die echte `App.py` mit
  `AppTest` und vorgetäuschter Ablage/KI (`tests/attrappe.py`). Browser-Tests (Tour) in `tests/browser/`.
- Lokal: `LOGIN_DEAKTIVIERT=1 streamlit run App.py` (nur über die Umgebung).
- Secrets (Vorlage `.streamlit/secrets.toml.example`): `OPENROUTER_API_KEY`, `[auth]`, `[zugang]`,
  `[google_drive]`, optional `[kalender]`, `[datenschutz]`. Nie committen.
- **Google:** OAuth-Client „Webanwendung“ mit Weiterleitungs-URIs `https://<app>.streamlit.app/oauth2callback`,
  `http://localhost:8501/oauth2callback`, `http://localhost:8080/` (für `drive_token_holen.py`) und der
  App-Startseite (Kalender verbinden). Zustimmungsbildschirm „In Produktion“, sonst läuft der Token nach 7 Tagen
  ab. Kein Service-Account (hat bei privaten Gmail-Konten kein Speicherkontingent).

## 9. Wichtige Entscheidungen

- **Modelle:** Qwen3-VL mit offenen Gewichten, später lokal auf einer RTX 3090 (24 GB). Dort passt nur das
  30B-Modell → `SCHIEDSRICHTER_MODELL` auf das 30B-Modell setzen (liest dann nur höher aufgelöst nach).
- **Das Modell rechnet nicht** (Domhof: MwSt. 11,40 statt 11,35). Die Steuerzeilen erlauben die Gegenprobe.
- **Keine echten Zahlen im Prompt-Beispiel** – sonst kopiert das Modell sie.
- **Kein „Vertrauen“-Wert** vom Modell (nicht kalibriert), stattdessen `kategorie_unsicher` + Begründung und
  harte Prüfungen im Code.
- **Datenschutz:** nur Anbieter ohne Datenspeicherung (`data_collection: deny`); `data/` nie committen.
- **JSON-Parsing:** `response_format=json_object` (ohne, falls der Anbieter das ablehnt), dann tolerant parsen
  und validieren.
- **Vergleich** (`werte_gleich`): Beträge auf den Cent, `0,00` = leer, Text ohne Groß-/Kleinschreibung;
  bei Steuersätzen ist das Komma ein Trennzeichen (`7,19` = 7 % und 19 %).
- **Oberfläche deutsch formatiert** (17.11.2026 16:20, 1.234,50 €), gespeichert ISO bzw. Zahl.
- **Barrierearm:** Ergebnisse als Wort, nicht nur Farbe; `st.table` für Ergebnis-Tabellen; ausreichender Kontrast.

## 10. Fachliche Vorgaben der Buchhaltung (Bewirtung)

- Quittung muss lesbar sein, Steuersatz (7 % / 19 %) und Datum ausweisen; bei Abweichungen immer einen Menschen
  fragen.
- Wichtig: Belegnummer, Restaurant, Belegdatum, Netto, Brutto. Restaurant- + EC-Beleg: Differenz = Trinkgeld.
- Für den Bewirtungsbeleg (Google-Doc): Belegnummer, Restaurant, Bewirtungskosten brutto, MwSt., Trinkgeld, Tag;
  manuell: Bewirtender, bewirtete Personen (künftig aus dem Kalender), Anlass.
- Auslandsbelege: immer Nachfrage. Bewirtung strikt von Tanken und Übernachtung trennen.

## 11. Bekannte Grenzen

- Kein Mehrbenutzer-Echtzeitbetrieb, keine Mandantentrennung (bewusst: interner PoC). Ausbau:
  [KONZEPT_PLATTFORM.md](KONZEPT_PLATTFORM.md).
- JSON-Dateien in Drive: bei einigen tausend Einträgen wird das erste Laden langsam.
- Textfelder haben keine Rechen-Gegenprobe (Plan: OCR-Modell als zusätzliche Gegenprobe).
