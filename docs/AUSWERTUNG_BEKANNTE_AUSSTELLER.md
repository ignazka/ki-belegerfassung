# Auswertung „Bekannte Aussteller“ – wie die Zahlen entstanden sind

Stand: 27.11.2026. Ausgewertet wurden die echten Daten im Drive, **nur gelesen**, nichts geschrieben.
Die Auswertung lief über zwei kleine Skripte außerhalb der App (unten vollständig abgedruckt). Sie nutzen
dieselben Funktionen wie die App, damit das Ergebnis genau dem entspricht, was die App rechnen würde.

---

## Schritt 0 – Daten laden

| Funktion | Datei | Was sie tut |
|---|---|---|
| `storage.analysen_laden()` | `storage.py` | Alle Einträge aus `analysen/` (jede KI-Analyse seit 18.11.) |
| `storage.nachfragen_laden()` | `storage.py` | Ältere Einträge aus `nachfragen/` (vor `analysen/`) |
| `storage.feedback_laden()` | `storage.py` | Alle menschlichen Prüfungen aus `feedback/` |
| `storage.kategorien_laden()` | `storage.py` | Alle Kategorie-Versionen aus `kategorien/` |

Weil die Ablage nur anhängt, kann es pro Beleg (Datei-Hash `datei_sha256`) mehrere Einträge geben. Das Skript
sortiert nach `zeitpunkt` und behält je Hash den **jüngsten** – genauso wie `App._belege_zusammenfuehren()`.

Ergebnis: **6 Analysen** (neues Format) und **9 geprüfte Belege**. Es sind mehr Prüfungen als Analysen, weil
ältere Belege noch aus `nachfragen/` stammen oder ohne gespeicherte Analyse geprüft wurden.

---

## Punkt 1 – „9 geprüfte Belege, 8 verschiedene Aussteller, nur DB Fernverkehr zweimal“

**Ablauf im Skript:**

1. Für jede Prüfung wird der **richtige** Ausstellername genommen: `felder.restaurant_name.korrekt` (der Wert,
   den der Mensch bestätigt oder korrigiert hat – nicht die KI-Lesung).
2. Der Name wird mit `merkmale.norm()` vereinheitlicht und danach gruppiert.
3. Gezählt wird, welche Gruppe mindestens zweimal vorkommt.

| Funktion | Datei | Was sie tut |
|---|---|---|
| `merkmale.norm(name)` | `merkmale.py` | Macht Namen vergleichbar: klein geschrieben, Umlaute → ae/oe/ue, Sonderzeichen und Rechtsformen („GmbH“, „AG“, „KG“, „& Co“ …) weg, Leerzeichen weg. „DB Fernverkehr AG“ → `dbfernverkehr` |

**Warum „DB Fernverkehr AG“ heute schon automatisch bekannt ist:** Die App ruft bei jedem Durchlauf
`App._merkmale_bereitstellen()` auf. Diese Funktion

1. holt mit `merkmale.aus_bewertungen(...)` die automatisch bekannten Aussteller aus allen jüngsten Prüfungen,
2. holt mit `merkmale.aus_kategorien(KAT_STAND)` die von Hand eingetragenen,
3. setzt beides mit `merkmale.registrieren(hand, auto)` als gültige Liste.

| Funktion | Datei | Was sie tut |
|---|---|---|
| `merkmale.aus_bewertungen(bewertungen)` | `merkmale.py` | Ein Aussteller gilt als bekannt, wenn er **mindestens `MIN_BELEGE` = 2-mal** geprüft wurde und dabei **immer zur selben Belegart** gehörte. Belege mit „Unlesbar“ oder „Sonstiger Beleg“ zählen nicht. |
| `merkmale.gruppe(kategorie)` | `merkmale.py` | Fasst die Bewirtungs-Unterarten (Restaurant-Beleg, mit EC-Beleg …) zu einer Gruppe „bewirtung“ zusammen. So ist derselbe Gasthof mal mit, mal ohne EC-Beleg kein Widerspruch. |
| `merkmale.registrieren(hand, auto)` | `merkmale.py` | Setzt die Liste, mit der der Code abgleicht. Von Hand Eingetragenes hat Vorrang. |
| `merkmale.aus_kategorien(stand)` | `merkmale.py` | Liest die Tabelle „Bekannte Aussteller“ aller Kategorien. Heute noch leer. |

Die beiden DB-Tickets wurden beide als „Reisekosten Mitarbeiter“ geprüft → 2 Prüfungen, eine Belegart → bekannt.

---

## Punkt 2 – „Nachgestellt: bei keinem der 9 wäre der Aussteller schon bekannt gewesen“

