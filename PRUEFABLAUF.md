# Prüfablauf: Wie ein Beleg gelesen, gerechnet und geprüft wird

Dieses Dokument beschreibt Schritt für Schritt, was mit einem hochgeladenen Beleg passiert, wo gerechnet
wird und wann ein Beleg zur Nachfrage an einen Menschen geht. Grundregel aus dem Leitfaden der
Buchhaltung: **Bei fehlenden oder unklaren Angaben nie raten.**

Kurzfassung:

1. Die KI **liest nur ab**. Sie rechnet nichts.
2. Der Beleg wird **zweimal gelesen**, beide Lesungen werden verglichen.
3. **Alle Rechnungen macht der Code**, auf den Cent genau.
4. Der Code **prüft gegen**: Passen die Zahlen auf dem Beleg zueinander?
5. Bei jedem Zweifel liest ein **größeres Modell** nach. Bleibt der Zweifel, geht der Beleg zur **Nachfrage**.

---

## 1. Upload und Bildaufbereitung

Datei: `extraction.py` (`dateien_zu_bildern`)

- Erlaubt: JPG, PNG, PDF. Bei mehreren Dateien fragt die App, wie sie gelesen werden sollen:
  - **Stapel** (Standard): Jede Datei ist ein eigener Beleg. Bis zu 30 Belege, 3 gleichzeitig, jeder mit
    dem vollen Ablauf. Ergebnis: Übersicht (stimmig / Nachfrage / Fehler, farbig), CSV-Download,
    die Analyse jedes Belegs im Detail ansehbar. **Jeder** analysierte Beleg wird abgelegt (Original +
    Ergebnis in `analysen/`) und erscheint im Tab „Belege“.
  - **Ein Beleg**: Alle Dateien gehören zusammen, z. B. Rechnung + EC-Beleg oder mehrere Fotos einer
    langen Rechnung.
- Während der Analyse zeigt der Knopf nur einen Spinner und die anderen Tabs sind gesperrt: Streamlit startet
  das Skript bei jeder Eingabe neu, ein Klick in einem anderen Tab würde die Analyse abbrechen.
- PDFs werden **vollständig** gelesen, bis 20 Seiten insgesamt. Mehr Seiten → Nachfrage.
- Fotos werden automatisch gedreht (Handy-Ausrichtung) und auf höchstens 2000 Pixel verkleinert
  (ab 6 Seiten 1600 Pixel). PDF-Seiten werden mit 150 dpi in Bilder umgewandelt.

## 2. Ablesen durch die KI (doppelt)

Dateien: `pipeline.py` (`beleg_lesen`), `prompts.py`

Der Beleg wird **zweimal gleichzeitig** gelesen, mit dem Modell `qwen3-vl-30b-a3b`:

| Lesung | Bild |
|---|---|
| 1 | Original |
| 2 | Graustufen mit verstärktem Kontrast und leicht geschärft (`kontrast_variante`) |

Die zweite Lesung bekommt absichtlich ein etwas anderes Bild. So sind Lesefehler der beiden Durchläufe
voneinander unabhängiger. Ein „3“ statt „8“ passiert dann selten zweimal gleich.

**Was die KI abliest**, genau wie gedruckt, ohne zu rechnen:

- Belegart (Bewirtung, Tankbeleg, Übernachtung, Sonstiges, Unlesbar) und ob sie dabei unsicher ist
- Belegnummer, Aussteller, Adresse, Datum, Uhrzeit
- **Gesamtbetrag der Rechnung** (`brutto`): die Zeile „Summe“, „Total“, „Gesamtbetrag“, **vor** einem
  Trinkgeld. Überträge und Zwischensummen sind ausdrücklich ausgeschlossen.
- **EC-/Kartenbetrag** (`ec_betrag`): der tatsächlich gezahlte Betrag
- **MwSt.-Aufstellung** (`steuerzeilen`): eine Zeile pro Steuersatz mit Satz, Netto, MwSt. und Brutto,
  so wie gedruckt
