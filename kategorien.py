"""Kategorien: in der App anlegen, bearbeiten, löschen – und daraus den Prompt bauen.

- Jede Änderung ist eine neue VERSION (nur anhängen, nie überschreiben) -> nachvollziehbar, wer was wann
  geändert hat; Löschen = Version mit Status "geloescht".
- Standard-Kategorien (beleg_schema.STANDARD_KATEGORIEN) sind im Code verankert (Rechenprüfungen,
  Bewirtungslogik). Ihre Beschreibung lässt sich ergänzen, löschen kann man sie nicht.
- Status "entwurf": gespeichert, aber noch NICHT im Prompt. "aktiv": fließt in jede Analyse ein.
- Jede aktive Kategorie wird zusätzlich als lesbares Google-Doc in
  "Anlage KI Assistent/<Name>/" abgelegt (Ordner wie bisher bei der Buchhaltung).
"""

import hashlib
import json
import re
import unicodedata

import skr04
from beleg_schema import STANDARD_KATEGORIEN

# Beschreibungen der Standard-Kategorien, solange niemand sie in der App ergänzt hat
STANDARD_BESCHREIBUNG = {
    "restaurant_beleg": "Vom Restaurant ausgestellte Rechnung/Quittung mit Positionen und MwSt.",
    "restaurant_mit_ec_beleg": "Restaurantrechnung zusammen mit EC-/Kartenbeleg. Differenz = Trinkgeld.",
    "nur_ec_beleg": "Nur Zahlungsnachweis vom Kartenterminal, keine Rechnung.",
    "bewirtungsbeleg_intern": "Von der Firma ausgefülltes Bewirtungsformular mit Anlass und Teilnehmern.",
    "tankbeleg": "Tankstelle mit Kraftstoff (Diesel, Super, AdBlue, Laden; Liter, €/l). Benötigt: Datum, "
                 "Betrag, Steuersatz. Fahrzeug und Mitarbeiter sind nicht nötig.",
    "uebernachtung": "Hotel, Pension, Ferienwohnung mit Übernachtung(en). Mitarbeitername und Reiseanlass "
                     "sind Pflicht; Namen nie raten.",
    "sonstiger_beleg": "Alles, was keiner anderen Kategorie zugeordnet werden kann.",
    "unlesbar": "Nicht lesbar oder kein Beleg.",
}

FELDER = ("beschreibung", "erkennungsmerkmale", "abgrenzung", "pflichtangaben", "nachfragen_wenn")
FELD_LABEL = {
    "beschreibung": "Beschreibung der Buchhaltung (Freitext)",
    "erkennungsmerkmale": "Woran erkennt man die Kategorie?",
    "abgrenzung": "Abgrenzung zu anderen Kategorien",
    "pflichtangaben": "Pflichtangaben auf dem Beleg",
    "nachfragen_wenn": "Wann muss nachgefragt werden?",
}


def schluessel_aus_name(name: str) -> str:
    """'Reisekosten Bahn & Flug' -> 'reisekosten_bahn_flug'"""
    s = unicodedata.normalize("NFKD", name.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
                              .replace("Ä", "Ae").replace("Ö", "Oe").replace("Ü", "Ue").replace("ß", "ss"))
    s = re.sub(r"[^a-z0-9]+", "_", s.encode("ascii", "ignore").decode().lower()).strip("_")
    return s[:40] or "kategorie"


def aktueller_stand(versionen: list[dict]) -> dict[str, dict]:
    """Alle Versionen -> {schluessel: jüngste Version}. Standard-Kategorien sind immer dabei."""
    stand = {
        key: {"schluessel": key, "name": label, "standard": True, "status": "aktiv", "version": 0,
              "beschreibung": STANDARD_BESCHREIBUNG.get(key, "")}
        for key, label in STANDARD_KATEGORIEN.items()
    }
    for v in sorted(versionen, key=lambda v: (v.get("version") or 0, v.get("zeitpunkt") or "")):  # Version zählt, nicht die Uhrzeit (UTC in der Cloud, lokal MEZ)
        key = v.get("schluessel")
        if not key:
            continue
        basis = stand.get(key, {})
        stand[key] = {**basis, **v, "standard": key in STANDARD_KATEGORIEN}
        if key in STANDARD_KATEGORIEN:  # Standard: Name und Status bleiben fest
            stand[key]["name"] = STANDARD_KATEGORIEN[key]
            stand[key]["status"] = "aktiv"
    return stand


