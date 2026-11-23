# BelegAssistent – technischer Ablauf (Stand 2026-11-18)

Für Entwickler, die neu ins Projekt kommen: was die App macht, wie ein Beleg Schritt für Schritt durchläuft,
wie die KI „lernt“ und wie die Daten gespeichert werden. Fachliche Details zu Rechnen und Prüfen stehen in
[PRUEFABLAUF.md](../PRUEFABLAUF.md), die Arbeitsweise im Projekt in [CLAUDE.md](../CLAUDE.md).

---

## 1. Überblick

Der BelegAssistent ist ein interner Proof of Concept (RE-ALIS GmbH): Belege hochladen → ein Vision-Sprachmodell
ordnet sie ein und liest die Daten ab → der Code rechnet nach und entscheidet, ob ein Mensch nachschauen muss
→ ein Mensch prüft und korrigiert → jede Prüfung wird gespeichert und dient als Messgrundlage und Lernmaterial.

| | |
|---|---|
| Sprache / Oberfläche | Python 3.11, Streamlit 1.67 (eine Seite, vier Tabs) |
| KI | OpenRouter (OpenAI-kompatible API). Lesen: `qwen/qwen3-vl-30b-a3b-instruct`; Schiedsrichter, Kategorie-Assistent, Verbesserungsvorschläge: `qwen/qwen3-vl-235b-a22b-instruct` |
| Ablage | Google-Drive-Ordner der Firma (lokal ersatzweise `data/`) – JSON-Dateien, nur anhängen |
| Login | Google über `st.login`, Freigabeliste in den Secrets |
| Betrieb | Streamlit Community Cloud, Deploy bei jedem Push auf `main`; Tests per GitHub Actions |

**Wichtigster Grundsatz:** Das Modell **liest nur ab**, der **Code rechnet und prüft**. Das Modell wird nie
nachtrainiert – „Lernen“ heißt: die Anweisungen (der Prompt) werden aus gepflegtem Wissen zusammengesetzt und
anhand gesammelter Korrekturen verbessert (Abschnitt 5).

---

## 2. Dateien

| Datei | Aufgabe |
|---|---|
| `App.py` | Gesamte Oberfläche. Wird von Streamlit **bei jeder Eingabe komplett neu ausgeführt** (Zustand in `st.session_state`) |
| `pipeline.py` | Ablauf einer Analyse: doppelt lesen, vergleichen, ggf. Schiedsrichter |
| `extraction.py` | Bilder aufbereiten (PDF → Bilder, Drehen, Verkleinern), Modell-Aufruf, JSON aus der Antwort holen |
| `beleg_schema.py` | Datenmodell `BelegAnalyse` (Pydantic), Felder, Kategorien, Rechnen mit Decimal, deutsche Formate, Vergleich |
| `checks.py` | Rechenprüfungen und Nachfragegründe (inkl. Einordnung „rein fachlich“) |
| `prompts.py` | System-Prompt-Vorlage, `PROMPT_VERSION` |
| `kategorien.py` | Kategorie-Wissen: Versionen → aktueller Stand → Prompt-Abschnitt; KI-Assistent; Prompt für „Aus Korrekturen lernen“ |
| `testlauf.py` | Probelauf einer Kategorie-Änderung (vorher/nachher) mit Beispielbelegen |
| `lesequalitaet.py` | Welche Lesung lag richtig? (Auswertung) |
| `kalender.py` | Abgleich Bewirtung/Übernachtung mit dem Firmenkalender |
| `kalender_verbindung.py` | „Kalender verbinden“: Google-Anmeldung nur für Kalender lesen, Rücksprung prüfen, Zugang verschlüsseln |
| `storage.py` | Ablage (Drive bzw. lokal), Kalenderzugriff |
| `auth.py`, `marke.py`, `datenschutz.py` | Login, Branding, Datenschutzseite |
| `einfuehrung.py`, `browser_skripte.py`, `assets/*.js` | Browser-Skripte: Einführungs-Tour, Blättern in der Belegansicht, hell/dunkel (`thema.js`) |
| `tests/` | pytest – Logik, Pipeline, Ablage, Oberfläche mit vorgetäuschter Ablage/KI (`tests/attrappe.py`) |

---

## 3. Ablauf einer Analyse (Tab „Belege hochladen“)