- **Trinkgeld**: nur, wenn es auf dem Beleg steht. Nie aus einer Differenz berechnet.
- Ausland ja/nein und ob der EC-Beleg zur Rechnung passt (Datum, Uhrzeit, Adresse, Name)
- **Konto** (SKR04), nur wenn die Kategorie Konto-Ausnahmen hat: Standardkonto oder die zutreffende Ausnahme,
  bei Hinweisen ohne Gewissheit `konto_unsicher` + Begründung. Andere Konten als die der Kategorie ersetzt der
  Code durch das Standardkonto; ohne Ausnahmen setzt der Code immer das Standardkonto.

Die KI bildet **keine Summen und keine Differenzen**. Das war die Ursache der ersten Fehler: Beim
Domhof-Beleg hatte sie die MwSt. falsch addiert (11,40 statt 11,35 €) und daraus einen falschen
Gesamtbetrag gebaut.

## 3. Rechnen im Code (cent-genau)

Datei: `beleg_schema.py` (`summe`, `differenz`, `mwst_aus_netto`, `mwst_aus_brutto`, `BelegAnalyse._ableiten`)

Alle Beträge werden als **Dezimalzahlen** gerechnet, nicht als Computer-Fließkommazahlen. Gerundet wird
kaufmännisch auf den Cent. So entstehen keine Rundungsfehler wie 0,1 + 0,2 = 0,30000000000000004.

| Wert | Formel |
|---|---|
| MwSt. gesamt | Summe der MwSt. aller Steuerzeilen |
| Netto gesamt | Summe der Netto-Beträge aller Steuerzeilen (fehlt Netto: Brutto − MwSt. der Zeile) |
| Trinkgeld | EC-Betrag − Rechnungsbetrag (nur wenn größer als 0) |
| Gesamtbetrag inkl. Trinkgeld | EC-Betrag, sonst Rechnungsbetrag + aufgedrucktes Trinkgeld |
| MwSt. aus Netto | Netto × Satz / 100, z. B. 23,45 × 19 % = 4,46 |
| MwSt. aus Brutto | Brutto × Satz / (100 + Satz), z. B. 20,00 × 19/119 = 3,19 |

### Typische Ablesefehler, die der Code selbst auflöst

Datei: `beleg_schema.py` (`_summen_abgleichen`)

Zwei Fehler kamen bei den Beispielbelegen mehrfach vor. Der Code löst sie auf, **aber nur, wenn das
Ergebnis danach auf den Cent zum gedruckten Gesamtbetrag passt**. Sonst bleibt alles, wie es abgelesen
wurde, und die Rechenprüfung schlägt an (→ Nachfrage). Jede Umdeutung wird in der App angezeigt
(„Vom Code umgedeutet“) und gespeichert.

**a) Brutto-Spalte als Netto gelesen.** Kassenbons drucken pro Steuersatz mal Netto, mal Brutto.

> Abgelesen: 19 %, „Netto“ 20,00 €, MwSt. 3,19 €.
> Als Netto passt das nicht: 20,00 × 19 % = 3,80 €.
> Als Brutto passt es: 20,00 × 19/119 = 3,19 €. → Netto ist 16,81 €.
> Übernommen, weil alle Zeilen danach zusammen genau den Gesamtbetrag 26,50 € ergeben.

**b) Gesamtbetrag inklusive Trinkgeld gelesen.**

> Beleg: „Summe 66,80“, „Trinkgeld 3,20“, „Kreditkarte 70,00“. Abgelesen als Gesamtbetrag: 70,00 €.
> Steuerzeilen: 52,70 + 14,10 = 66,80 €. Plus aufgedrucktes Trinkgeld 3,20 € = 70,00 €.
> → Rechnungsbetrag ist 66,80 €, Trinkgeld 3,20 €.
> Ohne aufgedrucktes Trinkgeld wird **nicht** geraten. Dann geht der Beleg zur Nachfrage.

