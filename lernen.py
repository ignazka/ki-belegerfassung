"""„Aus Korrekturen lernen“ – Logik ohne Oberfläche (der Prompt und die Antwortprüfung stehen in kategorien.py).

- Vorsortieren: eindeutige Fälle ohne KI einer Ursache zuordnen (nur „Unsicher gelesen“, sonst alles richtig).
- Veraltete Fälle: Wurde eine betroffene Kategorie NACH der Analyse inhaltlich geändert, ist der Fehler
  vielleicht schon behoben – solche Fälle gehen standardmäßig nicht mehr ans Modell.
- Wirkung: Fehlerquote einer Kategorie vor und nach dem Speichern eines übernommenen Vorschlags.
"""

from collections.abc import Iterable

from beleg_schema import STANDARD_KATEGORIEN
from kategorien import FELDER, STANDARD_BESCHREIBUNG, _als_text

NUR_UNSICHER_KURZ = ("Nur nachgefragt, weil zwei Lesungen voneinander abwichen – am Ende stimmte alles. "
                     "Lässt sich nicht über Regeln beheben.")


def fehlerfrei(bewertung: dict) -> bool:
    """Belegart bestätigt und kein Feld korrigiert."""
    return bool(bewertung["kategorie"]["richtig"]) and all(
        f.get("richtig") for f in (bewertung.get("felder") or {}).values())


def vorsortiert(bewertung: dict, gruende: list[str]) -> str | None:
    """Fall, der ohne KI eindeutig ein Lesefehler ist -> kurzer Satz dazu, sonst None."""
    if (bewertung.get("kommentar") or "").strip() or not fehlerfrei(bewertung):
        return None
    if gruende and all(str(g).startswith("Unsicher gelesen") for g in gruende):
        return NUR_UNSICHER_KURZ
    return None


def _wissen(k: dict) -> tuple:
    """Was die Einordnung beeinflusst (ohne Konten): Name, Beschreibungsfelder, aktiv oder nicht, bekannte Aussteller."""
    aussteller = sorted(str(m.get("wert")) for m in k.get("bekannte_merkmale") or [] if isinstance(m, dict))
    return tuple(_als_text(k.get(f)) for f in ("name",) + FELDER) + (k.get("status") or "aktiv", tuple(aussteller))


def wissensaenderungen(versionen: list[dict]) -> dict[str, str]:
    """{schluessel: Zeitpunkt der letzten inhaltlichen Änderung}. Speichern ohne geänderten Text (z. B. nur
    das Konto) zählt nicht; das Anlegen einer neuen Kategorie zählt."""
    stand = {key: {"name": name, "beschreibung": STANDARD_BESCHREIBUNG.get(key, ""), "status": "aktiv"}
             for key, name in STANDARD_KATEGORIEN.items()}
    letzte: dict[str, str] = {}
    for v in sorted(versionen, key=lambda v: (v.get("version") or 0, v.get("zeitpunkt") or "")):  # Version zählt, nicht die Uhrzeit (UTC in der Cloud, lokal MEZ)
        key = v.get("schluessel")
        if not key:
            continue
        neu = {**stand.get(key, {}), **v}
        if key in STANDARD_KATEGORIEN:
            neu.update(name=STANDARD_KATEGORIEN[key], status="aktiv")
        if key not in stand or _wissen(neu) != _wissen(stand[key]):
            letzte[key] = v.get("zeitpunkt") or ""
        stand[key] = neu
    return letzte


def veraltet(analyse_zeit: str | None, kategorien: Iterable[str | None], aenderungen: dict[str, str]) -> bool:
    """True, wenn eine der Kategorien (Wahl der KI, richtige Belegart) nach der Analyse geändert wurde."""
    return any(aenderungen.get(k, "") > (analyse_zeit or "") for k in kategorien if k)


def betrifft(bewertung: dict, kategorie: str) -> bool:
    k = bewertung["kategorie"]
    return kategorie in (k.get("modell"), k.get("korrekt"))


def wirkung(bewertungen: list[tuple[str, dict]], kategorie: str, ab: str) -> dict[str, tuple[int, int]]:
    """bewertungen: [(Analysezeitpunkt, jüngste Bewertung)]. Belege, die die Kategorie betreffen (von der KI
    gewählt oder richtig), vor und nach `ab` -> {"vorher": (mit Fehler, gesamt), "nachher": (…)}."""
    zaehler = {"vorher": [0, 0], "nachher": [0, 0]}
    for zeit, f in bewertungen:
        if not betrifft(f, kategorie):
            continue
        z = zaehler["nachher" if (zeit or "") >= ab else "vorher"]
        z[1] += 1
        z[0] += 0 if fehlerfrei(f) else 1
    return {k: (v[0], v[1]) for k, v in zaehler.items()}


def testbelege_auswaehlen(belege: list[dict], kategorie_menge: set[str], anzahl: int) -> list[dict]:
    """Geprüfte Belege für den Probelauf: solche mit Fehler (soll die Änderung beheben) und fehlerfreie
    (dürfen nicht kaputtgehen), je etwa zur Hälfte, die neuesten zuerst. belege: wie App._alle_belege()."""
    passend = [b for b in belege if b.get("bewertung")
               and ({b["bewertung"]["kategorie"].get("modell"), b["bewertung"]["kategorie"].get("korrekt")}
                    & kategorie_menge)]
    passend.sort(key=lambda b: b.get("zeitpunkt") or "", reverse=True)
    falsch = [b for b in passend if not fehlerfrei(b["bewertung"])]
    richtig = [b for b in passend if fehlerfrei(b["bewertung"])]
    auswahl = falsch[:anzahl // 2]
    auswahl += richtig[:anzahl - len(auswahl)]
    auswahl += falsch[anzahl // 2:anzahl // 2 + anzahl - len(auswahl)]
    return auswahl
