# Prüfablauf: Wie ein Beleg gelesen, gerechnet und geprüft wird

Was mit einem hochgeladenen Beleg passiert – vom Hochladen bis zur Prüfung durch einen Menschen. Wie das im
Code umgesetzt ist, steht in [docs/TECHNIK.md](docs/TECHNIK.md).

Grundregel der Buchhaltung: **Bei fehlenden oder unklaren Angaben nie raten – nachfragen.**

## Kurzfassung

1. Die KI **liest nur ab**. Sie rechnet nichts.
2. Jeder Beleg wird **zweimal gelesen**, beide Lesungen werden verglichen.
3. **Alle Rechnungen macht der Code**, auf den Cent genau.
4. Der Code **prüft gegen**: Passen die Zahlen auf dem Beleg zueinander?
5. Bei Zweifel liest ein **größeres Modell** („Schiedsrichter“) nach. Bleibt der Zweifel, geht der Beleg als
   **Nachfrage** an einen Menschen.
6. Jede Prüfung durch einen Menschen wird gespeichert – zum Messen und um die Regeln zu verbessern.

```text
Hochladen ─► 2 Lesungen ─► rechnen + prüfen ─┬─► stimmig ──────────────────────┐
                                             └─► Zweifel ─► Schiedsrichter ─────┤
                                                                                ▼
                         Kalenderabgleich ─► ablegen ─► Tab „Belege“: Mensch prüft
```

---

## 1. Hochladen

- JPG, PNG oder PDF. Bei mehreren Dateien fragt die App (ohne Vorauswahl):
  - **Ein Beleg** – alle Dateien gehören zusammen (z. B. Rechnung + EC-Beleg).
  - **Stapel** – jede Datei ist ein eigener Beleg (bis 30, drei gleichzeitig).
- PDFs werden vollständig gelesen, bis 20 Seiten. Mehr Seiten → Nachfrage.
- Fotos werden gedreht und verkleinert (höchstens 2000 Pixel).
- **Jeder** analysierte Beleg wird abgelegt und erscheint im Tab „Belege“.

## 2. Ablesen durch die KI (doppelt)

Der Beleg wird **zweimal gleichzeitig** vom Modell `qwen3-vl-30b` gelesen: einmal das Original, einmal eine
Variante mit stärkerem Kontrast. Durch das etwas andere Bild sind Lesefehler unabhängiger – eine „3“ statt
„8“ passiert selten zweimal gleich.

Die KI liest **genau wie gedruckt** ab:

- Belegart und ob sie dabei unsicher ist
- Belegnummer, Aussteller, Adresse, Datum, Uhrzeit
- Mitarbeiter / Gast (für wen der Beleg ist – nie geraten)
- Gesamtbetrag der Rechnung (vor Trinkgeld), EC-/Kartenbetrag, Trinkgeld (nur wenn aufgedruckt)
- MwSt.-Aufstellung: eine Zeile je Steuersatz mit Netto, MwSt. und Brutto
- Auslandsbeleg ja/nein, passt der EC-Beleg zur Rechnung
- Konto (SKR04) – nur wenn die Kategorie Konto-Ausnahmen hat; sonst setzt der Code das Standardkonto

Die KI bildet **keine Summen und keine Differenzen**. Das war die Ursache der ersten Fehler: Beim
Domhof-Beleg hatte sie die MwSt. falsch addiert (11,40 statt 11,35 €).

## 3. Rechnen im Code (cent-genau)

Gerechnet wird mit exakten Dezimalzahlen und kaufmännisch auf den Cent gerundet.

| Wert | Formel |
|---|---|
| MwSt. gesamt | Summe der MwSt. aller Steuerzeilen |
| Netto gesamt | Summe der Netto-Beträge (fehlt Netto: Brutto − MwSt. der Zeile) |
| Trinkgeld | EC-Betrag − Rechnungsbetrag (nur wenn größer als 0) |
| MwSt. aus Netto | Netto × Satz / 100, z. B. 23,45 × 19 % = 4,46 |
| MwSt. aus Brutto | Brutto × Satz / (100 + Satz), z. B. 20,00 × 19/119 = 3,19 |

**Zwei typische Lesefehler löst der Code selbst** – aber nur, wenn danach alles auf den Cent zum Gesamtbetrag
passt. Sonst bleibt es, wie gelesen, und die Rechenprüfung schlägt an. Jede Umdeutung wird angezeigt
(„Vom Code umgedeutet“).