```
Upload ─► Bilder ─► 2 Lesungen parallel ─► Vergleich + Prüfungen ─┬─► fertig (stimmig)
                                                                  ├─► fertig + Nachfrage (rein fachlicher Grund)
                                                                  └─► Schiedsrichter ─► erneut prüfen
        ─► Kalenderabgleich ─► ablegen (belege/ + analysen/) ─► Ergebnis anzeigen
```

1. **Upload** (`App.py`): eine oder mehrere Dateien. Mehrere Dateien sind entweder ein **Stapel** (jede Datei
   ein Beleg, bis 30, drei gleichzeitig in Threads) oder **ein Beleg** (z. B. Rechnung + EC-Beleg).
   Der Analyse-Knopf läuft über `_lauf_knopf`: Klick → neuer Durchlauf mit gesperrtem Knopf (Spinner) und
   gesperrten Tabs, dann die eigentliche Arbeit, dann `st.rerun()`.
2. **Beleg-Kennung:** `sha256` der Datei; bei mehreren Dateien `sha256` über die Einzel-Hashes. Diese
   **`datei_sha256`** verbindet alle Einträge zu einem Beleg.
3. **Bilder** (`extraction.dateien_zu_bildern`): PDF-Seiten mit 150 dpi rendern (pymupdf), Fotos nach EXIF
   drehen, längste Kante auf 2000 px (ab 6 Seiten 1600 px), JPEG. Höchstens 20 Seiten.
4. **Zwei Lesungen parallel** (`pipeline.beleg_lesen`): Originalbilder und eine Kontrast-Variante, beide mit dem
   30B-Modell und dem **aktuellen System-Prompt** (`SYSTEM_PROMPT_AKTUELL`, siehe 5.1). Aufruf
   (`extraction._modell_aufrufen`): `temperature=0.1`, `max_tokens=1500`, `response_format=json_object`,
   `provider.data_collection=deny` (nur Anbieter ohne Datenspeicherung). Antwort → JSON → `BelegAnalyse`
   (tolerante Validierung; das Modell liefert z. B. Steuerzeilen, der Code rechnet MwSt.-Summe, Netto,
   Trinkgeld cent-genau aus).
5. **Vergleich und Prüfungen** (`checks.py`): `abweichungen` zwischen den beiden Lesungen (Text tolerant,
   Beträge auf den Cent), `pruefen` (Rechenprüfungen: Steuerzeilen = Gesamtbetrag, MwSt. passt zum Satz,
   EC ≥ Rechnung, Datum plausibel …), `nachfragen_gruende` (unlesbar, Belegart unsicher, Pflichtangaben
   fehlen, Ausland, kein Steuersatz …).
6. **Entscheidung:**
   - beide Lesungen gleich, keine Gründe → **fertig**, Ergebnis = Lesung 1
   - beide gleich, nur **rein fachliche** Gründe (Ausland, nur EC-Beleg, ungewöhnlicher Steuersatz) → fertig
     ohne Schiedsrichter, Nachfrage bleibt
   - sonst → **Schiedsrichter**: 235B-Modell liest in hoher Auflösung (2800 px); sein Ergebnis gilt, danach
     alle Prüfungen erneut. Abweichende Felder, die er nicht bestätigen kann → Grund „Unsicher gelesen“.
7. **Kalenderabgleich** (`kalender.py`, optional): Bewirtung/Übernachtung ↔ Termin in allen gewählten Kalendern
   (Seitenleiste „Kalender verbinden“, sonst `[kalender]` in den Secrets); kein passender Termin → zusätzlicher
   Nachfragegrund.
8. **Ablegen** (`App._beleg_ablegen`): Originaldatei nach `belege/`, ein Eintrag nach `analysen/` – **immer**,
   auch ohne Nachfrage. Ergebnis landet in `st.session_state` und wird angezeigt; geprüft wird im Tab „Belege“.

---

## 4. Prüfen durch den Menschen (Tab „Belege“)

`App._alle_belege()` führt pro `datei_sha256` zusammen: jüngste Analyse (bzw. ältere Nachfrage), jüngste
Prüfung und – nur noch lesend – Entscheidungen der ersten Version. Daraus ergibt sich der **Status**:
*Nachfrage offen* · *Noch nicht geprüft* · *Geprüft – alles richtig* · *Geprüft – korrigiert* ·
*Erledigt (ohne Bewertung)*. Berechnet wird das **einmal pro Durchlauf** (`_LAUF_CACHE`).

