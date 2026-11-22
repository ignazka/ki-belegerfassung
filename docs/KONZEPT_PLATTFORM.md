# Konzept: Vom PoC zur Plattform für KI-Assistenz im Büro

Stand 2026-11-18 · Entwurf zur Diskussion

## 1. Ausgangslage und Ziel

Der BelegAssistent prüft heute Belege für die Buchhaltung der RE-ALIS GmbH: KI ordnet ein und liest ab, Code rechnet
nach, ein Mensch prüft und korrigiert, jede Korrektur wird gemessen und fließt – nach menschlicher Freigabe – in
die Anweisungen an die KI zurück (Details: [TECHNIK.md](TECHNIK.md)).

**Ziel:** daraus eine **Plattform („Hub“)** machen, auf der mehrere Firmen KI-Assistenten für wiederkehrende
Büroaufgaben betreiben – zuerst **Buchhaltung**, später E-Mail, Kalender, Erinnerungen und weitere
Sekretariatsaufgaben. Jede Aufgabe ist ein **Modul**; alle Module teilen denselben Kern.

**Technik:** TypeScript, React und PostgreSQL statt Python/Streamlit – passend zu den Stärken des Teams und
nötig für Mehrbenutzerbetrieb, Mandantentrennung und eine richtige Oberfläche.

## 2. Was der Kern ist (gilt für jedes Modul)

Der heutige Ablauf ist nicht buchhaltungsspezifisch:

| Schritt | Buchhaltung heute | E-Mail (später) | Kalender (später) |
|---|---|---|---|
| **Eingang** | Beleg hochgeladen | Mail kommt an | Terminanfrage |
| **Einordnen + Ablesen** | Belegart, Beträge | Anliegen, Absender, Frist | Teilnehmer, Zeitraum |
| **Prüfen (Code)** | Rechenprüfungen | Pflichtinfos vorhanden? | Konflikte? |
| **Nachfragen** | unsicher → Mensch | unsicher → Mensch | unsicher → Mensch |
| **Mensch prüft/korrigiert** | Tab „Belege“ | Antwortentwurf freigeben | Vorschlag bestätigen |
| **Aktion** | Entwurf in sevDesk | Antwort senden | Termin eintragen |
| **Lernen** | Kategorien + Korrekturen | Regeln + Korrekturen | Regeln + Korrekturen |

**Grundsätze, die bleiben:**

1. **Mensch im Ablauf:** Die KI schlägt vor, Aktionen nach außen erst nach Freigabe (pro Modul/Regel
   einstellbar, „automatisch ab Sicherheit X“ erst, wenn die Messung es trägt).
2. **Code prüft, was prüfbar ist** – KI liest/versteht, deterministische Regeln rechnen und kontrollieren.
3. **Nur anhängen + jüngste Version gilt:** lückenloses Protokoll, wer wann was entschieden hat.
4. **Lernen = versioniertes Regelwissen**, nicht Nachtrainieren. Jede Änderung bekommt eine Version, wird vor
   dem Aktivieren getestet und in der Auswertung vorher/nachher verglichen.
5. **Messbar:** Trefferquoten, Lesequalität, unnötige Nachfragen – je Modul, Mandant und Version.

## 3. Zielarchitektur

```
 Browser (React, TypeScript)
   │  Eingangskorb · Prüfansicht · Regeln/Kategorien · Auswertung · Einstellungen je Mandant
   ▼
 API (TypeScript, z. B. Next.js Route Handlers oder Fastify + tRPC/REST)
   │  Auth (OIDC: Google/Microsoft) · Mandant aus Sitzung · Validierung (zod)
   ├──► PostgreSQL ── Mandantentrennung per Row-Level Security · pgvector (RAG) · Protokoll
   ├──► Objektspeicher (S3-kompatibel) ── Originaldateien, je Mandant getrennt
   └──► Job-Warteschlange (z. B. pg-boss in Postgres) ── lange Vorgänge asynchron
              │
              ▼
        Worker (TypeScript)                      Worker (Python, optional)
          Modul-Pipelines: lesen, prüfen,          nur wo nötig: lokales OCR-Modell,
          Schiedsrichter, Vorschläge               PDF/Bild-Sonderfälle
              │
              ▼
        Modell-Gateway ── OpenRouter heute, später lokaler Server (z. B. vLLM/Ollama auf RTX 3090)
                          gleiche OpenAI-kompatible Schnittstelle → per Konfiguration umschaltbar
              │
        Anbindungen ── sevDesk · Google/Microsoft (Mail, Kalender) · Drive/SharePoint
```

**Wichtige Unterschiede zu heute:**

- **Asynchron statt „Seite rechnet“:** Analysen laufen als Jobs; die Oberfläche zeigt Fortschritt live
  (Server-Sent Events oder Polling). Kein Sperren von Tabs mehr nötig.
