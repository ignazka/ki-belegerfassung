"""Abgleich von Belegen mit dem Google-Kalender der Firma.

Zu Bewirtungen und Übernachtungen muss es einen passenden Kalendertermin geben. Findet die App keinen,
geht der Beleg zur Nachfrage. Ist ein Termin gefunden, liefert er Teilnehmer und Anlass als Vorschlag
für den Bewirtungsbeleg.

Zugang (Laden der Termine in storage.kalender_abgleichen, dieses Modul enthält nur Lesen + Regeln):
- Normalfall: In der Seitenleiste „Kalender verbinden“ (kalender_verbindung.py) – eigener Google-Zugang nur
  zum Lesen, gespeichert in kalender_zugang/; abgeglichen werden alle dort gewählten Kalender (doppelte
  Termine zählen einmal).
- Älterer Weg, nur wenn in der App nichts verbunden ist: Secrets
      [kalender]
      kalender_id = "firma@group.calendar.google.com"
      refresh_token = "…"   # optional, sonst der Drive-Token (drive_token_holen.py fragt beide Rechte an)

Regeln (bewusst einfach und nachvollziehbar, Werte unten anpassbar):
- Bewirtung: Termin am Belegdatum. Passend, wenn Restaurantname/Stadt in Titel, Ort oder Beschreibung
  vorkommt ODER er zeitlich zur Uhrzeit auf dem Beleg passt (beginnt höchstens BEWIRTUNG_VORHER_H Stunden
  vor der Zahlung, endet frühestens BEWIRTUNG_NACHHER_H Stunden davor) UND nach Essen klingt
  (ESSENS_HINWEISE). Uhrzeit allein reicht nicht – sonst gälte z. B. „Zahnarzt“ als Geschäftsessen.
- Übernachtung: Termin im Zeitraum ÜBERNACHTUNG_TAGE vor bis 1 Tag nach dem Belegdatum, dessen Titel/Ort
  Hotel bzw. Stadt nennt – oder eine Reise: mehrtägig (ganztägig mind. 2 Tage, mit Uhrzeit mind. 20 Std.) oder
  ganztägig mit Reise-Hinweis im Titel. Mehrere Reisen -> die eine mit Reise-Hinweis, sonst Nachfrage.

Was NIE zählt (auch nicht als Kandidat in der Nachfrage), weil sonst Feiertage und Geburtstage als „Reise“
gälten:
- Feiertags- und Kontakt-Geburtstagskalender von Google (kalender_relevant, schon beim Laden ausgelassen);
- Termine der Art Geburtstag, Abwesend, Fokuszeit, Arbeitsort (Google-Feld eventType);
- ganztägige Termine, die nach Abwesenheit klingen (ABWESENHEIT: Urlaub, Ferien, Feiertag, Geburtstag …) –
  egal aus welchem Kalender, denn Geburtstage und Ferien stehen oft in ganz normalen Kalendern.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from beleg_schema import BEWIRTUNG_KATEGORIEN, BelegAnalyse, datum_de

ZEITZONE = ZoneInfo("Europe/Berlin")
BEWIRTUNG_VORHER_H = 5     # Termin darf so viele Stunden vor der Zahlung beginnen
BEWIRTUNG_NACHHER_H = 1    # ... und muss spätestens so viele Stunden vor der Zahlung geendet haben (sonst zu früh)
UEBERNACHTUNG_TAGE = 14    # Hotelrechnung kommt am Abreisetag; Reise kann bis zu so viele Tage vorher beginnen

KALENDER_KATEGORIEN = set(BEWIRTUNG_KATEGORIEN) | {"uebernachtung"}
# Wortanfänge, an denen ein Termin als Essen erkennbar ist (ohne Umlaute, siehe _norm). Dazu jedes Wort,
# das auf „essen“ endet (Abendessen, Arbeitsessen, Teamessen …) – außer „Interessen“ u. Ä.
ESSENS_HINWEISE = ("mittag", "lunch", "dinner", "fruhstuck", "brunch", "bewirtung", "restaurant", "kaffee",
                   "cafe", "bistro", "imbiss")
_KEIN_ESSEN = ("interessen", "messen")
_VOR_STADT = {"in", "nach", "aus", "ab", "bis", "von"}  # „Messe in Essen“ -> Stadt, nicht Mahlzeit
AEHNLICHKEIT_MIN = 0.85  # Tippfehler-Toleranz beim Namensvergleich (1,0 = exakt; „domhoff“/„domhof“ ≈ 0,92)
# Wortteile ganztägiger Termine, die eine Abwesenheit/einen Anlass ohne Reise meinen (ohne Umlaute, siehe _norm)
ABWESENHEIT = ("urlaub", "ferien", "feiertag", "geburtstag", "krank", "elternzeit", "abwesen", "bruckentag",
               "jubilaum", "hochzeit", "namenstag")
# Wortteile, an denen eine Reise erkennbar ist – entscheidet zwischen mehreren mehrtägigen Terminen
REISE_HINWEISE = ("reise", "messe", "konferenz", "kongress", "tagung", "seminar", "schulung", "workshop",
                  "hotel", "flug", "bahn", "einsatz", "montage", "trip", "travel", "summit", "expo")
# Google-eventType, die nie ein Geschäftstermin sind
_IGNORIERTE_ARTEN = {"birthday", "outOfOffice", "focusTime", "workingLocation"}
_FUELLWOERTER = {"gmbh", "co", "kg", "ag", "ug", "mbh", "restaurant", "hotel", "gasthaus", "gaststaette",
                 "cafe", "bar", "und", "der", "die", "das", "im", "am", "zum", "zur", "the", "inh", "inhaber"}


@dataclass
class Termin:
    titel: str
    start: datetime
    ende: datetime
    ganztags: bool = False
    ort: str = ""
    beschreibung: str = ""
    teilnehmer: list[str] = field(default_factory=list)
    link: str = ""
    art: str = ""  # Google eventType („default“, „birthday“, „outOfOffice“ …)

    def zeitraum_de(self) -> str:
        if self.ganztags:
            letzter = (self.ende - timedelta(days=1)).date()
            return (datum_de(self.start.date().isoformat()) if letzter <= self.start.date()
                    else f"{datum_de(self.start.date().isoformat())} – {datum_de(letzter.isoformat())}")
        if self.start.date() == self.ende.date():
            return f"{self.start:%d.%m.%Y %H:%M}–{self.ende:%H:%M}"
        return f"{self.start:%d.%m.%Y %H:%M} – {self.ende:%d.%m.%Y %H:%M}"


@dataclass
class Abgleich:
    status: str                      # "passend" | "kein_termin" | "nicht_noetig" | "nicht_eingerichtet" | "fehler"
    grund: str = ""
    termin: Termin | None = None
    kandidaten: list[Termin] = field(default_factory=list)  # andere Termine im Zeitraum (Hilfe bei Nachfrage)

    @property
    def nachfrage_grund(self) -> str | None:
        if self.status in ("kein_termin", "fehler"):
            return f"Kalender: {self.grund}"
        return None

    def als_dict(self) -> dict:
        def t(x: Termin | None):
            return None if x is None else {"titel": x.titel, "zeitraum": x.zeitraum_de(), "ort": x.ort,
                                           "teilnehmer": x.teilnehmer, "link": x.link}
        return {"status": self.status, "grund": self.grund, "termin": t(self.termin),
                "kandidaten": [t(k) for k in self.kandidaten]}


# ---------------------------------------------------------------------------
# Hilfsfunktionen für den Vergleich
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").casefold())
    text = text.replace("ß", "ss")
    return "".join(c for c in text if not unicodedata.combining(c))


def _woerter(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", _norm(text)) if len(w) >= 4 and w not in _FUELLWOERTER}


def stadt_aus_adresse(adresse: str | None) -> str | None:
    """'Große Himmelsgasse 6, 67346 Speyer' -> 'Speyer'"""
    treffer = re.search(r"\b\d{5}\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß .\-]+)", adresse or "")
    return treffer.group(1).strip(" ,.") if treffer else None


def _aehnlich(beleg_wort: str, termin_wort: str) -> bool:
    """Gleiches Wort – auch mit Tippfehler („Domhoff“) oder abgekürzt („Domh.“ für „Domhof“). Zahlen nur exakt."""
    if beleg_wort == termin_wort:
        return True
    if not (beleg_wort.isalpha() and termin_wort.isalpha()):
        return False
    if beleg_wort.startswith(termin_wort):  # Abkürzung im Termin (mind. 4 Buchstaben, siehe _woerter)
        return True
    return (min(len(beleg_wort), len(termin_wort)) >= 5
            and SequenceMatcher(None, beleg_wort, termin_wort).ratio() >= AEHNLICHKEIT_MIN)


def _gemeinsames_wort(beleg_text: str, termin_woerter: set[str]) -> str | None:
    for w in sorted(_woerter(beleg_text)):
        if any(_aehnlich(w, t) for t in termin_woerter):
            return w
    return None


def _erwaehnt(termin: Termin, analyse: BelegAnalyse) -> str | None:
    """Nennt der Termin den Aussteller (z. B. Restaurant/Hotel) oder die Stadt? -> was gefunden wurde."""
    text = _woerter(f"{termin.titel} {termin.ort} {termin.beschreibung}")
    wort = _gemeinsames_wort(analyse.restaurant_name or "", text)
    if wort:
        return f"Name „{wort}“"
    stadt = stadt_aus_adresse(analyse.adresse)
    if stadt and _gemeinsames_wort(stadt, text):
        return f"Ort „{stadt}“"
    return None


def klingt_nach_essen(termin: Termin) -> bool:
    """Deutet Titel, Ort oder Beschreibung auf ein Essen hin (Mittag, Abendessen, Lunch, Bewirtung …)?
    Das bloße Wort „Essen“ zählt nicht, wenn es die Stadt meint („Messe in Essen“, „45127 Essen“)."""
    for feld in (termin.titel, termin.ort, termin.beschreibung):
        woerter = re.findall(r"[a-z0-9]+", _norm(feld))
        for i, w in enumerate(woerter):
            if w.startswith(ESSENS_HINWEISE):
                return True
            if w == "essen" and i > 0 and (woerter[i - 1] in _VOR_STADT or re.fullmatch(r"\d{5}", woerter[i - 1])):
                continue  # Stadt Essen
            if w.endswith("essen") and not w.endswith(_KEIN_ESSEN):
                return True
    return False


def kalender_relevant(kalender_id: str) -> bool:
    """Feiertagskalender (z. B. de.christian#holiday@…) und Googles Kontakt-Geburtstage enthalten nie Reisen
    oder Bewirtungen – sie werden gar nicht erst geladen."""
    return not re.search(r"#(holiday|contacts|weeknum)@", kalender_id or "")


def _hat_wortteil(termin: Termin, teile: tuple[str, ...]) -> bool:
    woerter = re.findall(r"[a-z0-9]+", _norm(f"{termin.titel} {termin.ort}"))
    return any(teil in w for w in woerter for teil in teile)


def relevant(termin: Termin) -> bool:
    """Kann der Termin überhaupt zu einem Beleg gehören? Nein bei Geburtstagen, Feiertagen, Urlaub & Co."""
    if getattr(termin, "art", "") in _IGNORIERTE_ARTEN:  # getattr: ältere zwischengespeicherte Termine
        return False
    return not (termin.ganztags and _hat_wortteil(termin, ABWESENHEIT))


def klingt_nach_reise(termin: Termin) -> bool:
    return _hat_wortteil(termin, REISE_HINWEISE)


def ist_reise(termin: Termin) -> bool:
    """Mindestens eine Nacht: ganztägig über 2+ Tage bzw. mit Uhrzeit 20+ Std. – oder ganztägig mit Reise-Hinweis.
    Ein einzelner ganztägiger Termin ohne Hinweis (typisch: Feiertag, Geburtstag) ist keine Reise."""
    dauer = termin.ende - termin.start
    if termin.ganztags:
        return dauer >= timedelta(days=2) or klingt_nach_reise(termin)
    return dauer >= timedelta(hours=20)


def _zahlzeit(analyse: BelegAnalyse) -> datetime | None:
    if not analyse.datum:
        return None
    d = date.fromisoformat(analyse.datum)
    stunde, minute = 23, 59  # ohne Uhrzeit: ganzer Tag zählt
    if analyse.uhrzeit and re.match(r"^\d{1,2}:\d{2}", analyse.uhrzeit):
        stunde, minute = (int(x) for x in analyse.uhrzeit[:5].split(":"))
    return datetime(d.year, d.month, d.day, stunde, minute, tzinfo=ZEITZONE)


def zeitraum(analyse: BelegAnalyse) -> tuple[datetime, datetime] | None:
    """Zeitraum, in dem nach Terminen gesucht wird."""
    if not analyse.datum:
        return None
    d = date.fromisoformat(analyse.datum)
    beginn = datetime(d.year, d.month, d.day, tzinfo=ZEITZONE)
    if analyse.kategorie == "uebernachtung":
        return beginn - timedelta(days=UEBERNACHTUNG_TAGE), beginn + timedelta(days=2)
    return beginn, beginn + timedelta(days=1)


# ---------------------------------------------------------------------------
# Abgleich (reine Logik, ohne API – gut testbar)
# ---------------------------------------------------------------------------

def abgleichen(analyse: BelegAnalyse, termine: list[Termin]) -> Abgleich:
    if analyse.kategorie not in KALENDER_KATEGORIEN:
        return Abgleich("nicht_noetig")
    if not analyse.datum:
        return Abgleich("kein_termin", "ohne Belegdatum kein Abgleich möglich.")
    termine = [t for t in termine if relevant(t)]  # Geburtstage, Feiertage, Urlaub … zählen nie
    if analyse.kategorie == "uebernachtung":
        return _abgleich_uebernachtung(analyse, termine)
    return _abgleich_bewirtung(analyse, termine)


def _abgleich_bewirtung(analyse: BelegAnalyse, termine: list[Termin]) -> Abgleich:
    tag = date.fromisoformat(analyse.datum)
    am_tag = [t for t in termine if t.start.date() <= tag <= (t.ende - timedelta(seconds=1)).date()]
    zahlung = _zahlzeit(analyse)
    hat_uhrzeit = bool(analyse.uhrzeit)
    bester, begruendung = None, ""
    nur_zeitlich = []  # passen zur Uhrzeit, klingen aber nicht nach Essen -> zählen nicht
    for t in am_tag:
        erwaehnt = _erwaehnt(t, analyse)
        zeitlich = (not t.ganztags and hat_uhrzeit
                    and zahlung - timedelta(hours=BEWIRTUNG_VORHER_H) <= t.start <= zahlung
                    and t.ende >= zahlung - timedelta(hours=BEWIRTUNG_NACHHER_H))
        if erwaehnt and zeitlich:
            return Abgleich("passend", f"Termin passt zeitlich und nennt {erwaehnt}.", t,
                            [k for k in am_tag if k is not t])
        essen = zeitlich and klingt_nach_essen(t)
        if zeitlich and not essen:
            nur_zeitlich.append(t)
        if (erwaehnt or essen) and bester is None:
            bester = t
            begruendung = (f"Termin nennt {erwaehnt}." if erwaehnt
                           else f"Essenstermin passt zeitlich zur Zahlung um {analyse.uhrzeit} Uhr.")
    if bester:
        return Abgleich("passend", begruendung, bester, [k for k in am_tag if k is not bester])
    if nur_zeitlich:
        titel = ", ".join(f"„{t.titel}“" for t in nur_zeitlich)
        return Abgleich("kein_termin",
                        f"{titel} passt zur Uhrzeit, klingt aber nicht nach einem Essen und nennt weder "
                        "Restaurant noch Ort – bitte prüfen, ob das die Bewirtung war.", None, am_tag)
    if am_tag:
        return Abgleich("kein_termin",
                        f"am {datum_de(analyse.datum)} gibt es {len(am_tag)} Termin(e), aber keiner passt "
                        "zu Uhrzeit, Restaurant oder Ort.", None, am_tag)
    return Abgleich("kein_termin", f"kein Termin am {datum_de(analyse.datum)} gefunden.")


def _abgleich_uebernachtung(analyse: BelegAnalyse, termine: list[Termin]) -> Abgleich:
    tag = date.fromisoformat(analyse.datum)
    # Termin muss bis zum Belegtag (Abreise) reichen bzw. höchstens 1 Tag davor enden
    im_zeitraum = [t for t in termine
                   if t.start.date() <= tag + timedelta(days=1)
                   and (t.ende - timedelta(seconds=1)).date() >= tag - timedelta(days=1)]
    for t in im_zeitraum:
        erwaehnt = _erwaehnt(t, analyse)
        if erwaehnt:
            return Abgleich("passend", f"Termin um den {datum_de(analyse.datum)} nennt {erwaehnt}.", t,
                            [k for k in im_zeitraum if k is not t])
    reisen = [t for t in im_zeitraum if ist_reise(t)]
    mit_hinweis = [t for t in reisen if klingt_nach_reise(t)]
    eindeutig = reisen if len(reisen) == 1 else mit_hinweis if len(mit_hinweis) == 1 else []
    if eindeutig:
        t = eindeutig[0]
        return Abgleich("passend", f"Reise „{t.titel}“ über das Rechnungsdatum.", t,
                        [k for k in im_zeitraum if k is not t])
    if reisen:
        return Abgleich("kein_termin", f"{len(reisen)} mehrtägige Termine kommen in Frage, keiner nennt "
                        "Hotel oder Ort – bitte zuordnen.", None, reisen)
    return Abgleich("kein_termin", f"keine Reise bzw. kein Termin rund um den {datum_de(analyse.datum)} "
                    "mit passendem Hotel oder Ort gefunden.", None, im_zeitraum)


# ---------------------------------------------------------------------------
# Google-Kalender lesen
# ---------------------------------------------------------------------------

def termin_aus_api(e: dict) -> Termin:
    def zeit(feld):
        x = e.get(feld, {})
        if "dateTime" in x:
            return datetime.fromisoformat(x["dateTime"].replace("Z", "+00:00")).astimezone(ZEITZONE), False
        d = date.fromisoformat(x["date"])
        return datetime(d.year, d.month, d.day, tzinfo=ZEITZONE), True
    start, ganztags = zeit("start")
    ende, _ = zeit("end")
    teilnehmer = [a.get("displayName") or a.get("email", "") for a in e.get("attendees", [])
                  if not a.get("resource") and a.get("responseStatus") != "declined"]
    return Termin(titel=e.get("summary") or "(ohne Titel)", start=start, ende=ende, ganztags=ganztags,
                  ort=e.get("location") or "", beschreibung=e.get("description") or "",
                  teilnehmer=teilnehmer, link=e.get("htmlLink") or "", art=e.get("eventType") or "")


def termine_laden(service, kalender_id: str, von: datetime, bis: datetime) -> list[Termin]:
    termine, token = [], None
    while True:
        res = service.events().list(
            calendarId=kalender_id, timeMin=von.isoformat(), timeMax=bis.isoformat(), singleEvents=True,
            orderBy="startTime", maxResults=250, pageToken=token,
        ).execute()
        termine += [termin_aus_api(e) for e in res.get("items", []) if e.get("status") != "cancelled"]
        token = res.get("nextPageToken")
        if not token:
            return termine