## 4. Rechenprüfungen (Gegenprobe)

Datei: `checks.py` (`pruefen`)

Ein falsch gelesener Betrag passt fast nie zu den anderen Zahlen auf dem Beleg. Genau das wird geprüft:

| Prüfung | Erlaubte Abweichung | Fängt ab |
|---|---|---|
| Summe der Steuerzeilen = Gesamtbetrag | 2 Cent | falsch gelesener Gesamtbetrag, Übertrag/Zwischensumme statt Summe, vergessene Zeile |
| MwSt. jeder Zeile = Netto × Satz | 3 Cent | falsch gelesene Ziffer in Netto oder MwSt. |
| Netto + MwSt. = Brutto je Zeile | 2 Cent | falsch gelesene Ziffer |
| Jeder Steuersatz nur einmal | – | doppelt oder erfunden gelesene Zeile |
| EC-Betrag ≥ Rechnung | 2 Cent | falscher EC-Beleg, Teilzahlung |
| Trinkgeld ≤ 30 % der Rechnung | – | EC-Beleg gehört zu einer anderen Rechnung |
| Datum nicht in der Zukunft | – | falsch gelesenes Datum |

**Warum ein paar Cent Toleranz?** Viele Kassen runden die MwSt. pro Position und nicht auf die Summe.
Dadurch weicht die Summe der Steuern um 1 bis 2 Cent vom „idealen“ Wert ab, obwohl der Beleg korrekt ist.
Alles über dieser Toleranz gilt als Ablesefehler. Die Toleranzen stehen an einer Stelle:
`TOLERANZ_SUMME` und `TOLERANZ_ZEILE` in `beleg_schema.py`.

## 5. Vergleich der beiden Lesungen

Datei: `checks.py` (`abweichungen`)

Verglichen werden: Belegart, Belegnummer, Aussteller, Datum, Gesamtbetrag, EC-Betrag und die
MwSt.-Aufstellung. Groß-/Kleinschreibung, Leer- und Satzzeichen zählen nicht. Beim Namen gilt
„Aral“ = „ARAL Tankstelle Speyer“ (der eine Name ist im anderen enthalten).

## 6. Schiedsrichter: größeres Modell bei Zweifel

Datei: `pipeline.py`

Der Schiedsrichter liest, wenn

- die beiden Lesungen in mindestens einem Feld abweichen, **oder**
- eine Prüfung fehlschlägt bzw. ein anderer Nachfragegrund vorliegt.

**Ausnahme – rein fachliche Gründe** (`checks.nur_fachliche_gruende`): Stimmen beide Lesungen überein und
lassen sich **alle** Nachfragegründe durch genaueres Lesen nicht ändern, liest der Schiedsrichter nicht –
das spart Zeit und Kosten. Die Nachfrage an den Menschen bleibt. Rein fachlich sind: Auslandsbeleg, nur
EC-Beleg (Rechnung fehlt), ungewöhnlicher Steuersatz (beide Lesungen sehen denselben Satz), Konto unsicher.
Alles andere –
Rechenprüfung, unsichere oder unbekannte Belegart, fehlende Pflichtangaben, EC passt nicht, unlesbar, kein
Steuersatz/Datum/Betrag – geht im Zweifel weiter an den Schiedsrichter.

Er liest in **höherer Auflösung** (2800 Pixel, PDFs mit 220 dpi), damit kleine Kassenbon-Schrift besser
lesbar ist. **Sein Ergebnis gilt.** Ein abweichendes Feld gilt als geklärt, wenn der Schiedsrichter einer
der beiden ersten Lesungen zustimmt. Danach laufen alle Prüfungen erneut.