def sichtbar(stand: dict[str, dict]) -> dict[str, dict]:
    return {k: v for k, v in stand.items() if v.get("status") != "geloescht"}


def aktiv(stand: dict[str, dict]) -> dict[str, dict]:
    return {k: v for k, v in stand.items() if v.get("status") == "aktiv"}


def labels(stand: dict[str, dict]) -> dict[str, str]:
    """{schluessel: Name} der aktiven Kategorien – für die Validierung der KI-Antworten."""
    return {k: v["name"] for k, v in aktiv(stand).items()}


def auswahl(stand: dict[str, dict]) -> dict[str, str]:
    """{schluessel: Anzeigename} für Auswahllisten von Menschen – inklusive Entwürfe.

    Anders als labels() (nur aktive Kategorien, damit die KI keine Entwürfe ausgibt) dürfen Menschen
    eine gerade angelegte Kategorie auch schon als Entwurf auswählen. Entwürfe werden gekennzeichnet,
    gelöschte Kategorien erscheinen nicht.
    """
    return {k: v["name"] + ("" if v.get("status") == "aktiv" else " (Entwurf)")
            for k, v in sichtbar(stand).items()}


def _als_text(wert) -> str:
    if isinstance(wert, list):
        return "; ".join(str(x) for x in wert if str(x).strip())
    return str(wert or "").strip()


def konto_ausnahmen(k: dict) -> list[dict]:
    """Gültige Konto-Ausnahmen der Kategorie: [{"wenn", "konto", "bezeichnung"}] (unvollständige weglassen)."""
    ergebnis = []
    for a in k.get("konto_ausnahmen") or []:
        if not isinstance(a, dict):
            continue
        wenn, konto = str(a.get("wenn") or "").strip(), str(a.get("konto") or "").strip()
        if wenn and konto and not skr04.nummer_pruefen(konto):
            ergebnis.append({"wenn": wenn, "konto": konto, "bezeichnung": str(a.get("bezeichnung") or "").strip()})
    return ergebnis


def ausnahmen_aus_tabelle(zeilen: list[dict]) -> tuple[list[dict], str | None]:
    """Zeilen der Ausnahmen-Tabelle im Kategorien-Tab -> (gültige Ausnahmen, Fehlertext oder None).
    Leere Zeilen fallen weg; fehlt die Bezeichnung, kommt sie aus der Vorlage."""
    def text(x):
        return "" if x is None or x != x else str(x).strip()  # x != x: leere Zelle (NaN) aus der Tabelle
    vorlage = dict(reversed(skr04.VORLAGE))  # erste Bezeichnung je Nummer
    ausnahmen, fehler = [], []
    for nr, z in enumerate(zeilen, start=1):
        wenn, konto, bezeichnung = text(z.get("wenn")), text(z.get("konto")), text(z.get("bezeichnung"))
        if not (wenn or konto or bezeichnung):
            continue
        if not wenn:
            fehler.append(f"Zeile {nr}: Bitte die Bedingung („Wenn …“) ausfüllen.")
        elif skr04.nummer_pruefen(konto) or not konto:
            fehler.append(f"Zeile {nr}: Die Kontonummer hat genau vier Ziffern.")
        else:
            ausnahmen.append({"wenn": wenn, "konto": konto, "bezeichnung": bezeichnung or vorlage.get(konto, "")})
    return ausnahmen, (" ".join(["Ausnahmen:"] + fehler) if fehler else None)