Darüber filtert eine **Suchleiste** (`App._belege_suchen`): Suchbegriffe, Belegart, Zeitraum. Grundlage sind
`App._beleg_werte` – bei geprüften Belegen die korrigierten Werte, sonst die KI-Lesung.

Prüfen (`App._beleg_formular`):

1. „Stimmt die Belegart …? Ja/Nein“ – ohne Vorauswahl, damit niemand die KI versehentlich bestätigt.
2. Felder sind mit der KI-Lesung (bzw. den bisher richtigen Werten) vorbelegt; Falsches überschreiben.
3. Begründung: Pflicht bei Nachfragen und Korrekturen, sonst nur bei Änderungen.
4. Speichern = **neuer** Eintrag in `feedback/`. Je Feld wird `modell` (KI), `korrekt` (Mensch) und
   `richtig` (gleich?) gespeichert. Verglichen wird immer mit der KI-Lesung, nie mit einer früheren Prüfung.
   Eine Korrektur einer Prüfung ist ebenfalls ein neuer Eintrag (`korrektur_von`, `kommentar_vorher`).

---

## 5. Wie die KI „lernt“

Das Modell selbst lernt nichts – seine Gewichte ändern sich nie. Gelernt wird über den **Prompt**, den
Menschen pflegen, und über **Messung**:

```
      ┌──────────── Kategorie-Wissen (Tab „Kategorien“) ◄───────────────┐
      │              Versionen, aktiv/Entwurf                           │ übernehmen, testen,
      ▼                                                                 │ speichern (Mensch)
 System-Prompt ─► Analyse ─► Prüfung durch Menschen ─► Auswertung ─► Verbesserungsvorschläge
 (+ Prompt-Version)              (feedback/)           (Trefferquote,    (großes Modell liest
                                                        Lesequalität)     alle Korrekturen)
```

### 5.1 Kategorie-Wissen → Prompt

- Jede Kategorie (Standard wie „Bewirtung“, „Tankbeleg“ oder selbst angelegt) hat Felder: Beschreibung
  (Freitext der Buchhaltung), Erkennungsmerkmale, Abgrenzung, Pflichtangaben, „Wann nachfragen?“, Status.
- Jede Änderung im Tab „Kategorien“ ist eine **neue Version** in `kategorien/` (nur anhängen; Löschen =
  Version mit Status `geloescht`). `kategorien.aktueller_stand` nimmt pro Schlüssel die jüngste Version.
- `kategorien.prompt_abschnitt` setzt **nur aktive** Kategorien mit all ihren Regeln in die Prompt-Vorlage
  (`prompts.system_prompt`) ein. Das passiert bei jedem Seitenaufruf → Änderungen wirken sofort für alle.
- **SKR04-Konto** je Kategorie (`skr04_konto` 4-stellig, `skr04_bezeichnung` optional): aus der Vorlage in
  `skr04.py` übernehmen oder frei eintragen. Ohne Konto wird trotzdem gespeichert (nur Hinweis), eine falsche
  Nummer verhindert das Speichern. Das Standardkonto allein steht **nicht** im Prompt – der Code setzt es.
- **Konto-Ausnahmen** (`konto_ausnahmen`: `[{wenn, konto, bezeichnung}]`, Tabelle im Kategorien-Tab): Erst
  dann kommt eine Zeile „Konto (SKR04): Standard … Ausnahmen: …, wenn …“ in den Prompt (und in den
  Fingerabdruck). Die KI gibt `konto`, `konto_unsicher`, `konto_grund` aus. `beleg_schema.KONTEN`
  (`konten_registrieren(kategorien.konten(stand))`) legt fest, welche Konten je Kategorie erlaubt sind;
  `BelegAnalyse._konto_festlegen` ersetzt alles andere durch das Standardkonto. `konto_unsicher` → Nachfrage
  (rein fachlich, kein Schiedsrichter); unterschiedliches Konto in den zwei Lesungen → Schiedsrichter.
  Das Konto ist Prüffeld im Tab „Belege“ und erscheint in Auswertung und Lesequalität.
- Der **KI-Assistent** (Knopf im Kategorien-Tab) formt aus dem Freitext klare Regeln und stellt Rückfragen –
  nur als Vorschlag im Formular, gespeichert wird erst per „Speichern“.