- **Brutto als Netto gelesen:** Gelesen „Netto 20,00 €, MwSt. 3,19 €“. Als Netto passt das nicht
  (20,00 × 19 % = 3,80), als Brutto schon (20,00 × 19/119 = 3,19) → Netto ist 16,81 €.
- **Gesamtbetrag mit Trinkgeld gelesen:** Gelesen 70,00 €; Steuerzeilen ergeben 66,80 €, aufgedrucktes
  Trinkgeld 3,20 € → Rechnung 66,80 €, Trinkgeld 3,20 €. Ohne aufgedrucktes Trinkgeld wird nicht geraten.

## 4. Rechenprüfungen (Gegenprobe)

Ein falsch gelesener Betrag passt fast nie zu den anderen Zahlen auf dem Beleg:

| Prüfung | Toleranz | Fängt ab |
|---|---|---|
| Summe der Steuerzeilen = Gesamtbetrag | 2 Cent | falscher Gesamtbetrag, Zwischensumme, vergessene Zeile |
| MwSt. jeder Zeile = Netto × Satz | 3 Cent | falsch gelesene Ziffer |
| Netto + MwSt. = Brutto je Zeile | 2 Cent | falsch gelesene Ziffer |
| Jeder Steuersatz nur einmal | – | doppelt gelesene Zeile |
| EC-Betrag ≥ Rechnung | 2 Cent | falscher EC-Beleg, Teilzahlung |
| Trinkgeld ≤ 30 % der Rechnung | – | EC-Beleg gehört zu anderer Rechnung |
| Datum nicht in der Zukunft | – | falsch gelesenes Datum |

Die Toleranz gibt es, weil viele Kassen die MwSt. je Position runden – dann weicht die Summe um 1–2 Cent ab,
obwohl der Beleg stimmt.

## 5. Vergleich der beiden Lesungen

Verglichen werden Belegart, Konto, Belegnummer, Aussteller, Mitarbeiter, Datum, Uhrzeit, Postleitzahl,
Gesamtbetrag, EC-Betrag und die MwSt.-Aufstellung. Kleinigkeiten zählen nicht: Groß-/Kleinschreibung,
„Aral“ = „ARAL Tankstelle Speyer“, „18.30“ = „18:30:12“, „Frankfurt a. M.“ = „Frankfurt am Main“ (von der
Adresse zählt nur die Postleitzahl).

## 6. Schiedsrichter: größeres Modell bei Zweifel

Das größere Modell (`qwen3-vl-235b`) liest in höherer Auflösung nach, wenn

- die beiden Lesungen abweichen, **oder**
- eine Prüfung fehlschlägt bzw. ein anderer Nachfragegrund vorliegt.

**Sein Ergebnis gilt.** Ein abweichendes Feld gilt als geklärt, wenn er einer der beiden ersten Lesungen
zustimmt; sonst „Unsicher gelesen“ → Nachfrage.

**Kein Schiedsrichter** bei rein fachlichen Gründen, die genaueres Lesen nicht ändert: Auslandsbeleg, nur
EC-Beleg, ungewöhnlicher Steuersatz, Konto unsicher. Die Nachfrage bleibt trotzdem.

**Zum Testen abschalten:** Schalter „Schiedsrichter (großes Modell)“ in der Seitenleiste (nur für die eigene
Sitzung). Dann geht jeder Zweifel direkt zur Nachfrage. Die Auswertung kann nach „an / abgeschaltet“ filtern.

## 7. Bekannte Aussteller

Aussteller, die zu einer Belegart gehören (z. B. „DB Fernverkehr“ → Reisekosten). Zwei Quellen:

- **von Hand** im Tab „Kategorien“ (Tabelle „Bekannte Aussteller“) oder per Häkchen „Aussteller … merken“
  beim Prüfen;
- **automatisch** aus geprüften Belegen: mindestens 2-mal geprüft, immer dieselbe Belegart.

Der Code gleicht den gelesenen Namen tolerant ab (Groß/klein, „GmbH“, kleine Lesefehler). Die KI sieht die
Liste nicht – sie steht nicht im Prompt.

| KI wählt … | Folge |
|---|---|
| dieselbe Belegart | Zweifel der KI an der Belegart entfallen |
| eine andere Belegart | Nachfrage |
| „Sonstiger Beleg“, Aussteller **von Hand** eingetragen | Code stellt die Belegart selbst richtig, keine Nachfrage („Belegart vom Programm richtiggestellt“) |

## 8. Abgleich mit dem Firmenkalender