Frage: Hätte die Funktion damals schon etwas gebracht? Dafür wird jeder geprüfte Beleg so behandelt, als käme er
**neu** herein, und die Liste wird nur aus den **anderen 8** Prüfungen gelernt („Leave-one-out“). Sonst würde der
Beleg sich selbst als Beweis zählen.

**Ablauf pro Beleg:**

1. `merkmale.aus_bewertungen(andere_8)` → automatisch bekannte Aussteller ohne diesen Beleg
2. `merkmale.registrieren([], ...)` → als gültige Liste setzen
3. `merkmale.nachschlagen(ki_name)` mit dem Namen, den **die KI** gelesen hatte (`analyse.restaurant_name`) –
   denn beim echten Hochladen kennt der Code nur die KI-Lesung
4. Ergebnis einordnen:
   - nicht gefunden → „unbekannt“
   - gefunden, gleiche Belegart wie die KI → „bestätigt“ (hätte „Belegart unsicher“ entfernt)
   - gefunden, andere Belegart → „Widerspruch“ (hätte eine Nachfrage ausgelöst) – je nachdem, ob die KI
     tatsächlich falsch lag, ein gefangener Fehler oder ein Fehlalarm

| Funktion | Datei | Was sie tut |
|---|---|---|
| `merkmale.nachschlagen(name)` | `merkmale.py` | Sucht den Namen tolerant in der Liste (über `_passt`). Passt er zu zwei Einträgen mit verschiedenen Belegarten, gilt er als nicht eindeutig → `None`. |
| `merkmale._passt(a, b)` | `merkmale.py` | Treffer, wenn die normalisierten Namen gleich sind, einer im anderen steckt (ab 4 Zeichen, „Aral“ in „Aral Tankstelle“) oder sie sich zu ≥ 88 % ähneln (kleine Lesefehler). |

**Ergebnis: 9 × „unbekannt“.** Grund: Der einzige mehrfache Aussteller ist DB Fernverkehr mit genau 2 Prüfungen.
Lässt man eines der beiden Tickets weg, bleibt nur 1 Prüfung übrig – unter `MIN_BELEGE` = 2. Alle anderen
Aussteller kamen nur einmal vor.

Nebenbefund: In den 6 Analysen kam der Grund „Belegart unsicher“ kein einziges Mal vor. Den Teil „bestätigt →
Zweifel entfallen“ kann man mit den heutigen Daten also gar nicht messen.

---

## Punkt 3 – „6 von 9 Belegarten falsch, fünfmal ‚Sonstiger Beleg‘“

**Ablauf im Skript:** Jede Prüfung enthält `kategorie: {modell, korrekt, richtig}` – was die KI gewählt hat,
was richtig ist und ob beides übereinstimmt. Gezählt wurden alle mit `richtig == False`.

| Aussteller | KI wählte | Richtig ist |
|---|---|---|
| Gasthof Zur Krone | Restaurant + EC-Beleg | Übernachtung |
| Trip.com Travel Singapore | Sonstiger Beleg | Reisekosten Mitarbeiter |
| Wizz Air Malta | Sonstiger Beleg | Reisekosten Mitarbeiter |
| Deutsche Post AG | Sonstiger Beleg | Porto/Briefmarken |
| DB Fernverkehr AG | Sonstiger Beleg | Reisekosten Mitarbeiter |
| DB Fernverkehr AG | Sonstiger Beleg | Reisekosten Mitarbeiter |

**„Gab es die Kategorie schon?“** – Zweites Skript: Aus `storage.kategorien_laden()` wird je Kategorie der
**früheste** Zeitpunkt genommen (= angelegt) und mit dem Zeitpunkt der Prüfung verglichen.

| Kategorie | angelegt | Prüfungen |
|---|---|---|
| Reisekosten Mitarbeiter | 17.11. 17:30 | Trip.com 17.11. 18:14 · Wizz Air 17.11. 18:14 · DB 24.11. 09:11 · DB 27.11. 10:18 |
| Porto/Briefmarken | 23.11. 09:24 | Deutsche Post 23.11. 09:27 |

Einschränkung: Verglichen wurde mit dem Zeitpunkt der **Prüfung**, nicht der Analyse (die älteren Belege haben
keinen eigenen Analyse-Eintrag). Trip.com, Wizz Air und Deutsche Post wurden nur Minuten nach dem Anlegen der
Kategorie geprüft – sie wurden sehr wahrscheinlich **vorher** analysiert, deshalb „wohl“. Bei den DB-Tickets
lagen Tage dazwischen: Die KI kannte die Kategorie und hat trotzdem „Sonstiger Beleg“ gewählt.