| Umgebung | Schiedsrichter |
|---|---|
| Jetzt (Cloud, OpenRouter) | `qwen3-vl-235b-a22b` |
| Später lokal (RTX 3090, 24 GB) | dasselbe 30B-Modell in höherer Auflösung (`SCHIEDSRICHTER_MODELL` setzen); das 235B-Modell passt nicht in 24 GB, und auf einer Karte ist immer nur ein Modell geladen |

## 7. Wann ein Beleg zur Nachfrage geht

Datei: `checks.py` (`nachfragen_gruende`)

Jeder Beleg wird sofort abgelegt (`analysen/`, Original in `belege/`); die Nachfragegründe stehen mit
dabei, im Tab „Belege“ erscheint er unter „Nachfragen offen“. (Ältere Nachfragen liegen in `nachfragen/`.)
Gründe:

- unlesbar
- Belegart unsicher (mit Begründung der KI) oder keiner Kategorie zuzuordnen
- nur EC-Beleg, keine Rechnung
- **Auslandsbeleg** (abweichende Handhabe laut Buchhaltung)
- **Konto unsicher** (Beleg deutet auf eine Konto-Ausnahme der Kategorie hin, aber nicht sicher)
- EC-Beleg passt nicht zur Rechnung (Datum, Uhrzeit, Adresse, Name)
- kein Steuersatz ausgewiesen, oder ein anderer als 7 % / 19 %
- Gesamtbetrag oder Datum fehlt
- eine Rechenprüfung fehlgeschlagen (nach den Umdeutungen aus Abschnitt 3)
- die beiden Lesungen weichen ab und auch der Schiedsrichter klärt es nicht
- mehr als 20 Seiten
- **kein passender Kalendertermin** zu einer Bewirtung oder Übernachtung (siehe Abschnitt 7a), oder der
  Kalender ist nicht erreichbar

## 7a. Abgleich mit dem Firmenkalender

Datei: `kalender.py` (Regeln), `storage.py` (`kalender_abgleichen`)

Zu jeder **Bewirtung** und **Übernachtung** muss es einen passenden Termin im Google-Kalender der Firma geben.

| Belegart | passend, wenn … |
|---|---|
| Bewirtung | ein Termin am Belegdatum zeitlich zur Zahlung passt (beginnt höchstens 5 Std. vorher, endet frühestens 1 Std. vorher) **oder** Restaurantname bzw. Stadt in Titel, Ort oder Beschreibung steht |
| Übernachtung | ein Termin rund um das Rechnungsdatum (bis 1 Tag davor) Hotel oder Stadt nennt, **oder** genau eine mehrtägige Reise über das Datum läuft |

- Gefunden: Die App zeigt den Termin und schlägt dessen **Teilnehmer** als „bewirtete Personen“ vor.
- Nicht gefunden: **Nachfrage**, mit den Terminen im Zeitraum als Hilfe („vielleicht ist einer davon gemeint“).
- Noch nicht eingerichtet: nur ein Hinweis, keine Nachfrage.

Einrichtung: In der Seitenleiste **„Kalender verbinden“** – mit dem Konto anmelden, das die Termine sieht
(z. B. Annika), „Kalender ansehen“ erlauben und auswählen, welche Kalender gelten (mehrere möglich; die App sucht
in allen). Unter „Kalender: verbunden“ lässt sich die Auswahl ändern, neu verbinden oder trennen.
Alter Weg, gilt nur ohne Verbindung in der App: `kalender_id` unter `[kalender]` in den Secrets, Zugriff über den
Drive-Zugang oder `python drive_token_holen.py --kalender`.

## 8. Belege prüfen und korrigieren (Tab „Belege“)

Datei: `App.py` (`zeige_belege`, `_alle_belege`, `_beleg_formular`), Ablage `storage.py`
(`analyse_speichern`, `feedback_speichern`)

Alle analysierten Belege an einer Stelle – auch solche, die schon als richtig abgehakt sind. Gerade jetzt, wo
geprüft wird, ob die KI richtig einordnet, soll man alles durchsehen und jederzeit korrigieren können.

