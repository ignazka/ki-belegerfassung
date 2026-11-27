"""Bekannte Merkmale: Aussteller, die zu einer Belegart gehören – damit die KI-Wahl gegengeprüft werden kann.

Zwei Quellen:
- von Hand im Tab „Kategorien“ (Feld `bekannte_merkmale` einer Kategorie-Version) – hat Vorrang;
- automatisch aus geprüften Belegen: ein Aussteller, der mindestens MIN_BELEGE-mal geprüft wurde und dabei
  immer zur selben Belegart gehörte.

Die KI liest den Aussteller nur ab, der Abgleich passiert im Code (checks._gruende_mit_art):
- bekannter Aussteller, KI wählt dieselbe Belegart -> Zweifel der KI an der Belegart sind ausgeräumt;
- bekannter Aussteller, KI wählt eine andere Belegart -> Nachfrage.
Merkmale stehen NICHT im Prompt (Prompt bleibt kurz, Prompt-Version ändert sich nicht).
"""

import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher

from beleg_schema import BEWIRTUNG_KATEGORIEN

MIN_BELEGE = 2         # so oft muss ein Aussteller geprüft sein, bevor er automatisch als bekannt gilt
AEHNLICHKEIT = 0.88    # kleine Lesefehler („Gasthaus zur Linde“ / „Gasthaus zur Iinde“) zählen noch als Treffer
_MIN_TEILTEXT = 4      # „Aral“ in „Aral Tankstelle“: Teiltreffer erst ab dieser Länge

# Rechtsformen und Füllwörter, die auf Belegen mal stehen und mal nicht
_FUELL = re.compile(r"\b(gmbh|mbh|ug|kg|ohg|gbr|ag|ek|e\s?k|inh|inhaber|co|und|haftungsbeschraenkt)\b")

_BEKANNT: dict[str, dict] = {}  # normalisierter Name -> {"name", "kategorie", "quelle", "anzahl"}


def norm(name: str | None) -> str:
    s = (name or "").casefold()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("&", " und ")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = _FUELL.sub(" ", s)
    return "".join(s.split())


def gruppe(kategorie: str | None) -> str | None:
    """Bewirtungs-Unterarten (Restaurant-Beleg, mit EC-Beleg, …) gehören zu EINEM Aussteller zusammen."""
    return "bewirtung" if kategorie in BEWIRTUNG_KATEGORIEN else kategorie


def aus_kategorien(stand: dict[str, dict]) -> list[dict]:
    """Von Hand eingetragene Aussteller aller (nicht gelöschten) Kategorien."""
    liste = []
    for key, k in stand.items():
        if k.get("status") == "geloescht":
            continue
        for m in k.get("bekannte_merkmale") or []:
            if isinstance(m, dict) and (m.get("art") or "aussteller") == "aussteller" and norm(m.get("wert")):
                liste.append({"name": str(m["wert"]).strip(), "kategorie": key, "quelle": "hand", "anzahl": 0})
    return liste


def aus_bewertungen(bewertungen: list[dict]) -> list[dict]:
    """Jüngste Prüfungen je Beleg -> automatisch bekannte Aussteller (eindeutig, oft genug geprüft)."""
    je_name: dict[str, list[tuple[str, str]]] = {}
    for f in bewertungen:
        kategorie = (f.get("kategorie") or {}).get("korrekt")
        feld = (f.get("felder") or {}).get("restaurant_name") or {}
        name = feld.get("korrekt") if "korrekt" in feld else (f.get("analyse") or {}).get("restaurant_name")
        if kategorie in (None, "unlesbar", "sonstiger_beleg") or not norm(name):
            continue
        je_name.setdefault(norm(name), []).append((str(name).strip(), kategorie))
    liste = []
    for eintraege in je_name.values():
        if len(eintraege) < MIN_BELEGE or len({gruppe(k) for _n, k in eintraege}) > 1:
            continue
        kategorie = Counter(k for _n, k in eintraege).most_common(1)[0][0]
        liste.append({"name": eintraege[-1][0], "kategorie": kategorie, "quelle": "belege", "anzahl": len(eintraege)})
    return liste


def registrieren(hand: list[dict], auto: list[dict]) -> None:
    """Gültige Liste setzen. Von Hand hat Vorrang; steht derselbe Aussteller von Hand bei zwei Belegarten
    unterschiedlicher Gruppen, ist er nicht eindeutig und wird ignoriert."""
    neu: dict[str, dict] = {}
    for m in auto:
        neu[norm(m["name"])] = m
    hand_je_name: dict[str, list[dict]] = {}
    for m in hand:
        hand_je_name.setdefault(norm(m["name"]), []).append(m)
    for n, eintraege in hand_je_name.items():
        if len({gruppe(m["kategorie"]) for m in eintraege}) == 1:
            neu[n] = eintraege[0]
        else:
            neu.pop(n, None)
    _BEKANNT.clear()
    _BEKANNT.update(neu)


def bekannte() -> list[dict]:
    return list(_BEKANNT.values())


def _passt(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) >= _MIN_TEILTEXT and (a in b or b in a):
        return True
    return min(len(a), len(b)) >= 6 and SequenceMatcher(None, a, b).ratio() >= AEHNLICHKEIT


def nachschlagen(name: str | None, liste: list[dict] | None = None) -> dict | None:
    """Bekannter Aussteller zum gelesenen Namen (tolerant gegen kleine Lesefehler) oder None.
    Passen mehrere mit verschiedenen Belegarten, ist es nicht eindeutig -> None."""
    n = norm(name)
    if not n:
        return None
    kandidaten = {norm(m["name"]): m for m in liste} if liste is not None else _BEKANNT
    if n in kandidaten:
        return kandidaten[n]
    treffer = [m for k, m in kandidaten.items() if _passt(n, k)]
    if len({gruppe(m["kategorie"]) for m in treffer}) != 1:
        return None
    return max(treffer, key=lambda m: (m["quelle"] == "hand", m["anzahl"]))


def aus_tabelle(zeilen: list[dict]) -> list[dict]:
    """Zeilen der Tabelle im Kategorien-Tab -> [{"art": "aussteller", "wert", "anmerkung"}] ohne Leerzeilen und
    Doppelte. Das Feld `art` hält das Format offen für weitere Merkmale (z. B. Mitarbeiter)."""
    def text(x):
        return "" if x is None or x != x else str(x).strip()  # x != x: leere Zelle (NaN) aus der Tabelle
    ergebnis, gesehen = [], set()
    for z in zeilen:
        wert, anmerkung = text(z.get("wert")), text(z.get("anmerkung"))
        if norm(wert) and norm(wert) not in gesehen:
            gesehen.add(norm(wert))
            ergebnis.append({"art": "aussteller", "wert": wert, "anmerkung": anmerkung})
    return ergebnis
