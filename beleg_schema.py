"""Datenmodell für die Beleg-Analyse: Kategorien, Felder, Validierung und Normalisierung."""

import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

# Feste Kategorienliste – das Modell MUSS eine davon wählen.
# Schlüssel nie umbenennen (stehen im gespeicherten Feedback), nur ergänzen.
STANDARD_KATEGORIEN = {
    "restaurant_beleg": "Bewirtung: Restaurant-Beleg / Quittung",
    "restaurant_mit_ec_beleg": "Bewirtung: Restaurant-Beleg + EC-/Kartenbeleg",
    "nur_ec_beleg": "Bewirtung: nur EC-/Kartenbeleg (keine Rechnung)",
    "bewirtungsbeleg_intern": "Bewirtung: interner Bewirtungsbeleg (Formular)",
    "tankbeleg": "Tankbeleg (Kraftstoff)",
    "uebernachtung": "Übernachtung / Hotelrechnung",
    "sonstiger_beleg": "Sonstiger Beleg",
    "unlesbar": "Unlesbar / kein Beleg",
}
# Aktuell gültige Kategorien = Standard + in der App angelegte (siehe kategorien_registrieren).
# Ein gemeinsames Dict für alle Sitzungen – alle Benutzer arbeiten mit denselben Kategorien.
KATEGORIEN = dict(STANDARD_KATEGORIEN)


def kategorien_registrieren(aktive: dict[str, str]) -> None:
    """Setzt die gültigen Kategorien (Standard bleibt immer). aktive = {schluessel: Name}."""
    neu = {**aktive, **STANDARD_KATEGORIEN}
    for key in list(KATEGORIEN):
        if key not in neu:
            del KATEGORIEN[key]
    KATEGORIEN.update(neu)


# SKR04-Konten je aktiver Kategorie: {schluessel: {"standard": "6640" | None, "ausnahmen": ["6664", ...]}}.
# Die KI darf nur eines dieser Konten wählen; alles andere ersetzt der Code durch das Standardkonto.
KONTEN: dict[str, dict] = {}


def konten_registrieren(konten: dict[str, dict]) -> None:
    KONTEN.clear()
    KONTEN.update(konten)


# Probelauf: abweichende Kategorien/Konten NUR für den laufenden Vorgang (nicht für andere Sitzungen).
# ContextVar statt globaler Änderung; pipeline.beleg_lesen reicht den Kontext an seine Lese-Threads weiter.
_SONDERSTAND: ContextVar[tuple[dict, dict] | None] = ContextVar("kategorien_sonderstand", default=None)


@contextmanager
def sonderstand(kategorien: dict[str, str], konten: dict[str, dict]):
    """Innerhalb des with-Blocks gelten diese Kategorien ({schluessel: Name}, Standard immer dabei) und Konten."""
    token = _SONDERSTAND.set(({**kategorien, **STANDARD_KATEGORIEN}, konten))
    try:
        yield
    finally:
        _SONDERSTAND.reset(token)


def gueltige_kategorien() -> dict[str, str]:
    sonder = _SONDERSTAND.get()
    return sonder[0] if sonder else KATEGORIEN


def gueltige_konten() -> dict[str, dict]:
    sonder = _SONDERSTAND.get()
    return sonder[1] if sonder else KONTEN


def konto_waehlen(konten: dict | None, ki_konto: str | None, unsicher: bool) -> tuple[str | None, bool]:
    """Konto der KI nur übernehmen, wenn es eines der Konten der Kategorie ist; sonst Standardkonto.
    Ohne Ausnahmen entscheidet die KI nichts -> immer Standardkonto, nie „unsicher“.
    konten = {"standard": "6640" | None, "ausnahmen": [...]} (eine Kategorie aus KONTEN)."""
    konten = konten or {}
    erlaubt = {k for k in [konten.get("standard"), *(konten.get("ausnahmen") or [])] if k}
    return (ki_konto if ki_konto in erlaubt else konten.get("standard"),
            bool(unsicher and konten.get("ausnahmen")))


BEWIRTUNG_KATEGORIEN = {"restaurant_beleg", "restaurant_mit_ec_beleg", "nur_ec_beleg", "bewirtungsbeleg_intern"}