---

## Hintergrund: Wie das Programm Aussteller „automatisch kennt“

Nicht die KI kennt die Aussteller, sondern der Python-Code. Die Liste steht **nicht im Prompt**: Die KI
liest nur den Namen ab (`restaurant_name`), den Abgleich macht danach der Code. Deshalb ändert sich durch
neue bekannte Aussteller auch die Prompt-Version nicht.

**Wann die Liste entsteht:** Streamlit führt `App.py` bei jedem Klick neu aus. Dabei ruft die App
`_merkmale_bereitstellen()` auf:

```python
auto = merkmale.aus_bewertungen([b["bewertung"] for b in _alle_belege() if b.get("bewertung")])
merkmale.registrieren(merkmale.aus_kategorien(KAT_STAND), auto)
```

`registrieren` legt das Ergebnis in die globale Variable `merkmale._BEKANNT`. Dort liest `merkmale.nachschlagen()`
während der Analyse. Weil die Liste bei jedem Durchlauf neu berechnet wird, gibt es nichts Gespeichertes, das
veralten kann: Wird eine Prüfung korrigiert, gilt die neue Liste beim nächsten Klick.

**Automatisch bekannt vs. von Hand eingetragen:**

| | Automatisch (aus Prüfungen) | Von Hand (Tab „Kategorien“) |
|---|---|---|
| Quelle | `aus_bewertungen`: ≥ 2 Prüfungen, immer dieselbe Belegart | `aus_kategorien`: Tabelle „Bekannte Aussteller“ |
| KI wählt dieselbe Belegart | „Belegart unsicher“ entfällt | „Belegart unsicher“ entfällt |
| KI wählt eine andere Belegart | Nachfrage | Nachfrage |
| KI wählt „Sonstiger Beleg“ | Nachfrage | Belegart wird automatisch richtiggestellt |
| Widerspruch zwischen beiden | Eintrag von Hand gilt | Eintrag von Hand gilt |

**Beispiel mit den DB-Tickets:**

1. 24.11. – erstes DB-Ticket als „Reisekosten Mitarbeiter“ geprüft → 1 Prüfung, noch nicht bekannt.
2. 27.11. – zweites DB-Ticket, dieselbe Belegart → 2 Prüfungen, eine Belegart → beim nächsten Klick steht
   `dbfernverkehr → reisekosten_mitarbeiter` in der Liste.
3. Nächstes DB-Ticket: Die KI liest „DB Fernverkehr AG“ und wählt wieder „Sonstiger Beleg“.
   `nachschlagen` findet den Eintrag, `_aussteller_abgleich` sieht die andere Belegart → Nachfrage
   „Bekannter Aussteller: … gehört bei 2 geprüften Belegen zu ‚Reisekosten Mitarbeiter‘ …“.
4. Wäre „DB Fernverkehr“ von Hand eingetragen, würde stattdessen `belegart_richtigstellen` die Belegart
   gleich auf Reisekosten setzen.

---

## Was der Code jetzt bei einem neuen Beleg tut

Ablauf in `pipeline.beleg_lesen()`, sobald die Lesungen da sind:

1. **`checks.belegart_richtigstellen(analyse)`** – Wählt die KI „Sonstiger Beleg“ und ist der Aussteller
   **von Hand** eingetragen, setzt der Code die Belegart und über `BelegAnalyse._konto_festlegen()` das
   Standardkonto der Kategorie. Es gibt keine Nachfrage und keinen Schiedsrichter. Vermerk:
   `belegart_richtiggestellt`.
2. **`checks.nachfragen_gruende(analyse, befunde)`** → `checks._gruende_mit_art()` → darin
   **`checks._aussteller_abgleich(analyse)`**:
   - Aussteller bekannt, gleiche Belegart → „Belegart unsicher“ entfällt
   - Aussteller bekannt, andere Belegart → Nachfragegrund „Bekannter Aussteller: … gehört … zu …“; weil er
     nicht „fachlich“ ist, darf vorher das große Modell nachsehen
3. Im Tab „Belege“ zeigt `App._beleg_formular()` den Hinweis „Belegart vom Programm richtiggestellt“ an.

Für die beiden DB-Tickets hieße das heute:

- **Nur automatisch bekannt** (Stand jetzt): Das nächste DB-Ticket als „Sonstiger Beleg“ → **Nachfrage** mit
  Hinweis auf Reisekosten.
- **Von Hand eingetragen**: Das nächste DB-Ticket als „Sonstiger Beleg“ → **automatisch** Reisekosten, ohne
  Nachfrage.