Zu jeder **Bewirtung** und **Übernachtung** sollte es einen Termin im Firmenkalender geben.

| Belegart | passend, wenn … |
|---|---|
| Bewirtung | ein Termin am Belegdatum Restaurant oder Stadt nennt, **oder** zeitlich zur Zahlung passt und nach Essen klingt (Mittagessen, Dinner, Bewirtung …) |
| Übernachtung | ein Termin rund um das Rechnungsdatum Hotel oder Stadt nennt, **oder** genau eine mehrtägige Reise darüber läuft |

Gefunden: Die App zeigt den Termin und schlägt dessen Teilnehmer als bewirtete Personen vor.
Nicht gefunden: Nachfrage, mit den Terminen im Zeitraum als Hilfe. Kalender noch nicht verbunden: nur ein Hinweis.
Verbinden: Seitenleiste → „Kalender: nicht verbunden“ → **„Verbinden“**, Kalender auswählen.

## 9. Wann ein Beleg zur Nachfrage geht

- unlesbar, oder mehr als 20 Seiten
- Belegart unsicher oder keiner Kategorie zuzuordnen (außer ein bekannter Aussteller bestätigt sie)
- bekannter Aussteller, aber andere Belegart
- nur EC-Beleg, keine Rechnung
- Auslandsbeleg
- Konto unsicher
- EC-Beleg passt nicht zur Rechnung
- kein Steuersatz, oder ein anderer als 7 % / 19 %
- Gesamtbetrag oder Datum fehlt, Pflichtangaben der Kategorie fehlen
- eine Rechenprüfung schlägt fehl
- die Lesungen weichen ab und auch der Schiedsrichter klärt es nicht
- kein passender Kalendertermin (Bewirtung, Übernachtung)

## 10. Prüfen und korrigieren (Tab „Belege“)

Alle Belege an einer Stelle, mit Filtern: *Nachfragen offen · Ungeprüft · Korrigiert · Mit Kommentar · Alle*
und einer Suche (Text, Belegart, Zeitraum).

- **Noch nicht geprüft:** links das Original, rechts das Formular. Zuerst „Stimmt die Belegart …? Ja/Nein“
  (ohne Vorauswahl), dann Falsches in den Feldern überschreiben. Begründung ist Pflicht bei Nachfragen und bei
  Änderungen. Danach geht es zum nächsten Beleg.
- **Schon geprüft:** Tabelle „KI hat gelesen / Richtig ist“; „Korrigieren“ öffnet das Formular erneut.
- **Falsch hochgeladen?** „Beleg entfernen“ verschiebt Beleg und Prüfungen in den Drive-Papierkorb
  (30 Tage wiederherstellbar).

Jede Prüfung wird als **neuer Eintrag** gespeichert (nie überschrieben): wer, wann, Belegart und jedes Feld
„KI / richtig“, Begründung. Es zählt immer die jüngste Prüfung.

## 11. Kategorien – und wie die KI daraus „lernt“

**„Lernen“ heißt: Der Prompt wird angepasst, das Modell wird nicht nachtrainiert.** Die aktiven Kategorien
mit ihren Regeln stehen bei jeder Analyse in den Anweisungen an die KI.

- **Anlegen und bearbeiten** im Tab „Kategorien“: Beschreibung als Freitext, Erkennungsmerkmale, Abgrenzung,
  Pflichtangaben, wann nachfragen, SKR04-Konto, bekannte Aussteller.
- **KI-Assistent:** macht aus dem Freitext klare Regeln und stellt Rückfragen statt zu raten – nur als
  Vorschlag.
- **Status:** Nur **aktive** Kategorien kann die KI wählen. Ein **Entwurf** ist gespeichert, aber für die KI
  unsichtbar.
- Jede Änderung ist eine **neue Version**; eine lesbare Kopie liegt als Google-Doc in
  `Anlage KI Assistent/<Kategorie>/`.

### Probelauf: „Hilft meine Änderung?“

Knopf **„Testen“** unter dem Kategorie-Formular. Bis zu 15 Belege werden zweimal analysiert – mit der
gespeicherten und mit der geänderten Beschreibung. Am besten mit **geprüften Belegen dieser Kategorie** (je
etwa zur Hälfte mit und ohne Fehler; ihre Prüfung dient als Musterlösung), alternativ mit Beispielbelegen aus
Drive. Ergebnis: richtig erkannt, Felder richtig gelesen, Nachfragen – und ein Fazit in einem Satz
(„Die Änderung hilft“ / „Eher nicht speichern“ / „Kein Unterschied“). Gespeichert wird dabei nichts.
Noch keine Musterlösungen? Der Knopf „Beispielbelege zum Prüfen in ‚Belege‘ legen“ analysiert die
Beispielbelege einmal normal und legt sie zum Prüfen ab.

