"""Lesequalität: Welche Lesung lag bei geprüften Belegen richtig?

Jede Analyse speichert ihre einzelnen Lesungen (pipeline.py): Lesung 1 vom Original, Lesung 2 von einer
Kontrast-Variante und – bei Zweifel – den Schiedsrichter in hoher Auflösung. Eine Prüfung im Tab „Belege“
liefert den richtigen Wert je Feld. Hier wird beides verglichen – ohne Modellaufruf.

Ziel: sehen, WO falsch gelesen wird (Textfelder, Beträge, Datum; Fotos/PDFs; ein-/mehrseitig) und ob die
zweite Lesung und der Schiedsrichter etwas bringen. Daraus folgen gezielte Verbesserungen (Bildaufbereitung,
Lesungen weglassen, spezielles Texterkennungs-Modell für bestimmte Felder).
"""
from beleg_schema import FEEDBACK_FELDER, BelegAnalyse, anzeige, werte_gleich

VARIANTEN = {  # Name in pipeline.py -> Anzeige
    "original": "Lesung 1 (Original)",
    "kontrast": "Lesung 2 (Kontrast)",
    "hochaufgelöst": "Schiedsrichter",
}
GRUPPEN = {  # Feldart -> Felder
    "Textfelder": ["belegnummer", "restaurant_name", "adresse"],
    "Beträge und Steuersätze": ["netto", "mwst", "brutto", "ec_betrag", "trinkgeld", "steuersaetze"],
    "Datum und Uhrzeit": ["datum", "uhrzeit"],
}
_TYP = {key: typ for key, _label, typ in FEEDBACK_FELDER}


def _gleich(key: str, a, b) -> bool:
    # wie im Prüfformular: beide Seiten als Anzeige-Text vergleichen (normalisiert Beträge, Datum, Sätze, Text)
    return werte_gleich(_TYP[key], anzeige(a), anzeige(b))


def _lesungen_je_variante(lesungen: list[dict]) -> dict[str, BelegAnalyse]:
    """Nur gelungene Lesungen (mit Analyse); bei doppelten Varianten zählt die erste."""
    ergebnis = {}
    for lesung in lesungen or []:
        variante, analyse = lesung.get("variante"), lesung.get("analyse")
        if variante in VARIANTEN and analyse and variante not in ergebnis:
            try:
                ergebnis[variante] = BelegAnalyse.model_validate(analyse)
            except Exception:  # alte/kaputte Einträge überspringen
                continue
    return ergebnis


def belegtyp(dateiname: str | None, seiten: int | None) -> list[str]:
    name = (dateiname or "").lower()
    typen = ["PDF" if ".pdf" in name else "Foto/Bild"]
    if seiten:
        typen.append("mehrseitig" if seiten > 1 else "einseitig")
    return typen


def auswerten(faelle: list[dict]) -> dict:
    """faelle: [{"bewertung": Feedback-Eintrag, "lesungen": [...], "dateiname": str, "seiten": int|None}].

    Rückgabe (Zähler immer als [richtig, gesamt]):
      belege            – geprüfte Belege mit mindestens einer gespeicherten Lesung
      felder[key][v]    – je Feld und Variante (+ "ergebnis" = gespeichertes Endergebnis)
      belegart[v]       – Belegart je Variante
      gruppen[name][v]  – zusammengefasst je Feldart
      je_typ[typ]       – Endergebnis je Belegtyp (Foto/PDF, ein-/mehrseitig): [richtige Felder, Felder]
      nur_original / nur_kontrast – Felder, in denen genau eine der beiden ersten Lesungen richtig lag
      schiedsrichter    – eingesetzt (Belege), gerettet (beide ersten falsch, er richtig),
                          verschlechtert (eine der ersten richtig, Endergebnis falsch)
    """
    erg = {
        "belege": 0,
        "felder": {key: {} for key, _l, _t in FEEDBACK_FELDER},
        "belegart": {},
        "gruppen": {name: {} for name in GRUPPEN},
        "je_typ": {},
        "nur_original": 0,
        "nur_kontrast": 0,
        "schiedsrichter": {"eingesetzt": 0, "gerettet": 0, "verschlechtert": 0},
    }

    def zaehlen(ziel: dict, variante: str, richtig: bool) -> None:
        z = ziel.setdefault(variante, [0, 0])
        z[0] += bool(richtig)
        z[1] += 1

    for fall in faelle:
        bewertung = fall["bewertung"]
        lesungen = _lesungen_je_variante(fall.get("lesungen"))
        if not lesungen:
            continue
        erg["belege"] += 1
        if "hochaufgelöst" in lesungen:
            erg["schiedsrichter"]["eingesetzt"] += 1
        typen = belegtyp(fall.get("dateiname"), fall.get("seiten"))

        # Belegart
        kat = bewertung["kategorie"]
        for variante, analyse in lesungen.items():
            zaehlen(erg["belegart"], variante, analyse.kategorie == kat["korrekt"])
        zaehlen(erg["belegart"], "ergebnis", kat["richtig"])

        # Felder
        for key, feld in (bewertung.get("felder") or {}).items():
            if key not in erg["felder"]:
                continue
            richtig = {v: _gleich(key, getattr(a, key), feld["korrekt"]) for v, a in lesungen.items()}
            richtig["ergebnis"] = bool(feld["richtig"])
            for variante, ok in richtig.items():
                zaehlen(erg["felder"][key], variante, ok)
                for gruppe, keys in GRUPPEN.items():
                    if key in keys:
                        zaehlen(erg["gruppen"][gruppe], variante, ok)
            for typ in typen:
                zaehlen(erg["je_typ"], typ, richtig["ergebnis"])
            if "original" in richtig and "kontrast" in richtig and richtig["original"] != richtig["kontrast"]:
                erg["nur_original" if richtig["original"] else "nur_kontrast"] += 1
            if "hochaufgelöst" in richtig:
                kleine = [richtig[v] for v in ("original", "kontrast") if v in richtig]
                if kleine and not any(kleine) and richtig["hochaufgelöst"]:
                    erg["schiedsrichter"]["gerettet"] += 1
                if any(kleine) and not richtig["ergebnis"]:
                    erg["schiedsrichter"]["verschlechtert"] += 1
    return erg


