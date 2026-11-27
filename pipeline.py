"""Ablauf einer Beleg-Analyse: doppelt lesen, vergleichen, bei Zweifel großes Modell als Schiedsrichter.

1. Zwei Lesungen PARALLEL mit MODEL: Originalbild + Kontrast-Variante (unabhängigere Lesefehler).
2. Stimmen alle wichtigen Felder überein und bestehen alle Prüfungen -> fertig.
   Stimmen sie überein und gibt es nur rein fachliche Nachfragegründe (z. B. Auslandsbeleg) -> auch fertig,
   ohne Schiedsrichter (genaueres Lesen ändert daran nichts); die Nachfrage bleibt.
3. Sonst liest MODEL_GROSS. Dessen Ergebnis gilt. Ein Feld, in dem die beiden ersten Lesungen
   abwichen, gilt als geklärt, wenn das große Modell einer der beiden Lesungen zustimmt.
   Ungeklärte Felder + alle übrigen Prüfgründe -> Nachfrage.
   Schiedsrichter abgeschaltet (Schalter in der Seitenleiste, zum Testen): statt Schritt 3 gilt Lesung 1,
   abweichende Felder und alle Prüfgründe gehen als Nachfrage an den Menschen.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field

from beleg_schema import BelegAnalyse
from checks import _gleich, abweichungen, anzeige_wert, nachfragen_gruende, nur_fachliche_gruende, pruefen, vergleichswerte
from extraction import SYSTEM_PROMPT, MODEL, MODEL_GROSS, AnalyseFehler, analysieren, dateien_zu_bildern, kontrast_variante


@dataclass
class Lesung:
    modell: str
    variante: str  # "original" | "kontrast"
    analyse: BelegAnalyse | None
    raw: str | None
    usage: dict
    fehler: str | None = None


@dataclass
class LeseErgebnis:
    analyse: BelegAnalyse
    raw: str
    modell: str                      # Modell, dessen Ergebnis gilt
    lesungen: list[Lesung]
    abweichungen: dict[str, tuple[str, str]] = field(default_factory=dict)  # zwischen Lesung 1 und 2
    ungeklaert: list[str] = field(default_factory=list)                     # auch nach Schiedsrichter
    schiedsrichter: bool = False
    befunde: list[str] = field(default_factory=list)
    gruende: list[str] = field(default_factory=list)

    @property
    def usage(self) -> list[dict]:
        return [{"modell": l.modell, "variante": l.variante, **l.usage} for l in self.lesungen]


def _lesen(bilder, modell, variante, system=SYSTEM_PROMPT) -> Lesung:
    try:
        analyse, raw, usage = analysieren(bilder, modell, system)
        return Lesung(modell, variante, analyse, raw, usage)
    except AnalyseFehler as e:
        return Lesung(modell, variante, None, e.raw, {}, f"Antwort nicht lesbar: {e}")
    except Exception as e:  # Netzwerk, Anbieter, Timeout
        return Lesung(modell, variante, None, None, {}, f"Modell-Aufruf fehlgeschlagen: {e}")


def _unsicher(f: str, lesungen: list[Lesung]) -> str:
    return f"Unsicher gelesen – {f}: " + " / ".join(anzeige_wert(f, l.analyse) for l in lesungen if l.analyse is not None)


def beleg_lesen(bilder: list[bytes], dateien=None, status=None, system: str = SYSTEM_PROMPT,
                schiedsrichter: bool = True) -> LeseErgebnis:
    """bilder: normal aufbereitete Seiten. dateien: Originale (name, bytes, mime) für die hochaufgelöste
    Schiedsrichter-Lesung (ohne dateien liest er die normalen Bilder). status: Funktion(text) für Fortschritt.
    schiedsrichter=False: großes Modell nie fragen (Testbetrieb) – Zweifel gehen direkt an den Menschen."""
    melden = status or (lambda _text: None)

    melden("Lese den Beleg doppelt …")
    with ThreadPoolExecutor(max_workers=2) as pool:
        # copy_context: ein Probelauf-Sonderstand (beleg_schema.sonderstand) gilt auch in den Lese-Threads
        f1 = pool.submit(copy_context().run, _lesen, bilder, MODEL, "original", system)
        f2 = pool.submit(copy_context().run, _lesen, [kontrast_variante(b) for b in bilder], MODEL, "kontrast",
                         system)
        l1, l2 = f1.result(), f2.result()
    lesungen = [l1, l2]

    gueltig = [l for l in lesungen if l.analyse is not None]
    basis = gueltig[0] if gueltig else None
    diff = abweichungen(l1.analyse, l2.analyse) if len(gueltig) == 2 else {}

    if basis is not None:
        befunde = pruefen(basis.analyse)
        gruende = nachfragen_gruende(basis.analyse, befunde)
        if len(gueltig) == 2 and not diff and not gruende:
            return LeseErgebnis(basis.analyse, basis.raw, MODEL, lesungen, befunde=befunde)
        if len(gueltig) == 2 and not diff and nur_fachliche_gruende(basis.analyse, befunde):
            # z. B. Auslandsbeleg: beide Lesungen stimmen, genaueres Lesen ändert nichts -> kein Schiedsrichter,
            # aber Nachfrage an den Menschen bleibt
            return LeseErgebnis(basis.analyse, basis.raw, MODEL, lesungen, befunde=befunde, gruende=gruende)

    if not schiedsrichter:
        if basis is None:
            raise AnalyseFehler(" / ".join(l.fehler or "" for l in lesungen), lesungen[0].raw)
        befunde = pruefen(basis.analyse)
        gruende = nachfragen_gruende(basis.analyse, befunde)
        if len(gueltig) < 2:
            gruende.append("Nur eine Lesung gelungen, Schiedsrichter abgeschaltet – ohne Gegenprobe, bitte die "
                           "Werte prüfen.")
        gruende += [_unsicher(f, lesungen) for f in diff]
        return LeseErgebnis(basis.analyse, basis.raw, MODEL, lesungen, diff, list(diff), False, befunde, gruende)

    # Zweifel -> großes Modell
    melden("Lesungen weichen ab oder Prüfung offen – großes Modell schaut nach …")
    try:
        bilder_hoch = dateien_zu_bildern(dateien, hochaufloesend=True)[0] if dateien else bilder
    except Exception:
        bilder_hoch = bilder
    l3 = _lesen(bilder_hoch, MODEL_GROSS, "hochaufgelöst", system)
    lesungen.append(l3)

    if l3.analyse is None:
        if basis is None:
            raise AnalyseFehler(" / ".join(l.fehler or "" for l in lesungen), lesungen[0].raw)
        befunde = pruefen(basis.analyse)
        gruende = nachfragen_gruende(basis.analyse, befunde)
        gruende.append(f"Großes Modell nicht verfügbar ({l3.fehler}).")
        gruende += [f"Doppelt gelesen, Abweichung bei {f}: {x or '–'} / {y or '–'}" for f, (x, y) in diff.items()]
        return LeseErgebnis(basis.analyse, basis.raw, MODEL, lesungen, diff, list(diff), True, befunde, gruende)

    gross = l3.analyse
    werte_gross = vergleichswerte(gross)
    ungeklaert = [f for f, (x, y) in diff.items()
                  if not (_gleich(f, werte_gross[f], x) or _gleich(f, werte_gross[f], y))]
    if len(gueltig) < 2:  # nur eine kleine Lesung -> mit der vergleichen
        andere = abweichungen(basis.analyse, gross) if basis else {}
        ungeklaert = list(andere)

    befunde = pruefen(gross)
    gruende = nachfragen_gruende(gross, befunde)
    if basis is None:  # beide kleinen Lesungen fehlgeschlagen -> niemand hat gegengelesen
        gruende.append("Nur das große Modell konnte den Beleg lesen – ohne Gegenprobe, bitte die Werte prüfen.")
    gruende += [_unsicher(f, lesungen) for f in ungeklaert]
    return LeseErgebnis(gross, l3.raw, MODEL_GROSS, lesungen, diff, ungeklaert, True, befunde, gruende)