- **Prompt-Version** = `PROMPT_VERSION` + `+k` + Fingerabdruck des aktiven Kategorie-Wissens
  (`kategorien.wissens_hash`, 6 Zeichen), z. B. `2026-11-17.5+k3af32b`. Jede Analyse und Prüfung speichert sie
  → die Auswertung kann nach Version filtern und vorher/nachher vergleichen.

### 5.2 Vor dem Speichern testen (Probelauf)

`testlauf.py`: Beispielbelege aus `Anlage KI Assistent/<Ordner>/` werden einmal mit dem gespeicherten und
einmal mit dem geänderten (noch ungespeicherten) Wissen komplett analysiert; Ergebnis: wie oft die Kategorie
erkannt wurde, wie viele Nachfragen, ein Fazit („Die Änderung hilft“ …). Es wird nichts gespeichert.
Dazu das **Konto** je Beleg und Variante: Während des Laufs erlaubt `konten_vereinigen` alle Konten beider
Varianten, danach wertet `beleg_schema.konto_waehlen` jede Lesung nach den Konto-Regeln ihrer Variante aus –
so wirken auch noch nicht gespeicherte Ausnahmen. Ein anderes Konto zählt in der Spalte „Unterschied“.
Kategorien und Konten des Probelaufs setzt `beleg_schema.sonderstand` (ContextVar) nur für die eigenen
Threads; `pipeline.beleg_lesen` reicht den Kontext per `copy_context()` an seine Lese-Threads weiter. Die
globalen `KATEGORIEN`/`KONTEN` (und damit echte Analysen anderer Sitzungen) bleiben unberührt.
**Musterlösungen schaffen:** `App._beispiele_ablegen` (Knopf im Probelauf-Fenster) analysiert noch nicht
abgelegte Beispielbelege mit `_beleg_verarbeiten` (3 parallel) und legt sie mit `herkunft: "beispielordner"` ab.
**Musterlösung:** `App._musterloesungen` sucht zu jedem Beispielbeleg (Datei-Hash) eine Prüfung aus dem Tab
„Belege“; `testlauf.felder_vergleichen` zählt dann richtig gelesene Felder (`werte_gleich` wie in der
Auswertung), `erwartet_fuer` nimmt deren Belegart als Erwartung.

### 5.3 Messen (Tab „Auswertung“)

- **Erkennungsqualität:** jede geprüfte Belegprüfung zählt einmal (jüngste pro Hash): Belegart richtig,
  alle Felder richtig, je Feld, je Belegart, Verwechslungen; Belege/geprüft/Nachfragen/unnötige Nachfragen
  („unnötig“ = alles richtig und kein Grund, der laut `checks.immer_berechtigt` ohnehin einen Menschen braucht –
  Ausland, nur EC-Beleg, Steuersatz, Konto, Kalender, Seitenlimit, technische Absicherung).
- **Lesequalität** (`lesequalitaet.py`): jede gespeicherte Lesung (Original, Kontrast, Schiedsrichter) wird
  Feld für Feld mit dem richtigen Wert verglichen → wo wird falsch gelesen, bringen zweite Lesung und
  Schiedsrichter etwas?
- **Wann hilft der Schiedsrichter?** (`lesequalitaet.schiedsrichter_wirkung`): über alle Belege mit
  Schiedsrichter-Lesung; Auslöser aus den ersten Lesungen nachgerechnet (`checks.nachfragen_gruende`,
  `abweichungen`, `grund_art`), je Auslöser: aufgelöst, anders gelesen, laut Prüfung besser/schlechter.
  `ueberspringen_kandidaten` nennt Auslöser mit ≥ 5 Einsätzen ohne jede Wirkung – Grundlage, um den
  Schiedsrichter dort in `pipeline.beleg_lesen` zu überspringen (noch nicht umgesetzt, erst Daten sammeln).

### 5.4 Aus Korrekturen lernen

1. Fälle = geprüfte Belege mit Korrektur, Kommentar oder Nachfrage (höchstens 60, neueste zuerst).
2. Ein Aufruf des großen Modells (`kategorien.LERN_PROMPT`) mit dem Kategorie-Wissen und den Fällen: Es
   ordnet jeden Fall einer Ursache zu (*Regel fehlte*, *Unnötige Nachfrage*, *Lesefehler*, *Bewertung
   widersprüchlich*, *Unklar*) und schlägt Sätze vor, die genau ein Feld einer Kategorie ergänzen.