def quote(zaehler: list[int] | None) -> float | None:
    return zaehler[0] / zaehler[1] if zaehler and zaehler[1] else None


# ---------------------------------------------------------------------------
# Wann hilft der Schiedsrichter? (Grundlage, um ihn bei bestimmten Gründen zu überspringen)
# ---------------------------------------------------------------------------

ABWEICHUNG = "Lesungen wichen ab"
EINE_LESUNG = "Eine Lesung fehlgeschlagen"


def grund_art(grund: str) -> str:
    """'Belegart unsicher: Tankstelle mit …' -> 'Belegart unsicher'; 'Auslandsbeleg – dafür gilt …' ->
    'Auslandsbeleg'; 'Kein Steuersatz ausgewiesen.' -> ohne Punkt."""
    return grund.split(":", 1)[0].split(" – ", 1)[0].strip().rstrip(".")


def schiedsrichter_wirkung(belege: list[dict]) -> dict[str, dict]:
    """belege: [{"lesungen": [...], "bewertung": Feedback-Eintrag oder None}].

    Für jeden Beleg, bei dem der Schiedsrichter gelesen hat, wird aus den ersten Lesungen nachgerechnet, WARUM
    er gerufen wurde (Auslöser), und gezählt, was er bewirkt hat. Rückgabe je Auslöser:
      einsaetze   – Belege mit diesem Auslöser (ein Beleg kann mehrere haben)
      aufgeloest  – der Auslöser war nach dem Schiedsrichter weg (Abweichung geklärt bzw. Grund entfallen)
      geaendert   – der Schiedsrichter las in den Vergleichsfeldern etwas anderes als Lesung 1
      geprueft    – davon von einem Menschen geprüft
      besser / schlechter – Felder, in denen er laut Prüfung richtig lag und Lesung 1 falsch (bzw. umgekehrt)
    """
    from checks import _gleich as vergleich_gleich
    from checks import abweichungen, nachfragen_gruende, pruefen, vergleichswerte

    ergebnis: dict[str, dict] = {}
    for beleg in belege:
        lesungen = _lesungen_je_variante(beleg.get("lesungen"))
        gross = lesungen.get("hochaufgelöst")
        kleine = [lesungen[v] for v in ("original", "kontrast") if v in lesungen]
        if gross is None or not kleine:
            continue  # ohne Schiedsrichter oder ohne erste Lesung nichts zu vergleichen
        basis = kleine[0]

        ausloeser = {grund_art(g) for g in nachfragen_gruende(basis, pruefen(basis))}
        nachher = {grund_art(g) for g in nachfragen_gruende(gross, pruefen(gross))}
        aufgeloest = {a: a not in nachher for a in ausloeser}
        if len(kleine) == 2:
            diff = abweichungen(kleine[0], kleine[1])
            if diff:
                werte = vergleichswerte(gross)
                ausloeser.add(ABWEICHUNG)
                aufgeloest[ABWEICHUNG] = all(vergleich_gleich(f, werte[f], x) or vergleich_gleich(f, werte[f], y)
                                             for f, (x, y) in diff.items())
        else:
            ausloeser.add(EINE_LESUNG)
            aufgeloest[EINE_LESUNG] = True  # der Schiedsrichter hat den Beleg gelesen
        if not ausloeser:
            continue
        geaendert = vergleichswerte(gross) != vergleichswerte(basis)

        besser = schlechter = 0
        bewertung = beleg.get("bewertung")
        if bewertung:
            for key, feld in (bewertung.get("felder") or {}).items():
                if key not in _TYP:
                    continue
                g_ok = _gleich(key, getattr(gross, key), feld["korrekt"])
                b_ok = _gleich(key, getattr(basis, key), feld["korrekt"])
                besser += g_ok and not b_ok
                schlechter += b_ok and not g_ok

        for a in ausloeser:
            z = ergebnis.setdefault(a, {"einsaetze": 0, "aufgeloest": 0, "geaendert": 0, "geprueft": 0,
                                        "besser": 0, "schlechter": 0})
            z["einsaetze"] += 1
            z["aufgeloest"] += aufgeloest[a]
            z["geaendert"] += geaendert
            if bewertung:
                z["geprueft"] += 1
                z["besser"] += besser
                z["schlechter"] += schlechter
    return ergebnis


def ueberspringen_kandidaten(wirkung: dict[str, dict], mindestens: int = 5) -> list[str]:
    """Auslöser, bei denen der Schiedsrichter oft lief, aber nie etwas aufgelöst oder geändert hat."""
    return sorted(a for a, z in wirkung.items()
                  if z["einsaetze"] >= mindestens and not z["aufgeloest"] and not z["geaendert"]
                  and a not in (ABWEICHUNG, EINE_LESUNG))