**Woher die Belege kommen** (`_alle_belege`, pro Datei-Hash zusammengeführt): jüngste Analyse (`analysen/`,
neu) bzw. Nachfrage (`nachfragen/`, ältere Einträge), jüngste Prüfung (`feedback/`) und – nur noch lesend –
Entscheidungen der ersten Version (`entscheidungen/`).

**Status je Beleg**: *Nachfrage offen* (KI hat nachgefragt, noch niemand geprüft) · *Noch nicht geprüft* ·
*Geprüft – alles richtig* · *Geprüft – korrigiert* · *Erledigt (ohne Bewertung)* (alte Entscheidung ohne
Feldprüfung).

**Suche** (ganz oben): Suchfeld über Dateiname, Belegnummer, Aussteller, Adresse, Belegart, Datum und Kommentar
(mehrere Wörter: alle müssen vorkommen), Auswahl der Belegart und Zeitraum nach Belegdatum. Bei geprüften
Belegen zählen die korrigierten Werte. „Filter zurücksetzen“ leert alles.

**Filter** (oben, gut sichtbar): Nachfragen offen · Ungeprüft · Korrigiert · Mit Kommentar ·
Alle. „Ungeprüft“ sind nur Belege ohne Nachfrage (KI war sicher, noch niemand hat geprüft) – beide Filter
überschneiden sich nicht. Liegt unter „Nachfragen offen“ oder „Ungeprüft“ etwas, steht die Zahl als farbige Plakette daneben
(orange bzw. grau-blau), sonst in Klammern. Beim Öffnen steht er dort, wo es etwas zu tun gibt. Der Tab zeigt die Zahl offener Nachfragen als Plakette („3 offen“).

**Ansicht**: Auswahlliste mit Vor/Zurück-Pfeilen. Oben die Gründe der KI (falls nachgefragt), links das
Original groß und so hoch wie das Formular daneben (mehrere Seiten: unten ‹ Seite x von n › und
Mini-Vorschauen zum Springen), rechts:

- noch nicht geprüft → gleich das Formular: „Stimmt die Belegart …? Ja/Nein“ (ohne Vorauswahl), Felder mit
  der KI-Lesung, Begründung. Bei Nachfragen ist die Begründung Pflicht (Knopf „Korrigieren“), sonst nur, wenn
  man etwas ändert (Knopf „Prüfung speichern“). Danach springt die Ansicht zum nächsten Beleg.
- geprüft → Belegart richtig/korrigiert und Tabelle „KI hat gelesen / Richtig ist“ (grün = stimmte,
  rot = korrigiert), wer wann geprüft hat, Kommentar. „Korrigieren“ öffnet das Formular mit den bisher
  richtigen Werten; „Abbrechen“ schließt es wieder. Begründung Pflicht.

Nach dem Speichern steht oben die Gegenüberstellung der gerade gespeicherten Prüfung.

**Gespeichert** wird jede Prüfung als **neuer** Feedback-Eintrag (nur anhängen, Stufe 1 des Leitfadens:
Annika prüft und dokumentiert jede Korrektur): Person, Zeitpunkt, Belegart und jedes Feld KI/richtig,
Begründung, Nachfragegründe der KI, Quelle (`nachfrage` / `pruefung`). Bei einer Korrektur zusätzlich
`korrektur_von` und `kommentar_vorher`. Es zählt immer die jüngste Prüfung; verglichen wird immer mit der
KI-Lesung. So fließt jede Prüfung in die Auswertung und in „Aus Korrekturen lernen“ ein.

## 9. Kategorien (Tab „Kategorien“) und wie die KI daraus lernt

Dateien: `kategorien.py`, `prompts.py` (`system_prompt`, `prompt_version`), `App.py` (`zeige_kategorien`)

- **Anlegen, bearbeiten, löschen** in der App. Standard-Kategorien (Bewirtung, Tankbeleg, Übernachtung, …)
  sind im Code verankert: Ihre Beschreibung lässt sich ergänzen, löschen kann man sie nicht.