3. `kategorien.lern_antwort_pruefen` sichert ab: nur bestehende Kategorien/Felder, gültige Fallnummern,
   ein Vorschlag aus nur einem Fall gilt als „Einzelfall“.
4. „In Kategorie übernehmen“ setzt den Satz als **ungespeicherte Änderung** in den Kategorien-Tab. Ein Mensch
   prüft, macht den Probelauf und speichert → neue Kategorie-Version → neue Prompt-Version → die Auswertung
   zeigt, ob es besser wurde.

**Kurz:** Daten sammeln (Prüfungen) → Muster finden (großes Modell, Vorschlag) → Mensch entscheidet und testet
→ Prompt ändert sich versioniert → Wirkung messen. Nichts davon läuft automatisch ohne menschliche Freigabe.

---

## 6. Datenablage

### 6.1 Wo

Mit `[google_drive]` in den Secrets: ein **gemeinsamer Drive-Ordner** (`ordner_id`) für alle Benutzer; die App
schreibt mit dem Refresh-Token des Ordner-Besitzers (`drive_token_holen.py`). Ohne Drive: lokaler Ordner
`data/` (bzw. `BELEG_DATENORDNER`). Halb konfiguriertes oder nicht erreichbares Drive **sperrt** die App
(lieber kein Betrieb als Daten verlieren – das Dateisystem auf Streamlit Cloud ist nicht dauerhaft).

```
<Drive-Ordner>/
├── belege/            Originaldateien: <sha256[:16]><endung>, z. B. 0f7e312ba61d7fda.pdf (Duplikate nur einmal)
├── analysen/          eine JSON-Datei je Analyse
├── feedback/          eine JSON-Datei je Prüfung
├── kategorien/        eine JSON-Datei je Kategorie-Version
├── kalender_zugang/   Kalender-Verbindung (Zugang verschlüsselt, gewählte Kalender), jüngster Eintrag gilt
├── nachfragen/        ältere Nachfragen (vor 2026-11-18), nur noch gelesen
├── entscheidungen/    Entscheidungen der ersten Nachfragen-Version, nur noch gelesen
└── Anlage KI Assistent/<Kategorie>/   Beispielbelege + lesbares Google-Doc je Kategorie
```

Dateiname je Eintrag: `<zeitpunkt>_<sha256[:16]>.json`, z. B. `2026-11-17T23-39-55_df125137280035f1.json`.
Lokal stattdessen eine Zeile je Eintrag in `<art>.jsonl` (Rechte 0700/0600).

### 6.2 Regeln

- **Nur anhängen, nie überschreiben oder löschen.** Jede Analyse, Prüfung und Kategorie-Änderung ist ein neuer
  Eintrag mit `zeitpunkt` (ISO, Sekunden). Dadurch ist nachvollziehbar, wer wann was gemacht hat.
- **Es gilt der jüngste Eintrag** pro `datei_sha256` (Analysen, Prüfungen) bzw. pro `schluessel` (Kategorien).
- Formate werden nur **erweitert** – alte Einträge müssen lesbar bleiben (Code liest fehlende Felder mit
  Standardwerten, z. B. `quelle` fehlt = altes Feedback).
- **Caching:** Die Dateiliste eines Unterordners wird 5 Minuten gecacht, jede einzelne Datei dauerhaft (Dateien
  ändern sich nie). Eigene Schreibvorgänge leeren den Listen-Cache sofort; Einträge anderer Benutzer erscheinen
  nach spätestens 5 Minuten.
- **Paralleles Laden:** Noch nicht geladene Dateien holt `storage._drive_jsons_holen` mit `DRIVE_PARALLEL` = 8
  gleichzeitig, jeder Thread mit eigener Drive-Verbindung (der HTTP-Client ist nicht thread-sicher), bei 429/5xx
  bis zu 3 Wiederholungen. Geladene Einträge liegen in `storage._JSON_CACHE` (Speicher des Servers, alle
  Sitzungen). Gemessen 2026-11-23: Kaltstart der App 45 s → 24 s; pro Datei sonst knapp 1 s nacheinander.

### 6.3 Einträge (vereinfacht)