def konto_regeln(k: dict) -> str:
    """Konto-Regel für den Prompt – nur bei Ausnahmen (sonst wählt die KI kein Konto, der Code setzt es)."""
    ausnahmen = konto_ausnahmen(k)
    if not ausnahmen:
        return ""
    nummer = (k.get("skr04_konto") or "").strip()
    standard = f'"{nummer}" ({k.get("skr04_bezeichnung") or "ohne Bezeichnung"})' if nummer else "keins"
    regeln = "; ".join(f'"{a["konto"]}" ({a["bezeichnung"] or "ohne Bezeichnung"}), wenn {a["wenn"]}'
                       for a in ausnahmen)
    return f"Standard {standard}. Ausnahmen: {regeln}"


def konten(stand: dict[str, dict]) -> dict[str, dict]:
    """{schluessel: {"standard": "6640" | None, "ausnahmen": ["6664", …]}} der aktiven Kategorien – damit prüft
    beleg_schema, ob die KI ein erlaubtes Konto gewählt hat."""
    return {key: {"standard": (k.get("skr04_konto") or "").strip() or None,
                  "ausnahmen": [a["konto"] for a in konto_ausnahmen(k)]}
            for key, k in aktiv(stand).items()}


def prompt_abschnitt(stand: dict[str, dict]) -> str:
    """Kategorie-Wissen für den System-Prompt (nur aktive Kategorien)."""
    bloecke = []
    for key, k in aktiv(stand).items():
        zeilen = [f'- "{key}": {k["name"]}']
        for feld in FELDER:
            text = _als_text(k.get(feld))
            if text:
                zeilen.append(f"    {FELD_LABEL[feld]}: {text}")
        if konto_regeln(k):
            zeilen.append(f"    Konto (SKR04): {konto_regeln(k)}")
        bloecke.append("\n".join(zeilen))
    return "\n".join(bloecke)


