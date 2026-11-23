"""Rechen- und Plausibilitätsprüfungen im Code + Entscheidung, ob ein Beleg zur Nachfrage abgelegt wird.

Das Modell liest nur ab; alles Rechnen und Gegenprüfen passiert hier.
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from beleg_schema import (
    TOLERANZ_SUMME,
    TOLERANZ_ZEILE,
    BelegAnalyse,
    betrag_de,
    datum_de,
    mwst_aus_brutto,
    mwst_aus_netto,
    summe,
)

TOLERANZ = TOLERANZ_SUMME
TRINKGELD_MAX_ANTEIL = 0.30


def _eur(x: float) -> str:
    return f"{betrag_de(x)} €"


def pruefen(a: BelegAnalyse) -> list[str]:
    """Liefert Auffälligkeiten (leere Liste = alles stimmig). Alle Rechnungen cent-genau (Decimal)."""
    befunde = []

    # 1. Ergeben die Steuerzeilen zusammen den gedruckten Gesamtbetrag?
    #    (fängt falsch gelesene Gesamtbeträge, Überträge/Zwischensummen und vergessene Zeilen ab)
    zeilen_brutto = []
    for z in a.steuerzeilen:
        if z.brutto is not None:
            zeilen_brutto.append(z.brutto)
        elif z.netto is not None and z.mwst is not None:
            zeilen_brutto.append(summe([z.netto, z.mwst]))
        else:
            zeilen_brutto = None
            break
    if zeilen_brutto and a.brutto is not None:
        gesamt = summe(zeilen_brutto)
        if abs(gesamt - a.brutto) > TOLERANZ_SUMME:
            befunde.append(
                f"Steuerzeilen ergeben {_eur(gesamt)}, als Gesamtbetrag erkannt wurde {_eur(a.brutto)} – "
                "Gesamtbetrag oder Steuerzeilen falsch gelesen."
            )

    saetze = [z.satz for z in a.steuerzeilen if z.satz is not None]
    if len(saetze) != len(set(saetze)):
        befunde.append("Ein Steuersatz kommt in der MwSt.-Aufstellung mehrfach vor – Zeile falsch gelesen.")

    # 2. Passt jede Zeile in sich? MwSt. = Satz × Netto, und Netto + MwSt. = Brutto (falls gedruckt)
    for z in a.steuerzeilen:
        if z.satz and z.netto is not None and z.mwst is not None:
            erwartet = mwst_aus_netto(z.netto, z.satz)
            if abs(erwartet - z.mwst) > TOLERANZ_ZEILE:
                zusatz = ""
                if abs(mwst_aus_brutto(z.netto, z.satz) - z.mwst) <= TOLERANZ_ZEILE:
                    zusatz = " (passt, wenn der Betrag brutto ist – dann stimmt aber die Gesamtsumme nicht)"
                befunde.append(
                    f"MwSt. {z.satz:g} %: {_eur(z.netto)} netto ergibt {_eur(erwartet)}, "
                    f"gelesen wurde {_eur(z.mwst)}{zusatz}."
                )
        if z.netto is not None and z.mwst is not None and z.brutto is not None:
            if abs(summe([z.netto, z.mwst]) - z.brutto) > TOLERANZ_SUMME:
                befunde.append(
                    f"Zeile {f'{z.satz:g}' if z.satz is not None else '?'} %: Netto {_eur(z.netto)} + MwSt. {_eur(z.mwst)} "
                    f"≠ Brutto {_eur(z.brutto)}."
                )

    # 3. EC-Betrag vs. Rechnung
    if a.ec_betrag is not None and a.brutto is not None:
        if a.ec_betrag < a.brutto - TOLERANZ:
            befunde.append(
                f"EC-Betrag {_eur(a.ec_betrag)} ist kleiner als die Rechnung {_eur(a.brutto)} "
                "(Teilzahlung oder falsch gelesen?)."
            )
        elif a.trinkgeld and a.trinkgeld > a.brutto * TRINKGELD_MAX_ANTEIL:
            befunde.append(
                f"Trinkgeld {_eur(a.trinkgeld)} ist mehr als {TRINKGELD_MAX_ANTEIL:.0%} der Rechnung – "
                "EC-Beleg gehört evtl. nicht zu dieser Rechnung."
            )

    # 4. Datum
    heute = datetime.now(ZoneInfo("Europe/Berlin")).date()  # Server läuft auf UTC – Belege sind deutsche Zeit
    if a.datum and a.datum > heute.isoformat():
        befunde.append(f"Datum {datum_de(a.datum)} liegt in der Zukunft.")

    return befunde


def _gruende_mit_art(a: BelegAnalyse, befunde: list[str]) -> list[tuple[str, bool]]:
    """(Grund, fachlich). fachlich = genaueres Lesen ändert nichts (z. B. Auslandsbeleg) – dann bringt der
    Schiedsrichter nichts, ein Mensch muss trotzdem draufschauen. Im Zweifel NICHT fachlich."""
    gruende = []
    if not a.lesbar or a.kategorie == "unlesbar":
        gruende.append(("Beleg nicht (vollständig) lesbar.", False))
    if a.kategorie_unsicher:  # großes Modell ordnet oft sicherer ein
        gruende.append((f"Belegart unsicher: {a.kategorie_grund or 'ohne Begründung'}", False))
    if a.kategorie == "sonstiger_beleg":
        gruende.append(("Belegart keiner bekannten Kategorie zuzuordnen.", False))
    if a.kategorie == "nur_ec_beleg":
        gruende.append(("Nur Zahlungsnachweis, keine Rechnung – Rechnung anfordern.", True))
    if a.fehlende_pflichtangaben:  # evtl. nur klein/handschriftlich -> hochaufgelöst nachsehen
        gruende.append(("Pflichtangaben laut Kategorie fehlen: " + ", ".join(a.fehlende_pflichtangaben), False))
    if a.ausland:
        gruende.append(("Auslandsbeleg – dafür gilt eine abweichende Handhabe.", True))
    if a.konto_unsicher:  # Ermessensfrage laut Konto-Ausnahmen der Kategorie, genaueres Lesen hilft nicht
        gruende.append((f"Konto unsicher: {a.konto_grund or 'ohne Begründung'}", True))
    if a.ec_passt_zur_rechnung is False:  # kann an einem falsch gelesenen Datum/Betrag liegen
        gruende.append(("EC-Beleg passt nicht zur Rechnung (Datum/Uhrzeit/Adresse/Name).", False))

    # Pflichtanforderungen der Buchhaltung an eine Quittung: lesbar, Steuersatz, Datum
    if a.kategorie not in ("unlesbar", "nur_ec_beleg"):
        if not a.steuersatz_erkennbar and not a.steuerzeilen:
            gruende.append(("Kein Steuersatz ausgewiesen.", False))
        elif a.steuersaetze and not a.ausland and set(a.steuersaetze) - {7, 19}:
            andere = ", ".join(f"{s:g} %" for s in a.steuersaetze if s not in (7, 19))
            # beide Lesungen sehen denselben Satz (sonst Abweichung) -> steht so auf dem Beleg
            gruende.append((f"Ungewöhnlicher Steuersatz: {andere} (erwartet 7 % und/oder 19 %).", True))
        fehlend = [name for name, wert in (("Gesamtbetrag", a.brutto), ("Datum", a.datum)) if wert is None]
        if fehlend:
            gruende.append(("Pflichtangabe fehlt: " + ", ".join(fehlend), False))
    gruende += [(f"Rechenprüfung: {b}", False) for b in befunde]
    return gruende


# Gespeicherte Nachfragegründe, bei denen ein Mensch IMMER draufschauen muss – auch wenn die KI alles richtig
# gelesen hat. Sie zählen in der Auswertung nicht als „unnötige Nachfrage“ (die soll zu strenge Regeln zeigen).
# Fachliche Gründe aus _gruende_mit_art (Test hält beides gleich) + Kalender, Seitenlimit, technische Absicherung.
_IMMER_BERECHTIGT = ("Nur Zahlungsnachweis", "Auslandsbeleg", "Konto unsicher", "Ungewöhnlicher Steuersatz",
                     "Kalender:", "Großes Modell nicht verfügbar", "Nur das große Modell konnte")


def immer_berechtigt(grund: str) -> bool:
    return grund.startswith(_IMMER_BERECHTIGT) or bool(re.match(r"Nur \d+ von \d+ Seiten gelesen", grund))


def nachfragen_gruende(a: BelegAnalyse, befunde: list[str]) -> list[str]:
    """Gründe, warum ein Mensch draufschauen muss. Leere Liste = kann automatisch weiter."""
    return [text for text, _fachlich in _gruende_mit_art(a, befunde)]


def nur_fachliche_gruende(a: BelegAnalyse, befunde: list[str]) -> bool:
    """True, wenn es Nachfragegründe gibt und KEINER durch genaueres Lesen verschwinden könnte."""
    gruende = _gruende_mit_art(a, befunde)
    return bool(gruende) and all(fachlich for _text, fachlich in gruende)


# ---------------------------------------------------------------------------
# Doppelt-Lesen: zwei Lesungen vergleichen
# ---------------------------------------------------------------------------

def _text_norm(s: str | None) -> str:
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())


def _uhrzeit_norm(s: str | None) -> str:
    """'18:30', '18.30', '18:30:12', '8:05 Uhr' -> '18:30' bzw. '08:05'; Unlesbares bleibt als Text."""
    treffer = re.match(r"^\s*(\d{1,2})[:.](\d{2})", s or "")
    return f"{int(treffer.group(1)):02d}:{treffer.group(2)}" if treffer else _text_norm(s)


def _plz(adresse: str | None) -> str:
    """Fünfstellige Postleitzahl aus der Adresse ('…, 67346 Speyer' -> '67346'); ohne (z. B. Ausland) leer.
    Nur die PLZ, nicht der Ortsname: „Frankfurt a. M.“ / „Frankfurt am Main“ ist kein Lesefehler."""
    treffer = re.search(r"\b(\d{5})\s+[A-Za-zÄÖÜäöüß]", adresse or "")
    return treffer.group(1) if treffer else ""


def vergleichswerte(a: BelegAnalyse) -> dict[str, str]:
    """Die Felder, die beim Doppelt-Lesen übereinstimmen müssen – normalisiert, als Anzeigetext."""
    zeilen = sorted(
        (z.satz or 0, z.netto, z.mwst) for z in a.steuerzeilen
    )
    return {
        "Belegart": a.kategorie,
        "Konto": a.konto or "",  # weicht nur ab, wenn die Kategorie Konto-Ausnahmen hat
        "Belegnummer": _text_norm(a.belegnummer),
        "Aussteller": _text_norm(a.restaurant_name),
        "Datum": a.datum or "",
        "Uhrzeit": _uhrzeit_norm(a.uhrzeit),  # wichtig für Kalenderabgleich und EC-Beleg
        "PLZ": _plz(a.adresse),               # Stadt zählt beim Kalenderabgleich
        "Gesamtbetrag": _eur(a.brutto) if a.brutto is not None else "",
        "EC-Betrag": _eur(a.ec_betrag) if a.ec_betrag is not None else "",
        "MwSt.-Aufstellung": "; ".join(
            f"{s:g} %: {_eur(n) if n is not None else '–'} / {_eur(m) if m is not None else '–'}"
            for s, n, m in zeilen
        ),
    }


def _gleich(feld: str, x: str, y: str) -> bool:
    if feld == "Aussteller" and x and y:
        return x in y or y in x  # "Aral Tankstelle" vs. "Aral" ist kein Lesefehler
    return x == y


def abweichungen(a: BelegAnalyse, b: BelegAnalyse) -> dict[str, tuple[str, str]]:
    """{Feld: (Wert Lesung 1, Wert Lesung 2)} für alle Felder, die nicht übereinstimmen."""
    va, vb = vergleichswerte(a), vergleichswerte(b)
    return {f: (va[f], vb[f]) for f in va if not _gleich(f, va[f], vb[f])}


def anzeige_wert(feld: str, a: BelegAnalyse) -> str:
    """Wert eines Vergleichsfelds lesbar (nicht normalisiert) für Meldungen."""
    roh = {"Belegnummer": a.belegnummer, "Aussteller": a.restaurant_name, "Datum": datum_de(a.datum),
           "Uhrzeit": a.uhrzeit, "PLZ": a.adresse}
    return (roh.get(feld) if feld in roh else vergleichswerte(a)[feld]) or "–"