**`analysen/`** – geschrieben in `App._beleg_ablegen`:

```json
{
  "zeitpunkt": "2026-11-17T23:39:55",
  "datei_sha256": "df125137…", "dateiname": "rechnung.pdf",
  "beleg_pfad": "belege/df125137280035f1.pdf", "beleg_pfade": ["belege/df125137280035f1.pdf"], "seiten": 2,
  "kategorie": "restaurant_mit_ec_beleg",
  "gruende": ["Unsicher gelesen – EC-Betrag: 350,00 € / 315,50 € / –"],
  "analyse": { "kategorie": "…", "brutto": 315.5, "steuerzeilen": [ … ], "…": "Endergebnis (BelegAnalyse)" },
  "lesungen": [ {"modell": "qwen/…30b…", "variante": "original", "analyse": { … }, "rohantwort": "…", "fehler": null},
                {"variante": "kontrast", …}, {"variante": "hochaufgelöst", …} ],
  "rohantwort": "…", "schiedsrichter": true, "kalender": { … },
  "modell": "qwen/qwen3-vl-235b-a22b-instruct", "prompt_version": "2026-11-17.5+k3af32b",
  "dauer_s": 41.2, "benutzer_email": "…",
  "herkunft": "beispielordner"   // nur bei Belegen aus dem Probelauf-Knopf; fehlt = normaler Upload
}
```

**`feedback/`** – eine Prüfung (`App._beleg_formular`):

```json
{
  "zeitpunkt": "2026-11-18T09:12:03",
  "datei_sha256": "df125137…", "dateiname": "rechnung.pdf", "beleg_pfade": ["belege/…"],
  "modell": "…", "prompt_version": "…", "analyse": { … },
  "quelle": "nachfrage",
  "nachfrage_gruende": ["…"],
  "kategorie": {"modell": "restaurant_mit_ec_beleg", "korrekt": "uebernachtung", "richtig": false},
  "felder": {
    "brutto": {"modell": 315.5, "korrekt": 315.5, "richtig": true},
    "ec_betrag": {"modell": null, "korrekt": 350.0, "richtig": false}
  },
  "kommentar": "EC-Beleg auf Seite 2 übersehen",
  "bearbeiter": "…", "benutzer_email": "…",
  "korrektur_von": "2026-11-17T23:45:10", "kommentar_vorher": "…"
}
```

`quelle`: `nachfrage` (KI hatte nachgefragt), `pruefung` (ohne Nachfrage geprüft), fehlt = Feedback-Formular
der früheren Version. `korrektur_von`/`kommentar_vorher` nur, wenn eine frühere Prüfung korrigiert wurde.

**`kategorien/`** – eine Version (`App._kategorie_sichern`):

```json
{
  "zeitpunkt": "2026-11-17T10:00:00", "schluessel": "reisekosten_mitarbeiter", "name": "Reisekosten - Mitarbeiter",
  "beschreibung": "…", "erkennungsmerkmale": "…", "abgrenzung": "…",
  "pflichtangaben": ["Name des Mitarbeiters", "Reisezeitraum"], "nachfragen_wenn": "…",
  "status": "aktiv", "version": 3, "bearbeiter": "…"
}
```

**`kalender_zugang/`** – Verbindung aus der Seitenleiste (`storage.kalender_ruecksprung`,
`kalender_auswahl_speichern`, `kalender_trennen`):

```json
{
  "zeitpunkt": "2026-11-22T10:00:00", "verbunden": true, "konto": "…@…", "bearbeiter": "…",
  "token_verschluesselt": "gAAAA…", "kalender": [{"id": "…@group.calendar.google.com", "name": "Firma"}]
}
```

Getrennt = neuer Eintrag `{"verbunden": false}`. Der Zugang ist mit einem Schlüssel aus `[auth].cookie_secret`
verschlüsselt; eine Kopie der Datei allein reicht nicht für den Kalenderzugriff.

### 6.4 Was nicht gespeichert wird

Die Verbesserungsvorschläge („Aus Korrekturen lernen“) leben nur in der laufenden Sitzung; Probelauf-
Ergebnisse ebenso. Gespeichert wird erst, was ein Mensch übernimmt (Kategorie-Version, Prüfung).

---

## 7. Streamlit-Besonderheiten (Fallstricke)