- **Echter Mehrbenutzerbetrieb:** gleichzeitiges Arbeiten, Rollen (Prüfer, Regel-Pfleger, Admin).
- **Modell-Gateway:** eine Stelle für alle KI-Aufrufe – Kosten je Mandant zählen, Modell je Modul wählen,
  später lokal betreiben, Datenschutz-Einstellungen zentral.

## 4. Module

Jedes Modul beschreibt nur, was fachlich anders ist; der Rest kommt aus dem Kern.

```ts
interface Modul<Daten> {
  id: "buchhaltung" | "email" | "kalender" | string;
  /** Welche Arten von Vorgängen es gibt (bei Belegen: Belegarten) – als versioniertes Regelwissen gepflegt */
  arten: ArtDefinition[];
  /** Felder, die abgelesen und vom Menschen geprüft werden (Name, Typ, Vergleichsregel) */
  felder: FeldDefinition[];
  /** Eingang → Rohinhalt (Bilder, Text) */
  aufbereiten(eingang: Eingang): Promise<Inhalt>;
  /** Code-Prüfungen und Nachfragegründe (deterministisch, testbar) */
  pruefen(daten: Daten, art: string): Pruefergebnis;
  /** Aktionen nach Freigabe (z. B. sevDesk-Entwurf) */
  aktionen: AktionDefinition<Daten>[];
}
```

Die Lese-Pipeline (doppelt lesen, vergleichen, Schiedsrichter), das Prüfen durch Menschen, Lernen und Messen
sind **generisch** und arbeiten mit den `felder`- und `arten`-Definitionen.

## 5. Datenmodell (PostgreSQL, Auszug)

Jede Tabelle trägt `mandant_id`; Row-Level Security sorgt dafür, dass eine Firma nur ihre Zeilen sieht.

```sql
-- Stammdaten
mandant(id, name, einstellungen jsonb, erstellt_am)
benutzer(id, mandant_id, email, name, rolle)              -- rolle: pruefer | regeln | admin
modul_aktiv(mandant_id, modul_id, einstellungen jsonb)

-- Regelwissen (heute: kategorien/) – nur anhängen, jüngste Version je schluessel gilt
art_version(id, mandant_id, modul_id, schluessel, name, regeln jsonb, status, version,
            erstellt_von, erstellt_am)
wissens_stand(id, mandant_id, modul_id, hash, prompt_version, erstellt_am)   -- Fingerabdruck für Auswertung

-- Vorgänge (heute: ein Beleg = datei_sha256)
vorgang(id, mandant_id, modul_id, kennung_hash, quelle, titel, status, erstellt_am)
datei(id, mandant_id, vorgang_id, speicher_pfad, mime, sha256, seiten)

-- Analysen (heute: analysen/) – jede Analyse ein Eintrag
analyse(id, mandant_id, vorgang_id, prompt_version, modell, ergebnis jsonb, gruende text[],
        schiedsrichter bool, dauer_ms, kosten_cent, erstellt_am)
lesung(id, analyse_id, variante, modell, ergebnis jsonb, rohantwort text, fehler text, tokens int)

-- Prüfungen (heute: feedback/) – nur anhängen, jüngste je Vorgang gilt
pruefung(id, mandant_id, vorgang_id, analyse_id, quelle, art_ki, art_korrekt,
         begruendung, korrektur_von uuid null, geprueft_von, geprueft_am)
pruefung_feld(pruefung_id, feld, wert_ki jsonb, wert_korrekt jsonb, richtig bool)

-- Lernen
vorschlag_lauf(id, mandant_id, modul_id, erstellt_von, erstellt_am, faelle jsonb, rueckfragen text[])
vorschlag(id, lauf_id, art_schluessel, feld, text, begruendung, sicherheit, status)  -- offen|uebernommen|verworfen
probelauf(id, mandant_id, art_schluessel, vorher_version, nachher_regeln jsonb, ergebnis jsonb, erstellt_am)

-- Aktionen und Protokoll
aktion(id, mandant_id, vorgang_id, typ, status, ziel_referenz, antwort jsonb, freigegeben_von, ausgefuehrt_am)
protokoll(id, mandant_id, benutzer_id, ereignis, objekt_typ, objekt_id, daten jsonb, zeitpunkt)

-- RAG (später): Kontierungsregeln, frühere Buchungen je Lieferant, Firmenwissen
wissen_chunk(id, mandant_id, modul_id, quelle, text, embedding vector(1024), metadaten jsonb)
```

Views wie `pruefung_aktuell` (jüngste Prüfung je Vorgang) ersetzen heutige Funktionen wie `_alle_belege`;
die Auswertung wird zu SQL-Abfragen statt Python-Schleifen. Vorschläge und Probeläufe werden – anders als
heute – gespeichert und sind damit nachvollziehbar.

## 6. Was für andere Firmen zusätzlich nötig ist

Solange nur RE-ALIS die App nutzt, wurde das bewusst weggelassen. Für Kunden ist es Pflicht:

