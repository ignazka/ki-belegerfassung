"""Testlauf: Beispielbelege einer Kategorie mit altem und neuem Kategorie-Wissen analysieren und vergleichen.

So sieht die Buchhaltung VOR dem Aktivieren, ob eine geänderte Beschreibung die Erkennung verbessert.
Gemessen wird: Wird der Beleg als die erwartete Kategorie erkannt? Muss nachgefragt werden? Wurde derselbe
Beleg schon in der App geprüft, dient diese Prüfung als Musterlösung: Dann zählen ihre Belegart und die
richtig gelesenen Felder (Beträge, Datum, Konto …).

Die neue Kategorie und ihre Konten gelten nur innerhalb des Probelaufs (beleg_schema.sonderstand) –
gleichzeitige echte Analysen anderer Benutzer sehen davon nichts.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from collections import Counter

from beleg_schema import (BEWIRTUNG_KATEGORIEN, FEEDBACK_FELDER, betrag_de, datum_de, gueltige_kategorien,
                          gueltige_konten, konto_waehlen, sonderstand, werte_gleich)
from extraction import dateien_zu_bildern
from pipeline import beleg_lesen

MAX_BELEGE = 15
PARALLEL = 4


def erwartete_kategorien(schluessel: str) -> set[str]:
    """Bewirtungs-Unterarten zählen gegenseitig als Treffer (Restaurant-Beleg vs. Restaurant + EC)."""
    return set(BEWIRTUNG_KATEGORIEN) if schluessel in BEWIRTUNG_KATEGORIEN else {schluessel}


@dataclass
class Ergebnis:
    kategorie: str | None
    nachfrage: bool
    gruende: list[str]
    betrag: str
    datum: str
    fehler: str | None = None
    konto: str | None = None
    konto_unsicher: bool = False
    werte: dict | None = None  # {Prüffeld: gelesener Wert} für den Vergleich mit einer Musterlösung


def _analysieren(beleg: tuple, system: str, konten: dict | None = None) -> Ergebnis:
    """beleg: (name, bytes, mime) oder – bei mehreren Dateien/Seiten – (name, [(name, bytes, mime), …]).
    konten: Konto-Regeln DIESER Variante ({kategorie: {"standard", "ausnahmen"}}). Ohne: wie gelesen."""
    try:
        dateien = beleg[1] if isinstance(beleg[1], list) else [beleg]
        bilder = dateien_zu_bildern(dateien)[0]
        e = beleg_lesen(bilder, dateien, system=system)
    except Exception as ex:
        return Ergebnis(None, True, [], "", "", f"{type(ex).__name__}: {ex}")
    a = e.analyse
    gruende, konto, unsicher = list(e.gruende), a.konto, a.konto_unsicher
    if konten is not None:
        konto, unsicher = konto_waehlen(konten.get(a.kategorie), a.konto, a.konto_unsicher)
        if not unsicher:  # Konto-Nachfrage gilt nur, wenn diese Variante Ausnahmen kennt
            gruende = [g for g in gruende if not g.startswith("Konto unsicher")]
    werte = {key: getattr(a, key, None) for key, _label, _typ in FEEDBACK_FELDER}
    werte["konto"] = konto
    return Ergebnis(a.kategorie, bool(gruende), gruende,
                    f"{betrag_de(a.brutto)} €" if a.brutto is not None else "–", datum_de(a.datum) or "–",
                    konto=konto, konto_unsicher=unsicher, werte=werte)


def konten_vereinigen(*konten: dict[str, dict]) -> dict[str, dict]:
    """Für die Dauer des Probelaufs: alle Konten beider Varianten erlauben (ohne Standard), damit die Wahl der
    KI erhalten bleibt. Welches Konto je Variante gilt, entscheidet danach konto_waehlen mit deren Regeln."""
    alle: dict[str, set] = {}
    for k in konten:
        for kategorie, regel in k.items():
            alle.setdefault(kategorie, set()).update(
                x for x in [regel.get("standard"), *(regel.get("ausnahmen") or [])] if x)
    return {kategorie: {"standard": None, "ausnahmen": sorted(nummern)} for kategorie, nummern in alle.items()}


def _im_sonderstand(kategorien, alle_konten, beleg, system, konten):
    """Läuft im Arbeits-Thread: Kategorien/Konten des Probelaufs gelten nur hier (und in beleg_lesens Threads)."""
    if kategorien is None and not alle_konten:
        return _analysieren(beleg, system, konten)
    with sonderstand(gueltige_kategorien() if kategorien is None else kategorien,
                     alle_konten or gueltige_konten()):
        return _analysieren(beleg, system, konten)


def ausfuehren(belege: list[tuple[str, bytes, str]], varianten: dict[str, str], fortschritt=None,
               konten: dict[str, dict] | None = None, kategorien: dict[str, str] | None = None):
    """belege: [(name, bytes, mime)]; varianten: {"vorher": system_prompt, "nachher": system_prompt};
    konten: {variante: Konto-Regeln} (optional); kategorien: gültige {schluessel: Name} für den Probelauf
    (z. B. inkl. der noch nicht gespeicherten Kategorie). -> {beleg_name: {variante: Ergebnis}}"""
    melden = fortschritt or (lambda _fertig, _gesamt: None)
    auftraege = [(b, v, system) for b in belege for v, system in varianten.items()]
    ergebnisse: dict[str, dict[str, Ergebnis]] = {b[0]: {} for b in belege}
    # während des Laufs alle Konten beider Varianten erlauben; je Variante entscheidet danach konto_waehlen
    alle_konten = konten_vereinigen(*konten.values()) if konten else {}
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        futures = {pool.submit(_im_sonderstand, kategorien, alle_konten, b, system, (konten or {}).get(v)): (b[0], v)
                   for b, v, system in auftraege}
        for fertig, f in enumerate(as_completed(futures), start=1):
            name, variante = futures[f]
            ergebnisse[name][variante] = f.result()
            melden(fertig, len(auftraege))
    return ergebnisse


def erwartet_fuer(name: str, erwartet: set[str], muster: dict | None) -> set[str]:
    """Erwartete Belegart eines Belegs: laut Musterlösung (geprüft), sonst laut Beispielordner."""
    m = (muster or {}).get(name)
    return erwartete_kategorien(m["kategorie"]) if m and m.get("kategorie") else erwartet


def felder_vergleichen(e: Ergebnis, muster: dict | None) -> tuple[int, int, list[str]]:
    """Gelesene Werte gegen die Musterlösung -> (richtig, geprüft, [Labels der falschen Felder])."""
    if not muster or not e.werte or e.fehler:
        return 0, 0, []
    richtig, falsch = 0, []
    for key, label, typ in FEEDBACK_FELDER:
        if key not in (muster.get("felder") or {}):
            continue
        if werte_gleich(typ, e.werte.get(key), muster["felder"][key]):
            richtig += 1
        else:
            falsch.append(label)
    return richtig, richtig + len(falsch), falsch


def zusammenfassung(ergebnisse: dict, variante: str, erwartet: set[str], muster: dict | None = None) -> dict:
    """muster: {beleg_name: {"kategorie": schluessel, "felder": {key: richtiger Wert}}} – geprüfte Belege."""
    paare = [(name, e[variante]) for name, e in ergebnisse.items() if variante in e]
    felder = [felder_vergleichen(e, (muster or {}).get(name)) for name, e in paare]
    return {
        "belege": len(paare),
        "erkannt": sum(1 for name, e in paare if e.kategorie in erwartet_fuer(name, erwartet, muster)),
        "nachfragen": sum(1 for _n, e in paare if e.nachfrage),
        "fehler": sum(1 for _n, e in paare if e.fehler),
        "konten": Counter(e.konto for _n, e in paare if e.konto and not e.fehler),
        "mit_muster": sum(1 for name, e in paare if (muster or {}).get(name) and not e.fehler),
        "felder_richtig": sum(f[0] for f in felder),
        "felder_geprueft": sum(f[1] for f in felder),
    }