- **Jede Eingabe führt `App.py` komplett neu aus.** Lange Vorgänge deshalb über `_lauf_knopf` (sonst bricht ein
  Klick woanders sie ab); Ergebnisse in `st.session_state` halten.
- Widget-Werte lassen sich nach dem Zeichnen nicht mehr setzen → „pending“-Schlüssel vor dem Widget anwenden
  (`kategorie_wahl_naechste`, `beleg_wahl_naechste`, `belege_filter_naechste`, `kategorie_vorschlaege_naechste`).
- Gestaltung per CSS über `key=` → Klasse `.st-key-<key>`; Tabs sind react-aria (`[role=tab]`).
- JavaScript nur über `st.html(..., unsafe_allow_javascript=True)`; Streamlits HTML-Filter entfernt ein
  `<script>`, dessen Text nach Markup aussieht → `browser_skripte.maskieren`. Sofort-Reaktionen (Blättern
  in der Belegansicht, Tour) laufen deshalb im Browser.

---

## 8. Tests und Betrieb

- `python -m pytest` (ca. 10 s, ohne API, Drive oder Secrets; `pip install -r requirements-dev.txt`).
  UI-Tests starten die echte `App.py` mit `streamlit.testing.v1.AppTest` und vorgetäuschter Ablage/KI
  (`tests/attrappe.py`, echter Drive-Zugriff ist dort gesperrt). GitHub Actions führt sie bei jedem Push aus.
- Manuelle Browser-Tests (Tour, Belegansicht) in `tests/browser/` (Node + Chrome).
- Lokal starten: `LOGIN_DEAKTIVIERT=1 streamlit run App.py` (Login aus, nur über die Umgebung möglich).
- Secrets (Vorlage `.streamlit/secrets.toml.example`): `OPENROUTER_API_KEY`, `[auth]`, `[zugang]`,
  `[google_drive]`, optional `[kalender]`, `[datenschutz]`. Nie committen.

## 9. Bekannte Grenzen

- Kein Mehrbenutzer-Echtzeitbetrieb, keine Mandantentrennung, keine Löschfristen (bewusst: interner PoC).
- Ablage als JSON-Dateien in Drive: bei einigen tausend Einträgen wird das erste Laden langsam.
- Textfelder (Belegnummer, Name, Adresse) haben keine Rechen-Gegenprobe – abgesichert nur durch Doppelt-Lesen
  und Schiedsrichter (siehe „Lesequalität“; Plan: zusätzliches OCR-Modell als Gegenprobe).
- Weiterentwicklung als mandantenfähige Plattform: [KONZEPT_PLATTFORM.md](KONZEPT_PLATTFORM.md).

---

## 10. Einrichtung: Login (Google) und Ablage (Google Drive)

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

---

## 11. Wichtige Entscheidungen

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
- **JSON-Parsing:** erst `response_format=json_object` (Fallback ohne – nur wenn der Anbieter die Anfrage
  ablehnt, also 400/422; Zeitüberschreitung und Überlastung wiederholt der OpenAI-Client selbst), dann direkt parsen,
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

---

## 12. Fachliche Vorgaben der Buchhaltung (Bewirtung)

- Quittung muss **lesbar** sein, **Steuersatz** (7 % und/oder 19 %) ausweisen, **Datum** erkennbar.
  **Bei Abweichungen immer einen Menschen fragen** → Tab/Ordner „Nachfragen“.
- Wichtig: Belegnummer, Restaurantname, Belegdatum, Netto und Brutto.
- Restaurant- + EC-Beleg: Differenz = Trinkgeld. Abgleich von Tag, Datum, Uhrzeit, Adresse, Name
  (`ec_passt_zur_rechnung`).
- Auf den Bewirtungsbeleg (Google-Doc „Bewirtungsbeleg“): Belegnummer, Restaurant, Bewirtungskosten brutto,
  MwSt., Trinkgeld, Tag der Bewirtung. Zusätzlich manuell: Firmenadresse + Bewirtender (meist die
  Geschäftsführung), bewirtete Personen (künftig aus dem Kalender), Anlass, Anlagen = „Quittungsbeleg
  <Restaurant>, <Ort>“, Ort und Datum der Erstellung.
- **Auslandsbelege:** abweichende Handhabe → immer Nachfrage (`ausland`).
- Bewirtung strikt von **Tanken** und **Übernachtung** trennen (eigene Kategorien).