- **Beschreibung als Freitext**, so wie man es einem neuen Kollegen erklären würde.
- **KI-Assistent** (Schaltfläche, großes Modell): Er übersetzt den Freitext in klare Regeln
  (Erkennungsmerkmale, Abgrenzung, Pflichtangaben, wann nachfragen). Was unklar ist oder sich mit einer
  anderen Kategorie überschneidet, stellt er als **Rückfrage an die Buchhaltung**, statt zu raten. Sein
  Ergebnis ist nur ein Vorschlag. Erst „Speichern“ übernimmt ihn.
- **Status**: „Entwurf“ wird gespeichert, aber noch nicht verwendet. „Aktiv“ fließt ab sofort in jede
  Analyse ein. Entwürfe erscheinen in der Belegart-Auswahl im Tab „Belege“ als „(Entwurf)“,
  damit eine neu angelegte Kategorie sofort auswählbar ist – der KI-Prompt und die Prüfung ihrer Antworten
  nutzen aber nur aktive Kategorien.
- **Jede Änderung ist eine neue Version** (`kategorien/`) mit Person und Zeitpunkt. Löschen ist ebenfalls
  nur eine neue Version mit Status „gelöscht“, der Verlauf bleibt erhalten.
- **Lesbare Kopie im Drive**: Pro Kategorie ein Google-Doc „Kategorie-Beschreibung (aus der App)“ in
  `Anlage KI Assistent/<Kategorie>/`, also dort, wo die Buchhaltung ihre Unterlagen bisher ablegt.
- **Pflichtangaben**: Die KI prüft bei der gewählten Kategorie, ob die genannten Pflichtangaben auf dem
  Beleg stehen (`fehlende_pflichtangaben`). Fehlt eine, geht der Beleg zur Nachfrage.

**„Lernen“ heißt hier: Der Prompt wird angepasst, das Modell wird nicht nachtrainiert.** Die aktiven
Kategorien mit allen Regeln stehen bei jeder Analyse in den Anweisungen an die KI. Die Prompt-Version
bekommt einen Fingerabdruck des Kategorie-Wissens (z. B. `2026-11-17.5+kda009b`). So zeigt die
Auswertung, ob eine geänderte Beschreibung die Trefferquote verbessert oder verschlechtert. Ein echtes
Nachtrainieren des Modells lohnt sich erst mit einigen hundert geprüften Belegen. Diese sammeln
die Prüfungen im Tab „Belege“ gerade.

### Probelauf vor dem Speichern („Hilft meine Änderung?“)

Datei: `testlauf.py`, `App.py` (`_zeige_testlauf`)

Im Tab „Kategorien“ öffnet der Button **„Testen“** (unter dem Formular einer Kategorie) ein Fenster mit dem **Probelauf mit Beispielbelegen**. Kategorien wählt man ganz oben in der Auswahlliste; der Button „Neue Kategorie“ daneben legt eine neue an. Die Beispielbelege
liegen im passenden Ordner unter `Anlage KI Assistent/` (z. B. „Bewirtungsbeleg Deutschland“). Neue
Beispiele lassen sich direkt in der App hochladen.

Jeder Beispielbeleg wird zweimal komplett analysiert (doppelt lesen, Prüfungen, ggf. Schiedsrichter):

- **vorher**: mit dem gespeicherten Kategorie-Wissen
- **nachher**: mit dem Stand im Formular, auch wenn er noch nicht gespeichert ist

Ergebnis pro Variante („Bisherige Beschreibung“ / „Neue Beschreibung“): Wie viele Belege wurden als diese
Kategorie erkannt? (Bewirtungs-Unterarten zählen gegenseitig.) Wie viele müssten nachgefragt werden? Dazu
ein **Fazit in einem Satz** („Die Änderung hilft“ / „Eher nicht speichern“ / „Kein Unterschied“; richtig
erkennen zählt mehr als wenige Rückfragen) und eine Tabelle pro Beleg: grün = sicher, rot = Nachfrage,
grau = Datei nicht lesbar.
Gespeichert wird beim Testlauf **nichts**. Höchstens 15 Belege pro Lauf, 4 parallel.