### Aus Korrekturen lernen (Tab „Auswertung“)

1. Die App sammelt geprüfte Belege mit Korrektur, Kommentar oder Nachfrage (höchstens 60). Eindeutige
   Lesefehler sortiert sie ohne KI aus; Fälle, deren Kategorie seither geändert wurde, lässt sie weg.
2. Das große Modell ordnet jeden Fall einer Ursache zu (*Regel fehlte*, *unnötige Nachfrage*, *Lesefehler*,
   *Bewertung widersprüchlich*, *unklar*) und schlägt je einen Satz für eine Kategorie vor.
3. **„In Kategorie übernehmen“** setzt den Satz als ungespeicherte Änderung in den Kategorien-Tab. Ein Mensch
   prüft, testet (Probelauf) und speichert.
4. „Wirkung übernommener Vorschläge“ zeigt, ob die Fehler danach weniger wurden.

**Warum mehr Fälle helfen:** Ein einzelner Fehler kann Zufall sein, dieselbe Verwechslung bei mehreren
Belegen ist ein Muster – daraus wird eine allgemeine Regel. Unter 20 Fällen weist die App darauf hin.

## 12. Auswertung (Tab „Auswertung“)

- **Belege und Nachfragen:** wie viele geprüft, wie viele Nachfragen, davon *unnötige* (alles war richtig –
  viele davon = Regeln zu streng).
- **Trefferquote:** Belegart richtig, alle Felder richtig, je Feld und je Belegart, Verwechslungen. Filterbar
  nach Prompt-Version, Modell und Schiedsrichter.
- **Lesequalität:** Welche Lesung (Original, Kontrast, Schiedsrichter) lag je Feld richtig?
- **Wann hilft der Schiedsrichter?** Je Auslöser: Hat er den Zweifel aufgelöst, etwas besser oder schlechter
  gelesen? Ohne Wirkung in mindestens 5 Fällen → Kandidat, ihn dort zu überspringen.

---

## Was nicht abgesichert ist

- **Texte** (Belegnummer, Name, Adresse) haben keine Rechen-Gegenprobe – nur Doppelt-Lesen und Schiedsrichter.
- Liest die KI **zwei zusammenpassende Zahlen gleichzeitig falsch**, fällt das nur auf, wenn die Gesamtsumme
  nicht mehr stimmt. Sehr unwahrscheinlich, aber möglich.
- Fachliche Fragen (z. B. ob eine Bewirtung steuerlich anerkannt wird) prüft die App nicht.

## Anhang: Welche Mathematik steckt im Code?

Kurz: **einfache Mathematik** – Grundrechenarten und Prozentrechnung. Anspruchsvoll ist nur, dass bei Geld
jeder Cent stimmen muss und die gelesenen Werte fehlerhaft sein können. Die „Intelligenz“ (Lesen, Einordnen)
steckt im KI-Modell; der Code macht bewusst nur, was sich exakt und nachprüfbar rechnen lässt.

| Bereich | Was gerechnet wird | Schwierigkeit |
|---|---|---|
| Beträge (Abschnitt 3) | MwSt., Netto, Trinkgeld – Formeln oben | Prozentrechnung |
| Cent-Genauigkeit | exakte Dezimalzahlen statt Kommazahlen (im Computer ist 0,1 + 0,2 = 0,30000000000000004), kaufmännisch runden | Standard-Handwerk, aber wichtig |
| Lesefehler auflösen (Abschnitt 3) | beide Deutungen durchrechnen, nur übernehmen, wenn genau eine passt | etwas Logik |
| Rechenprüfungen (Abschnitt 4) | Vergleiche mit 2–3 Cent Toleranz | Vergleiche |
| Namen vergleichen (Abschnitt 5, 7) | Ähnlichkeit 0–1 aus der Python-Standardbibliothek, ab 0,88 gleich | fertige Bibliothek |
| Auswertung (Abschnitt 12) | Zählen und Prozente, keine Statistik im engeren Sinn | Zählen |
| Technik am Rand | Prüfsummen (Datei wiedererkennen), Verschlüsselung des Kalender-Zugangs | fertige Bibliotheken |