# Felder, die im Feedback einzeln bewertet/korrigiert werden: (key, Label, Typ)
FEEDBACK_FELDER = [
    ("belegnummer", "Belegnummer", "text"),
    ("restaurant_name", "Restaurant / Aussteller", "text"),
    ("adresse", "Adresse", "text"),
    ("mitarbeiter", "Mitarbeiter / Gast", "text"),
    ("datum", "Datum (TT.MM.JJJJ)", "datum"),
    ("uhrzeit", "Uhrzeit (HH:MM)", "text"),
    ("netto", "Netto (€)", "betrag"),
    ("mwst", "MwSt. gesamt (€)", "betrag"),
    ("brutto", "Gesamtbetrag Rechnung (€)", "betrag"),
    ("ec_betrag", "EC-/Kartenbetrag (€)", "betrag"),
    ("trinkgeld", "Trinkgeld (€)", "betrag"),
    ("steuersaetze", "Steuersätze (%)", "saetze"),
    ("konto", "Konto (SKR04-Nr.)", "konto"),
]

_LEER = {"", "null", "none", "-", "–"}


# ---------------------------------------------------------------------------
# Cent-genaues Rechnen. Alle Summen/Differenzen laufen über Decimal (keine Float-Fehler wie
# 0,1 + 0,2 = 0,30000000000000004) und werden kaufmännisch auf Cent gerundet.
# ---------------------------------------------------------------------------

# Toleranzen: Kassen runden die MwSt. oft pro Position statt auf die Summe -> wenige Cent Differenz
# sind normal und kein Lesefehler. Alles darüber -> Nachfrage.
TOLERANZ_SUMME = 0.02  # € – Steuerzeilen gegen Gesamtbetrag, EC gegen Rechnung
TOLERANZ_ZEILE = 0.03  # € – MwSt. einer Zeile gegen Satz × Netto


def _d(x) -> Decimal:
    return Decimal(str(x))


def _cent(x: Decimal) -> float:
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def summe(werte) -> float:
    return _cent(sum((_d(w) for w in werte), Decimal(0)))


def differenz(a, b) -> float:
    return _cent(_d(a) - _d(b))


def mwst_aus_netto(netto, satz) -> float:
    """19 % auf 100,00 netto -> 19,00"""
    return _cent(_d(netto) * _d(satz) / 100)


def mwst_aus_brutto(brutto, satz) -> float:
    """In 119,00 brutto enthaltene 19 % -> 19,00"""
    return _cent(_d(brutto) * _d(satz) / (100 + _d(satz)))


# ---------------------------------------------------------------------------
# Normalisierung (für Modell-Ausgabe UND Nutzer-Korrekturen)
# ---------------------------------------------------------------------------