## 10. Prüfung und Messung

Datei: `App.py`

Geprüft wird **nur im Tab „Belege“** (Abschnitt 8). Der Tab „Belege hochladen“ zeigt nur das Ergebnis der
Analyse (bei Stapeln die Übersicht, Details je Beleg zum Ansehen) und verweist zum Prüfen auf „Belege“.
Früher gab es dort zusätzlich ein Feedback-Formular; dessen Einträge zählen weiter (Quelle „Feedback direkt
nach der Analyse (frühere Version)“).

Die **Belegart wird ausdrücklich abgefragt**: „Stimmt die Belegart „…“? Ja / Nein“, nichts ist
vorausgewählt; bei „Nein“ wählt man die richtige. Ohne Antwort lässt sich nicht speichern. (Vorher war die
KI-Kategorie vorausgewählt – wer sie nicht umstellte, bestätigte sie, auch wenn im Kommentar das Gegenteil
stand.)

Der Tab **„Auswertung“** (`zeige_auswertung`) zeigt nur Zahlen und Zusammenfassungen – einzelne Belege
sieht man im Tab „Belege“.

**Belege und Nachfragen**: Belege gesamt, davon geprüft, Nachfragen der KI (davon offen) und *unnötige
Nachfragen* (nachgefragt, bei der Prüfung war aber alles richtig – viele davon = Regeln zu streng).

**Erkennungsqualität**: jeder geprüfte Beleg zählt **einmal** (jüngste Prüfung pro Datei-Hash):

| Kennzahl | Bedeutung |
|---|---|
| Belegart richtig | KI-Kategorie = vom Menschen bestätigte Kategorie |
| Alle Felder richtig | kein Feld musste korrigiert werden (ein Feld gilt als richtig, wenn es beim Bewerten nicht geändert wurde) |
| Komplett richtig | beides |

Dazu Trefferquote pro Feld und pro Belegart, die Verwechslungen und ein Hinweis, wenn eine falsche
Belegart eine **neu angelegte Kategorie** betrifft (die KI kannte sie bei der Analyse evtl. noch nicht).
Filter nach Prompt-Version und Modell sind aufklappbar.

### Lesequalität (Tab „Auswertung“)

Datei: `lesequalitaet.py`, Anzeige `App.py` (`_zeige_lesequalitaet`)

Jede Analyse speichert ihre Lesungen (Lesung 1 Original, Lesung 2 Kontrast, ggf. Schiedsrichter). Für jeden
geprüften Beleg wird jede Lesung Feld für Feld mit dem richtigen Wert verglichen – genauso wie im
Prüfformular (Beträge auf den Cent, Text ohne Groß-/Kleinschreibung, Steuersätze als Menge). Angezeigt
werden:

- **Tabelle** je Feld, zusammengefasst je Feldart (Textfelder, Beträge und Steuersätze, Datum und Uhrzeit)
  und für die Belegart: Trefferquote jeder Lesung und des Endergebnisses; unter 100 % hell, unter 90 % kräftiger
  hinterlegt.
- **Zähler**: Schiedsrichter eingesetzt / rettete (beide ersten falsch, er richtig) / verschlechterte (eine
  der ersten richtig, Endergebnis falsch); „Nur Original richtig“ bzw. „Nur Kontrast richtig“.
- **Endergebnis je Belegtyp** (Foto/PDF, ein-/mehrseitig).
- Ab 10 Belegen **Hinweise**, z. B. schwächste Feldart, Schiedsrichter ohne Nutzen, Kontrast-Lesung ohne Nutzen.