- **Mandantentrennung** (Row-Level Security, getrennte Speicherpfade, Tests dafür).
- **Datenschutz:** Auftragsverarbeitungsvertrag, Verzeichnis der Unterauftragsverarbeiter (Modell-Anbieter!),
  Löschfristen je Mandant, Export und Löschung auf Anfrage, Hosting in der EU.
- **Modell-Anbieter:** nur mit Zusage „keine Speicherung/kein Training“ (heute `data_collection: deny`) – oder
  lokal betriebene Modelle als Verkaufsargument.
- **Protokoll** jeder Freigabe und Aktion; Rollen und Rechte.
- **Abgrenzung Buchhaltung:** Die Plattform bereitet vor, die revisionssichere Ablage (GoBD) bleibt im
  Buchhaltungssystem (sevDesk, DATEV …).
- **Kostenkontrolle:** Modellkosten je Mandant messen, Limits.

## 7. Migration – Schritt für Schritt

Kein Umbau in einem Rutsch: Die heutige App bleibt das **Labor** und sammelt weiter Prüfungen, bis die neue
Version sie ersetzt.

| Phase | Inhalt | Ergebnis |
|---|---|---|
| **0. Labor weiter** (läuft) | Prüfungen sammeln, Verbesserungsrunden, Lesequalität, ggf. OCR-Vergleich | Messwerte, bewährte Regeln, Testdatensatz |
| **1. Fundament** | Repo (TS-Monorepo), Postgres-Schema + RLS, Auth (OIDC), Objektspeicher, Job-Queue, Modell-Gateway, CI | leere, mandantenfähige Plattform |
| **2. Logik portieren** | `beleg_schema` (Decimal → `decimal.js`), `checks`, `pipeline`, `kategorien`, `lesequalitaet` nach TS; **die bestehenden Tests als Vorlage mitportieren** (gleiche Fälle, gleiche Erwartungen) | Kernlogik in TS, nachweislich gleiches Verhalten |
| **3. Modul Buchhaltung** | Eingang/Upload, Prüfansicht (heute Tab „Belege“), Regeln (Kategorien), Probelauf, Auswertung, Vorschläge | Funktionsgleich mit dem Labor |
| **4. Datenübernahme** | Einmal-Skript: Drive-JSON (`analysen/`, `feedback/`, `kategorien/` …) → Tabellen; Dateien → Objektspeicher | RE-ALIS arbeitet in der neuen App weiter, Labor wird abgeschaltet |
| **5. Aktion sevDesk** | Datenmodell auf sevDesk-Voucher abbilden, Entwurf anlegen nach Freigabe | erster echter „Arbeitsschritt“ |
| **6. Zweiter Mandant** | Pilotfirma, Datenschutzpaket aus Abschnitt 6, Onboarding (eigene Regeln, Beispielbelege) | Beweis der Übertragbarkeit |
| **7. Weitere Module** | E-Mail, Kalender, Erinnerungen – auf demselben Kern | Hub |
| **8. Lokale Modelle / RAG** | Modell-Gateway auf lokalen Server; Kontierungsregeln/frühere Buchungen per pgvector | Datenhoheit, bessere Kontierung |

**Abbildung heute → neu**

| Heute (Python) | Neu (TypeScript/Postgres) |
|---|---|
| `App.py` (Streamlit, vier Tabs) | React-Seiten: Eingang, Belege/Prüfung, Regeln, Auswertung |
| `st.session_state`, `_lauf_knopf` | Server-Zustand in Postgres, Jobs + Live-Fortschritt |
| `pipeline.py`, `extraction.py` | Worker „Lesen“ + Modell-Gateway; PDF/Bild mit pdf.js/pdfium bzw. `sharp` |
| `beleg_schema.py`, `checks.py` | `zod`-Schemas + Prüffunktionen, `decimal.js` |
| `kategorien.py`, `prompts.py` | `art_version` + Prompt-Bausteine, Wissens-Hash |
| `storage.py` (Drive-JSON) | Postgres-Tabellen + Objektspeicher |
| `lesequalitaet.py`, Auswertung | SQL-Views + Diagramme |
| `tests/` (pytest, AppTest) | Vitest (Logik), Playwright (Oberfläche) |

## 8. Risiken und offene Fragen

- **Fokus:** Sekretariatsaufgaben (Mail, Kalender) sind ein umkämpfter Markt (Microsoft Copilot, Google
  Gemini). Empfehlung: erst Buchhaltung für mehrere Firmen beweisen (Zahlungsbereitschaft), dann erweitern.
- **Wettbewerb Buchhaltung:** Belegerkennung gibt es in sevDesk, Lexoffice, DATEV, Candis. Unterschied:
  firmeneigene Regeln ohne Entwickler, nachvollziehbare Lernschleife mit Messung, Nachfrage-Logik, lokales Modell.
- **Modellqualität und -kosten** je Beleg: mit dem Labor messen, bevor Preise festgelegt werden.
- **Offene Entscheidungen:** Hosting (eigener Server vs. Cloud in der EU), Next.js oder getrenntes
  Frontend/Backend, Rollenmodell, welche Pilotfirma.