def parse_betrag(value):
    """'12,50 €', '1.234,56', 12.5, '' -> float | None"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    s = str(value).strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if s.lower() in _LEER:
        return None
    if "," in s and "." in s:
        # Das zuletzt stehende Zeichen ist das Dezimaltrennzeichen
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def parse_datum(value):
    """'2026-11-17', '17.11.2026', '17.11.26' -> 'YYYY-MM-DD' | None"""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    s = str(value).strip()
    if s.lower() in _LEER:
        return None
    for fmt, teil in (("%Y-%m-%d", s[:10]), ("%d.%m.%Y", s), ("%d.%m.%y", s), ("%d/%m/%Y", s)):
        try:
            return datetime.strptime(teil, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_text(value):
    if value is None:
        return None
    s = str(value).strip()
    return None if s.lower() in _LEER else s


def parse_saetze(value):
    """[7, 19], '7, 19', '19%' -> sortierte Liste von Zahlen"""
    if value is None:
        return []
    if isinstance(value, (int, float)):
        value = [value]
    if isinstance(value, str):
        value = [value]
    # Aus jedem Element die Zahlen ziehen ("7%", "7 und 19", "7,19", 19.0).
    # Komma gilt hier als Trennzeichen zwischen Sätzen, nur Punkt als Dezimaltrenner.
    teile = []
    for v in value:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            teile.append(v)
        else:
            teile.extend(re.findall(r"\d+(?:\.\d+)?", str(v)))
    value = teile
    result = set()
    for v in value:
        b = parse_betrag(v)
        if b is not None:
            result.add(int(b) if float(b).is_integer() else b)
    return sorted(result)


def parse_konto(value):
    """'6640', '6640 · Bewirtungskosten', 6640 -> '6640'; ohne vierstellige Nummer -> None"""
    if value is None or isinstance(value, bool):
        return None
    treffer = re.search(r"(?<!\d)\d{4}(?!\d)", str(value))
    return treffer.group() if treffer else None


def normalisieren(feld_typ, value):
    if feld_typ == "konto":
        return parse_konto(value)
    if feld_typ == "betrag":
        return parse_betrag(value)
    if feld_typ == "datum":
        return parse_datum(value)
    if feld_typ == "saetze":
        return parse_saetze(value)
    return parse_text(value)


def werte_gleich(feld_typ, a, b):
    """Vergleich nach Normalisierung (bei Text: Groß-/Kleinschreibung & Leerzeichen egal)."""
    a, b = normalisieren(feld_typ, a), normalisieren(feld_typ, b)
    if feld_typ == "betrag":
        # 0,00 und "nicht vorhanden" gelten als gleich (Modell liefert z. B. trinkgeld 0.0 statt null)
        return abs((a or 0.0) - (b or 0.0)) < 0.005
    if feld_typ == "text":
        def norm(x):
            return re.sub(r"\s+", " ", x).casefold() if x else None
        return norm(a) == norm(b)
    return a == b


# ---------------------------------------------------------------------------
# Deutsche Anzeige (DIN 5008): 04.09.2026, 18:30, 1.234,50
# Gespeichert wird weiterhin ISO (2026-09-04, 133.4) – nur die Oberfläche ist deutsch.
# ---------------------------------------------------------------------------

_ISO_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def betrag_de(value: float) -> str:
    """1234.5 -> '1.234,50'"""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def datum_de(value) -> str:
    """'2026-09-04' -> '04.09.2026' (andere Werte unverändert)."""
    if not value:
        return ""
    s = str(value)
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if _ISO_DATUM.match(s) else s


def jetzt_iso() -> str:
    """Jetzt in deutscher Zeit, ohne Zeitzonen-Angabe ('2026-11-27T14:05:00'). Die Cloud läuft auf UTC – bis
    27.11.2026 stehen gespeicherte Zeitpunkte aus der Cloud deshalb in UTC (eine bzw. zwei Stunden früher)."""
    return datetime.now(ZoneInfo("Europe/Berlin")).replace(tzinfo=None).isoformat(timespec="seconds")


def zeitpunkt_de(value) -> str:
    """'2026-11-17T16:20:05' -> '17.11.2026 16:20'"""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return str(value)


def anzeige(value):
    """Wert -> String für Anzeige / Editor, deutsch formatiert (wird von parse_* wieder gelesen)."""
    if value is None:
        return ""
    if isinstance(value, list):
        # Steuersätze: Komma ist hier Trennzeichen, deshalb keine Dezimalkommas (5.5 bleibt 5.5)
        return ", ".join(
            str(int(v)) if isinstance(v, float) and v.is_integer() else str(v) for v in value
        )
    if isinstance(value, float):
        return betrag_de(value)
    if isinstance(value, str) and _ISO_DATUM.match(value):
        return datum_de(value)
    return str(value)


# ---------------------------------------------------------------------------
# Pydantic-Modell der Modell-Antwort
# ---------------------------------------------------------------------------

class Steuerzeile(BaseModel):
    """Eine Zeile der MwSt.-Aufstellung, so wie sie auf dem Beleg steht (nichts gerechnet)."""

    satz: float | None = None
    netto: float | None = None
    mwst: float | None = None
    brutto: float | None = None

    @field_validator("satz", "netto", "mwst", "brutto", mode="before")
    @classmethod
    def _zahl(cls, v):
        if isinstance(v, str):
            v = v.replace("%", "")
        return parse_betrag(v)


class BelegAnalyse(BaseModel):
    kategorie: str = "sonstiger_beleg"
    kategorie_unsicher: bool = False
    kategorie_grund: str | None = None
    fehlende_pflichtangaben: list[str] = Field(default_factory=list)  # laut Kategorie-Beschreibung
    ausland: bool = False
    ec_passt_zur_rechnung: bool | None = None  # None = kein EC-Beleg dabei / nicht prüfbar
    lesbar: bool = False
    steuersatz_erkennbar: bool = False
    datum_erkennbar: bool = False
    belegnummer: str | None = None
    restaurant_name: str | None = None
    adresse: str | None = None
    mitarbeiter: str | None = None       # Person, für die der Beleg ausgestellt ist (Gast, Reisender) – nie geraten
    datum: str | None = None
    uhrzeit: str | None = None
    netto: float | None = None
    mwst: float | None = None
    brutto: float | None = None
    trinkgeld: float | None = None
    ec_betrag: float | None = None
    steuerzeilen: list[Steuerzeile] = Field(default_factory=list)
    steuersaetze: list[float] = Field(default_factory=list)
    hinweise: list[str] = Field(default_factory=list)
    konto: str | None = None             # SKR04-Nr.; die KI wählt nur bei Konto-Ausnahmen, sonst setzt der Code
    konto_unsicher: bool = False
    konto_grund: str | None = None
    korrekturen: list[str] = Field(default_factory=list)  # nur vom Code gesetzt (Umdeutungen), nie vom Modell

    @field_validator("kategorie", mode="before")
    @classmethod
    def _kategorie(cls, v):
        s = str(v or "").strip().lower().replace("-", "_").replace(" ", "_")
        kategorien = gueltige_kategorien()
        if s in kategorien:
            return s
        eingabe = str(v).strip().casefold()
        for key, label in kategorien.items():  # Toleranz: Label statt Schlüssel, auch ohne "Bewirtung: "
            if eingabe in (label.casefold(), label.split(": ", 1)[-1].casefold()):
                return key
        return "sonstiger_beleg"

    @field_validator("netto", "mwst", "brutto", "trinkgeld", "ec_betrag", mode="before")
    @classmethod
    def _betrag(cls, v):
        return parse_betrag(v)

    @field_validator("datum", mode="before")
    @classmethod
    def _datum(cls, v):
        return parse_datum(v)

    @field_validator("konto", mode="before")
    @classmethod
    def _konto(cls, v):
        return parse_konto(v)

    @field_validator("belegnummer", "restaurant_name", "adresse", "mitarbeiter", "uhrzeit", "kategorie_grund",
                     "konto_grund", mode="before")
    @classmethod
    def _text(cls, v):
        return parse_text(v)

    @field_validator("steuersaetze", mode="before")
    @classmethod
    def _saetze(cls, v):
        return parse_saetze(v)

    @field_validator("hinweise", "fehlende_pflichtangaben", mode="before")
    @classmethod
    def _hinweise(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return [str(x) for x in v if str(x).strip()]

    @field_validator("steuerzeilen", mode="before")
    @classmethod
    def _zeilen(cls, v):
        if not isinstance(v, list):
            return []
        return [z for z in v if isinstance(z, dict)]

    @field_validator("ec_passt_zur_rechnung", mode="before")
    @classmethod
    def _bool_oder_none(cls, v):
        if v is None or (isinstance(v, str) and v.strip().lower() in _LEER):
            return None
        if isinstance(v, str):
            return v.strip().lower() in {"true", "ja", "yes", "1"}
        return bool(v)

    @field_validator("lesbar", "steuersatz_erkennbar", "datum_erkennbar", "kategorie_unsicher", "ausland",
                     "konto_unsicher", mode="before")
    @classmethod
    def _bool(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in {"true", "ja", "yes", "1"}
        return bool(v)

    @model_validator(mode="after")
    def _ableiten(self):
        """Summen und Trinkgeld rechnet der Code, nicht das Modell (LLMs verrechnen sich). Cent-genau (Decimal)."""
        self.korrekturen = []
        self._summen_abgleichen()
        zeilen = self.steuerzeilen
        if zeilen and all(z.mwst is not None for z in zeilen):
            self.mwst = summe(z.mwst for z in zeilen)
            netto = [z.netto if z.netto is not None else (differenz(z.brutto, z.mwst) if z.brutto is not None else None)
                     for z in zeilen]
            if all(n is not None for n in netto):
                self.netto = summe(netto)
        if zeilen:
            self.steuersaetze = parse_saetze(self.steuersaetze + [z.satz for z in zeilen if z.satz is not None])
        if self.ec_betrag is not None and self.brutto is not None:
            # Trinkgeld = EC minus Rechnung; ein vom Modell selbst errechneter Wert wird ersetzt
            diff = differenz(self.ec_betrag, self.brutto)
            self.trinkgeld = diff if diff > 0 else None
        self._konto_festlegen()
        return self

    def _konto_festlegen(self) -> None:
        regeln = gueltige_konten().get(self.kategorie)
        self.konto, self.konto_unsicher = konto_waehlen(regeln, self.konto, self.konto_unsicher)
        if not (regeln or {}).get("ausnahmen"):
            self.konto_grund = None  # ohne Ausnahmen hat die KI nichts zu begründen

    @staticmethod
    def _zeilen_summe(zeilen) -> float | None:
        teile = []
        for z in zeilen:
            if z.brutto is not None:
                teile.append(z.brutto)
            elif z.netto is not None and z.mwst is not None:
                teile.append(summe([z.netto, z.mwst]))
            else:
                return None
        return summe(teile)

    def _summen_abgleichen(self) -> None:
        """Löst zwei typische, rechnerisch EINDEUTIGE Ablesefehler auf (sonst bleibt alles wie abgelesen):

        a) Spalten verwechselt: Kassenbons drucken pro Satz mal Netto, mal Brutto. Wurde Brutto als Netto
           gelesen, passt die MwSt. nur zum Brutto (20,00 × 19/119 = 3,19 statt 20,00 × 19 % = 3,80).
        b) Gesamtbetrag inkl. Trinkgeld: Steht ein Trinkgeld auf dem Beleg und ergibt
           Steuerzeilen + Trinkgeld exakt den abgelesenen Gesamtbetrag, war das die Zahlsumme, nicht die Rechnung.

        Übernommen wird eine Deutung nur, wenn danach die Steuerzeilen cent-genau zum Gesamtbetrag passen.
        Die unveränderte Lesung hat Vorrang. Jede Umdeutung wird in `korrekturen` begründet."""
        if not self.steuerzeilen or self.brutto is None:
            return
        trinkgeld = self.trinkgeld if self.trinkgeld and self.trinkgeld > 0 else None

        umgedeutet_zeilen, umgedeutet = [], []
        for z in self.steuerzeilen:
            z = z.model_copy()
            if z.satz and z.netto is not None and z.mwst is not None and z.brutto is None:
                passt_als_netto = abs(mwst_aus_netto(z.netto, z.satz) - z.mwst) <= TOLERANZ_ZEILE
                passt_als_brutto = abs(mwst_aus_brutto(z.netto, z.satz) - z.mwst) <= TOLERANZ_ZEILE
                if passt_als_brutto and not passt_als_netto:
                    z.brutto, z.netto = z.netto, differenz(z.netto, z.mwst)
                    umgedeutet.append(z)
            umgedeutet_zeilen.append(z)

        varianten = [(self.steuerzeilen, [])]
        if umgedeutet:
            varianten.append((umgedeutet_zeilen, umgedeutet))
        for zeilen, geaendert in varianten:
            rechnung = self._zeilen_summe(zeilen)
            if rechnung is None:
                continue
            passt = abs(rechnung - self.brutto) <= TOLERANZ_SUMME
            mit_trinkgeld = trinkgeld is not None and abs(summe([rechnung, trinkgeld]) - self.brutto) <= TOLERANZ_SUMME
            if not (passt or mit_trinkgeld):
                continue
            if not geaendert and passt:
                return  # alles stimmt wie abgelesen
            self.steuerzeilen = list(zeilen)
            for z in geaendert:
                self.korrekturen.append(
                    f"{z.satz:g} %: abgelesener Betrag {betrag_de(z.brutto)} € ist brutto, nicht netto "
                    f"(MwSt. {betrag_de(z.mwst)} € = {z.satz:g}/{100 + z.satz:g} davon). "
                    f"Netto daraus: {betrag_de(z.netto)} €."
                )
            if not passt and mit_trinkgeld:
                self.korrekturen.append(
                    f"Abgelesener Gesamtbetrag {betrag_de(self.brutto)} € enthält das aufgedruckte Trinkgeld "
                    f"{betrag_de(trinkgeld)} €. Rechnungsbetrag laut Steuerzeilen: {betrag_de(rechnung)} €."
                )
                if self.ec_betrag is None:
                    self.ec_betrag = self.brutto  # gezahlte Summe inkl. Trinkgeld
                self.brutto = rechnung
            return

    @property
    def ist_bewirtung(self) -> bool:
        return self.kategorie in BEWIRTUNG_KATEGORIEN

    def gesamtbetrag(self) -> float | None:
        if self.ec_betrag is not None and (self.brutto is None or self.ec_betrag >= self.brutto):
            return self.ec_betrag
        if self.brutto is None:
            return None
        return summe([self.brutto, self.trinkgeld or 0])

    def bewirtungsdaten(self) -> dict:
        """Anzeige-Daten – im Code abgeleitet, nicht doppelt vom Modell."""
        if not self.ist_bewirtung:
            return {
                "Belegnummer": self.belegnummer,
                "Aussteller": self.restaurant_name,
                "Adresse": self.adresse,
                "Mitarbeiter / Gast": self.mitarbeiter,
                "Datum": self.datum,
                "Netto": self.netto,
                "MwSt.": self.mwst,
                "Steuersätze": self.steuersaetze,
                "Gesamtbetrag": self.brutto,
            }
        return {
            "Belegnummer": self.belegnummer,
            "Restaurant": self.restaurant_name,
            "Adresse": self.adresse,
            "Tag der Bewirtung": self.datum,
            "Netto": self.netto,
            "MwSt.": self.mwst,
            "Steuersätze": self.steuersaetze,
            "Brutto (Rechnung)": self.brutto,
            "EC-/Kartenbetrag": self.ec_betrag,
            "Trinkgeld": self.trinkgeld,
            "Gesamtbetrag inkl. Trinkgeld": self.gesamtbetrag(),
            **({"Mitarbeiter / Gast": self.mitarbeiter} if self.mitarbeiter else {}),
        }