---

## Die Skripte

Beide liefen aus dem Repo-Ordner mit `python <skript>`; die Drive-Zugangsdaten kommen aus
`.streamlit/secrets.toml`.

### merkmale_daten.py (Punkte 1–3)

```python
"""Nur lesen: Wie viel bringen bekannte Aussteller mit den heutigen Daten? (Leave-one-out-Simulation)"""
import sys
from collections import Counter, defaultdict
sys.path.insert(0, r"c:\Users\phili\beleg-poc")
import storage, merkmale

# jüngster Eintrag je Datei-Hash
analysen = {}
for e in sorted(storage.nachfragen_laden() + storage.analysen_laden(), key=lambda e: e.get("zeitpunkt") or ""):
    if e.get("datei_sha256"):
        analysen[e["datei_sha256"]] = e
fb = {}
for f in sorted(storage.feedback_laden(), key=lambda e: e.get("zeitpunkt") or ""):
    if f.get("datei_sha256"):
        fb[f["datei_sha256"]] = f

print("Analysen:", len(analysen), " geprüft:", len(fb))

def name_richtig(f):  # vom Menschen bestätigter Ausstellername
    feld = (f.get("felder") or {}).get("restaurant_name") or {}
    return feld.get("korrekt") if "korrekt" in feld else None

# Punkt 1: Aussteller gruppieren
gruppen = defaultdict(list)
for sha, f in fb.items():
    gruppen[merkmale.norm(name_richtig(f))].append((name_richtig(f), (f.get("kategorie") or {}).get("korrekt")))
mehrfach = {k: v for k, v in gruppen.items() if k and len(v) >= 2}
print("Aussteller insgesamt:", len([k for k in gruppen if k]), " davon mehrfach:", len(mehrfach))
for k, v in sorted(mehrfach.items(), key=lambda x: -len(x[1])):
    print(f"  {len(v)}x  {v[0][0]!r:40}  {Counter(c for _, c in v)}")

# Punkt 3: falsche Belegarten
kat_falsch = [(sha, f) for sha, f in fb.items() if (f.get("kategorie") or {}).get("richtig") is False]
print("Belegart von KI falsch:", len(kat_falsch))
for sha, f in kat_falsch:
    print("  ", name_richtig(f), (f["kategorie"].get("modell"), "->", f["kategorie"].get("korrekt")))

# Nebenbefund: wie oft „Belegart unsicher“?
unsicher = [sha for sha, a in analysen.items()
            if any(str(g).startswith("Belegart unsicher") for g in a.get("gruende") or [])]
print("Analysen mit Grund 'Belegart unsicher':", len(unsicher))

# Punkt 2: Leave-one-out – aus den ANDEREN Prüfungen lernen, dann mit der KI-Lesung nachschlagen
ergebnis = Counter()
for sha, f in fb.items():
    andere = [g for s, g in fb.items() if s != sha]
    merkmale.registrieren([], merkmale.aus_bewertungen(andere))
    a = (analysen.get(sha) or {}).get("analyse") or (f.get("analyse") or {})
    ki_name = a.get("restaurant_name")
    ki_kat = (f.get("kategorie") or {}).get("modell")
    richtig = (f.get("kategorie") or {}).get("korrekt")
    t = merkmale.nachschlagen(ki_name)
    if not t:
        ergebnis["unbekannt"] += 1
        continue
    if merkmale.gruppe(t["kategorie"]) == merkmale.gruppe(ki_kat):
        ergebnis["bestätigt, KI richtig" if ki_kat == richtig else "bestätigt, KI FALSCH"] += 1
    else:
        ergebnis["Widerspruch, Fehler gefangen" if ki_kat != richtig else "Widerspruch, Fehlalarm"] += 1
print(dict(ergebnis))
```

### kat_zeit.py (Punkt 3, „gab es die Kategorie schon?“)

```python
import sys; sys.path.insert(0, r"c:\Users\phili\beleg-poc")
import storage

erst = {}  # Kategorie -> frühester Zeitpunkt = angelegt
for v in sorted(storage.kategorien_laden(), key=lambda e: e.get("zeitpunkt") or ""):
    erst.setdefault(v.get("schluessel") or v.get("key"), v.get("zeitpunkt"))
print("Kategorie angelegt:", erst)

for f in storage.feedback_laden():
    k = f.get("kategorie") or {}
    if k.get("richtig") is False:
        print(f.get("zeitpunkt"), (f.get("felder") or {}).get("restaurant_name", {}).get("korrekt"),
              k.get("modell"), "->", k.get("korrekt"))
```