def wissens_hash(stand: dict[str, dict]) -> str:
    """Kurzer Fingerabdruck des Kategorie-Wissens -> Teil der Prompt-Version (Auswertung vorher/nachher).
    Konto-Regeln zählen nur mit, wenn es Ausnahmen gibt (nur dann stehen sie im Prompt)."""
    def wissen(v):
        w = {f: _als_text(v.get(f)) for f in ("name",) + FELDER}
        if konto_regeln(v):
            w["konto"] = konto_regeln(v)
        return w
    roh = json.dumps({k: wissen(v) for k, v in aktiv(stand).items()}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(roh.encode()).hexdigest()[:6]


def konto_text(k: dict) -> str:
    """SKR04-Konto der Kategorie als '6640 · Bewirtungskosten' (leer, wenn keins festgelegt).

    Das Standardkonto allein steht nicht im Prompt (die KI muss nichts entscheiden). Erst Konto-Ausnahmen
    („wenn … → anderes Konto“) gehen in den Prompt, siehe konto_regeln.
    """
    return skr04.als_text(k.get("skr04_konto"), k.get("skr04_bezeichnung"))


def als_dokument(k: dict) -> str:
    """Lesbarer Text für das Google-Doc im Drive-Ordner der Kategorie."""
    teile = [k["name"], "", f"Schlüssel: {k['schluessel']} · Status: {k.get('status')} · "
             f"Version {k.get('version')} · zuletzt geändert von {k.get('bearbeiter') or '–'}",
             f"SKR04-Konto: {konto_text(k) or 'noch nicht festgelegt'}"]
    teile += [f"  Ausnahme: {skr04.als_text(a['konto'], a['bezeichnung'])}, wenn {a['wenn']}"
              for a in konto_ausnahmen(k)]
    aussteller = [m.get("wert") for m in k.get("bekannte_merkmale") or [] if isinstance(m, dict) and m.get("wert")]
    if aussteller:
        teile.append("Bekannte Aussteller: " + "; ".join(aussteller))
    teile.append("")
    for feld in FELDER:
        text = _als_text(k.get(feld))
        if text:
            teile += [FELD_LABEL[feld], text, ""]
    teile.append("Diese Datei wird von der Beleg-App erzeugt. Änderungen bitte in der App vornehmen "
                 "(Tab „Kategorien“), sonst werden sie beim nächsten Speichern überschrieben.")
    return "\n".join(teile)


# ---------------------------------------------------------------------------
# KI-Assistent: Freitext der Buchhaltung -> klare Regeln + Rückfragen
# ---------------------------------------------------------------------------

ASSISTENT_PROMPT = """Du hilfst der Buchhaltung, eine Belegkategorie für eine Beleg-KI präzise zu beschreiben.
Du bekommst den Freitext der Buchhaltung und die übrigen Kategorien. Formuliere daraus klare Regeln.

REGELN
- Nur aus dem Freitext und allgemein bekanntem Wissen über Belege ableiten. Keine Firmenregeln erfinden.
- Was im Freitext unklar oder widersprüchlich ist oder sich mit einer anderen Kategorie überschneidet:
  NICHT entscheiden, sondern als Rückfrage an die Buchhaltung formulieren.
- Rückfragen betreffen die REGEL, nicht einzelne Belege. Gut: "Gehört eine Hotelrechnung zu Reisekosten oder
  zu Übernachtung?" Schlecht: "Ist auf diesem Beleg ein Name lesbar?"
- Pflichtangaben: nur Angaben, die auf dem Beleg selbst stehen müssen (keine Arbeitsschritte wie "Konto").
- Kurz und konkret, Deutsch, Stichpunkte durch "; " getrennt.

Antworte NUR mit JSON:
{"erkennungsmerkmale": "...", "abgrenzung": "...", "pflichtangaben": ["..."], "nachfragen_wenn": "...",
 "rueckfragen": ["..."]}"""


def assistent_nachricht(name: str, freitext: str, andere: dict[str, dict]) -> str:
    uebrige = "\n".join(f"- {k['name']}: {_als_text(k.get('beschreibung'))[:200]}"
                        for k in andere.values())
    return f"Kategorie: {name}\n\nFreitext der Buchhaltung:\n{freitext}\n\nÜbrige Kategorien:\n{uebrige}"


# ---------------------------------------------------------------------------
# Aus Korrekturen lernen: gesammelte Korrekturen -> Vorschläge für das Kategorie-Wissen
# ---------------------------------------------------------------------------

LERN_FELDER = ("erkennungsmerkmale", "abgrenzung", "pflichtangaben", "nachfragen_wenn")
URSACHEN = {
    "regel": "Regel fehlte",
    "nachfrage_zu_streng": "Unnötige Nachfrage",
    "lesefehler": "Lesefehler",
    "bewertung_widerspruechlich": "Bewertung widersprüchlich",
    "unklar": "Unklar",
}

LERN_PROMPT = """Du hilfst, die Anweisungen einer Beleg-KI zu verbessern. Du bekommst das aktuelle
Kategorie-Wissen der KI und Fälle, in denen ein Mensch ihr Ergebnis korrigiert oder kommentiert hat – jeweils
mit den Gründen, aus denen die KI nachgefragt hat, und der Begründung bzw. dem Kommentar des Menschen.

AUFGABE
1. Ordne jeden Fall GENAU EINER Ursache zu:
   - "regel": der KI fehlte Wissen oder eine Regel (z. B. Zimmer-Positionen bedeuten Übernachtung)
   - "nachfrage_zu_streng": die KI hat nachgefragt, obwohl alles stimmte
   - "lesefehler": Zahl oder Text falsch abgelesen – lässt sich nicht durch Regeln beheben. Dazu gehören auch
     Nachfragen mit dem Grund "Unsicher gelesen": Sie entstehen, weil zwei Lesungen voneinander abweichen,
     und lassen sich nicht durch Kategorie-Regeln ändern.
   - "bewertung_widerspruechlich": Kommentar widerspricht der Bewertung (z. B. Belegart als richtig
     bestätigt, aber der Kommentar beschreibt einen Fehler der Belegart)
   - "unklar"
2. Leite aus den Fällen "regel" und "nachfrage_zu_streng" Vorschläge ab, die das Kategorie-Wissen ergänzen.
   - Nur allgemeingültige Regeln – keine Einzelheiten eines Belegs (keine Namen, Beträge, Daten, Orte).
   - Stütze dich nur auf das, was in den Fällen steht ("beleg_laut_ki", Kommentar, Korrekturen). Wenn
     unklar ist, was einen Beleg ausmacht, lieber eine Rückfrage als ein geratener Vorschlag.
     "beleg_laut_ki" zeigt auch, woran die KI gezweifelt hat (belegart_unsicher, fehlende_pflichtangaben,
     Begründungen); fehlende Angaben gab es auf dem Beleg nicht oder sie waren leer.
   - Lieber ein Vorschlag, der mehrere Fälle abdeckt, als viele kleine.
   - Ein Vorschlag ergänzt GENAU EIN Feld GENAU EINER bestehenden Kategorie (Schlüssel aus dem
     Kategorie-Wissen): "erkennungsmerkmale" | "abgrenzung" | "pflichtangaben" | "nachfragen_wenn".
   - "text" ist nur der neue Satz zum Anhängen, nicht das ganze Feld. Nichts wiederholen, was schon dasteht.
   - Unnötige Nachfragen: Regel in "nachfragen_wenn" präzisieren (wann gerade NICHT nachgefragt werden muss).
   - Beruht ein Vorschlag auf nur einem Fall: "sicherheit": "niedrig".
   - Prüfe jeden Vorschlag gegen ALLE anderen Kategorien: Würde er Belege einer anderen Kategorie mit
     erfassen (z. B. "Hotel" bei Reisekosten, obwohl es eine Kategorie Übernachtung gibt), mache KEINEN
     Vorschlag, sondern stelle eine Rückfrage zur Abgrenzung.
3. Erfinde keine Firmenregeln. Was nur die Buchhaltung entscheiden kann, als Rückfrage formulieren.
4. Deutsch, kurz und konkret.

Antworte NUR mit JSON:
{"faelle": [{"nr": 1, "ursache": "regel", "kurz": "ein Satz, was schiefging"}],
 "vorschlaege": [{"kategorie": "<schluessel>", "feld": "erkennungsmerkmale", "text": "...",
                  "begruendung": "...", "faelle": [1, 3], "sicherheit": "hoch|mittel|niedrig"}],
 "rueckfragen": ["..."]}"""


def lern_nachricht(stand: dict[str, dict], faelle: list[dict]) -> str:
    """faelle: bereits aufbereitete, nummerierte Fälle (siehe App._lernfaelle)."""
    return ("KATEGORIE-WISSEN (Schlüssel in Anführungszeichen):\n" + prompt_abschnitt(stand)
            + "\n\nFÄLLE:\n" + json.dumps(faelle, ensure_ascii=False, indent=1))


def lern_antwort_pruefen(antwort: dict, stand: dict[str, dict], anzahl_faelle: int) -> dict:
    """Antwort des Modells absichern: nur bekannte Kategorien/Felder/Ursachen, Fallnummern im Bereich."""
    gueltig = sichtbar(stand)

    def nummern(werte):
        return [n for n in (werte or []) if isinstance(n, int) and 1 <= n <= anzahl_faelle]

    faelle = [{"nr": f["nr"], "ursache": f.get("ursache") if f.get("ursache") in URSACHEN else "unklar",
               "kurz": str(f.get("kurz") or "")}
              for f in antwort.get("faelle") or [] if isinstance(f, dict) and nummern([f.get("nr")])]
    vorschlaege = [{
        "kategorie": v["kategorie"], "feld": v["feld"], "text": str(v["text"]).strip(),
        "begruendung": str(v.get("begruendung") or ""), "faelle": nummern(v.get("faelle")),
        "sicherheit": ("niedrig" if len(nummern(v.get("faelle"))) <= 1 else  # ein Fall ist kein Muster
                       v.get("sicherheit") if v.get("sicherheit") in ("hoch", "mittel", "niedrig") else "mittel"),
    } for v in antwort.get("vorschlaege") or []
        if isinstance(v, dict) and v.get("kategorie") in gueltig and v.get("feld") in LERN_FELDER
        and str(v.get("text") or "").strip()]
    return {"faelle": faelle, "vorschlaege": vorschlaege,
            "rueckfragen": [str(r) for r in antwort.get("rueckfragen") or [] if str(r).strip()]}