Kein Modellaufruf. Grundlage für Entscheidungen wie Bildaufbereitung verbessern, eine Lesung weglassen oder
ein spezielles Texterkennungs-Modell (OCR) als zusätzliche Gegenprobe für bestimmte Felder einsetzen.

### Aus Korrekturen lernen (Tab „Auswertung“)

Datei: `App.py` (`_aus_korrekturen_lernen`, `_lernfaelle`), Prompt `kategorien.py` (`LERN_PROMPT`)

Erst sammeln, dann in Runden abarbeiten – der Prompt ändert sich nie automatisch.

1. **Fälle**: alle bewerteten Belege (jüngste Bewertung, Filter beachtet), die korrigiert, kommentiert oder
   nachgefragt wurden – höchstens 60, die neuesten zuerst. Pro Fall gehen an das Modell: Belegart der KI und
   die richtige, geänderte Felder (vorher/nachher), Nachfragegründe der KI, Kommentar/Begründung des Menschen
   und Eckdaten des Belegs laut KI (Aussteller, Ausland, Begründung der Belegart, Hinweise).
2. **„Verbesserungsvorschläge erstellen“** (großes Modell, ein Aufruf). Das Modell ordnet jeden Fall einer
   Ursache zu – *Regel fehlte*, *Unnötige Nachfrage*, *Lesefehler* (auch „Unsicher gelesen“, weil zwei
   Lesungen abwichen), *Bewertung widersprüchlich*, *Unklar* – und schlägt für Regel-Fälle je einen Satz
   vor, der genau ein Feld einer Kategorie ergänzt. Überschneidet sich ein Vorschlag mit einer anderen
   Kategorie, soll es eine Rückfrage stellen statt eines Vorschlags.
3. **Absicherung im Code** (`lern_antwort_pruefen`): nur bestehende Kategorien und erlaubte Felder,
   Fallnummern im gültigen Bereich; ein Vorschlag aus nur einem Fall gilt immer als „Einzelfall“.
4. **„In Kategorie übernehmen“** setzt den Satz als **ungespeicherte Änderung** in das Feld der Kategorie im
   Tab „Kategorien“ (mit Hinweis). Dort prüfen, mit „Testen“ den Probelauf machen und erst dann speichern –
   das erzeugt eine neue Prompt-Version, deren Wirkung die Auswertung vorher/nachher zeigt.
5. Widersprüchliche Bewertungen werden extra genannt, damit man sie im Tab „Belege“ (Ansicht „Mit
   Kommentar“) über „Korrigieren“ richtigstellt. Die Vorschläge selbst werden nicht gespeichert (nur in der laufenden Sitzung).

## Was nicht abgesichert ist

- **Texte** (Belegnummer, Name, Adresse) haben keine Rechen-Gegenprobe. Abgesichert sind sie nur durch das
  Doppelt-Lesen und den Schiedsrichter.
- Liest die KI **zwei zusammenpassende Zahlen gleichzeitig falsch** (z. B. Netto und MwSt. derselben Zeile
  so, dass die Rechnung trotzdem aufgeht), fällt das nur auf, wenn die Gesamtsumme nicht mehr stimmt.
  Das ist sehr unwahrscheinlich, aber möglich.
- Fachliche Fragen (z. B. ob eine Bewirtung steuerlich anerkannt wird) prüft die App nicht.

## Ergebnis mit den 13 Beispielbelegen (Ordner „Bewirtungsbeleg Deutschland“)

| | vorher (17.11.2026, Prompt 2026-11-17.3) | jetzt (Prompt 2026-11-17.4) |
|---|---|---|
| ohne Nachfrage durchgelaufen | 5 | 9 |
| zur Nachfrage | 8 | 4 |

Die 4 verbleibenden Nachfragen: einmal Auslandsbeleg, zweimal Steuersatz 0 %, einmal passt der EC-Beleg
nicht zur Rechnung. Ob diese Einschätzungen der KI stimmen, muss die Buchhaltung bestätigen.
