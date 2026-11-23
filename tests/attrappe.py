"""Vorgetäuschte Ablage und KI für Oberflächen-Tests (streamlit.testing.v1.AppTest).

- Alle Lese-/Schreibfunktionen von storage arbeiten auf dem Wörterbuch SPEICHER statt auf Drive/data/.
- Jeder echte Drive-Zugriff (storage._drive) löst einen Fehler aus – ein vergessener Ersatz fällt also auf,
  statt still in die echte Ablage zu schreiben.
- Die KI (pipeline.beleg_lesen, extraction.text_anfrage_json) antwortet mit den Werten aus KI.

Benutzung:  at = attrappe.app(analysen=[...], feedback=[...])  ->  AppTest nach dem ersten Durchlauf.
"""
import io
import itertools
from pathlib import Path

from PIL import Image
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "App.py"
ARTEN = ("analysen", "nachfragen", "feedback", "entscheidungen", "kategorien")
SPEICHER: dict[str, list[dict]] = {art: [] for art in ARTEN}
KI: dict = {}  # analyse (dict), gruende (list) für beleg_lesen; text_antwort (dict) für text_anfrage_json
ANFRAGEN: list[str] = []  # Nachrichten an text_anfrage_json
LADEN: dict[str, int] = {}  # wie oft jede Ablage gelesen wurde (für Tests zur Effizienz)
PAPIERKORB: list[tuple[str, list[str]]] = []  # Aufrufe von beleg_in_papierkorb: (sha, Originaldateien)
# Kalender-Verbindung: "verbindung" (dict wie storage.kalender_verbindung), "liste" (Kalender des Kontos),
# "ruecksprung" (Ergebnis oder Exception für storage.kalender_ruecksprung); AUFRUFE protokolliert Änderungen
KALENDER: dict = {}
KALENDER_AUFRUFE: list[tuple] = []
_uhr = itertools.count()

FELD_KEYS = ["belegnummer", "restaurant_name", "adresse", "datum", "uhrzeit", "netto", "mwst", "brutto",
             "ec_betrag", "trinkgeld", "steuersaetze"]


def bild_png() -> bytes:
    puffer = io.BytesIO()
    Image.new("RGB", (200, 300), "white").save(puffer, "PNG")
    return puffer.getvalue()


def zeitpunkt() -> str:
    n = next(_uhr)
    return f"2099-01-01T{n // 3600 % 24:02d}:{n // 60 % 60:02d}:{n % 60:02d}"


def analyse(kategorie="restaurant_beleg", brutto=26.5, **weitere) -> dict:
    return {"kategorie": kategorie, "lesbar": True, "steuersatz_erkennbar": True, "datum_erkennbar": True,
            "datum": "2026-08-25", "brutto": brutto, **weitere}


def analyse_eintrag(sha, dateiname=None, gruende=(), **analyse_werte) -> dict:
    return {"zeitpunkt": zeitpunkt(), "datei_sha256": sha, "dateiname": dateiname or f"{sha}.png",
            "beleg_pfade": [f"belege/{sha}.png"], "gruende": list(gruende), "analyse": analyse(**analyse_werte),
            "modell": "test-modell", "prompt_version": "test"}


def bewertung(sha, ki_kat="restaurant_beleg", richtige_kat=None, felder_falsch=(), kommentar=None, **weitere) -> dict:
    """Feedback-Eintrag wie nach einer Prüfung. felder_falsch: Feld-Keys, die korrigiert wurden."""
    richtige_kat = richtige_kat or ki_kat
    felder = {k: {"modell": None, "korrekt": None, "richtig": k not in felder_falsch} for k in FELD_KEYS}
    felder["brutto"] = {"modell": 26.5, "korrekt": 26.5 if "brutto" not in felder_falsch else 27.0,
                        "richtig": "brutto" not in felder_falsch}
    return {"zeitpunkt": zeitpunkt(), "datei_sha256": sha, "dateiname": f"{sha}.png",
            "beleg_pfade": [f"belege/{sha}.png"], "modell": "test-modell", "prompt_version": "test",
            "analyse": analyse(ki_kat), "felder": felder, "kommentar": kommentar, "bearbeiter": "test@firma.de",
            "kategorie": {"modell": ki_kat, "korrekt": richtige_kat, "richtig": ki_kat == richtige_kat}, **weitere}


def _anhaengen(art):
    def speichern(eintrag):
        SPEICHER[art].append({"zeitpunkt": zeitpunkt(), **eintrag})
    return speichern


def _gesperrt(*_a, **_k):
    raise RuntimeError("Test: kein Zugriff auf Google Drive / Kalender / KI")


def einsetzen() -> None:
    """Wird im Test-Skript VOR App.py ausgeführt (App importiert die Funktionen beim Start)."""
    import extraction
    import pipeline
    import storage
    from beleg_schema import BelegAnalyse
    from kalender import Abgleich

    storage._drive = _gesperrt  # Sicherheitsnetz
    storage._drive_dienst_bauen = _gesperrt  # paralleles Laden baut eigene Verbindungen
    storage.ablage_pruefen = lambda: None
    storage.ablage_link = lambda: None
    def lader(art):
        def laden():
            LADEN[art] = LADEN.get(art, 0) + 1
            return SPEICHER[art]
        return laden

    for art in ARTEN:
        setattr(storage, f"{art}_laden", lader(art))
    storage.analyse_speichern = _anhaengen("analysen")
    storage.feedback_speichern = _anhaengen("feedback")
    storage.entscheidung_speichern = _anhaengen("entscheidungen")
    storage.kategorie_speichern = _anhaengen("kategorien")
    storage.nachfrage_speichern = lambda e: _anhaengen("nachfragen")(e) or True
    storage.schon_bewertet = lambda sha: any(f.get("datei_sha256") == sha for f in SPEICHER["feedback"])
    storage.beleg_speichern = lambda daten, name, sha: f"belege/{name}"
    storage.beleg_laden = lambda pfad: bild_png()

    def in_papierkorb(sha, beleg_pfade):
        PAPIERKORB.append((sha, list(beleg_pfade)))
        anzahl = 0
        for art in ("analysen", "nachfragen", "feedback", "entscheidungen"):
            vorher = len(SPEICHER[art])
            SPEICHER[art] = [e for e in SPEICHER[art] if e.get("datei_sha256") != sha]
            anzahl += vorher - len(SPEICHER[art])
        return anzahl + len(beleg_pfade)
    storage.beleg_in_papierkorb = in_papierkorb
    storage.kategorie_dokument_ablegen = lambda name, text: "test-doc"
    # Beispielordner vortäuschen: KI["beispiele"] = {ordner: [(name, bytes, mime), …]}
    beispiele = KI.get("beispiele") or {}
    storage.anlage_ordner = lambda: list(beispiele)
    storage.beispielbelege = lambda ordner: [{"name": n, "mime": m, "ref": f"{ordner}/{n}"}
                                             for n, _d, m in beispiele.get(ordner, [])]
    storage.beispielbeleg_laden = lambda ref: next(d for o, liste in beispiele.items() for n, d, _m in liste
                                                   if f"{o}/{n}" == ref)
    storage.beispielbeleg_hochladen = _gesperrt
    storage.kalender_abgleichen = lambda a: Abgleich(status="nicht_eingerichtet")
    _kalender_einsetzen(storage)

    def beleg_lesen(*_a, **_k):
        return pipeline.LeseErgebnis(BelegAnalyse.model_validate(KI.get("analyse") or analyse()), "{}",
                                     "test-modell", [], gruende=list(KI.get("gruende") or []))

    def text_anfrage_json(system, nachricht, modell=None):
        ANFRAGEN.append(nachricht)
        if "text_antwort" not in KI:
            _gesperrt()
        return KI["text_antwort"]

    pipeline.beleg_lesen = beleg_lesen
    extraction.text_anfrage_json = text_anfrage_json

    # Hochgeladene Dateien vortäuschen (KI["dateien"] = [(name, bytes, mime), …]); sonst Original-Uploader
    import streamlit as st
    global _ORIG_UPLOADER
    if _ORIG_UPLOADER is None:
        _ORIG_UPLOADER = st.file_uploader
    if KI.get("dateien"):
        class _Datei:
            def __init__(self, name, daten, typ):
                self.name, self._daten, self.type = name, daten, typ

            def getvalue(self):
                return self._daten

        st.file_uploader = lambda *a, **k: [_Datei(*d) for d in KI["dateien"]]
    else:
        st.file_uploader = _ORIG_UPLOADER

    # AppTest kann ein offenes Fenster (st.dialog) nicht einzeln neu aufbauen, der Browser schon. Wo die App
    # st.rerun(scope="fragment") außerhalb eines Fragment-Durchlaufs aufruft, im Test die ganze Seite neu bauen.
    from streamlit.errors import StreamlitInvalidLayoutContextError
    global _ORIG_RERUN
    if _ORIG_RERUN is None:
        _ORIG_RERUN = st.rerun

    def rerun(*, scope="app"):
        try:
            return _ORIG_RERUN(scope=scope)
        except StreamlitInvalidLayoutContextError:
            return _ORIG_RERUN(scope="app")
    st.rerun = rerun


_ORIG_UPLOADER = None
_ORIG_RERUN = None


def _kalender_einsetzen(storage) -> None:
    def verbindung():
        return KALENDER.get("verbindung")

    def status():
        v = verbindung()
        if not v:
            return "nicht verbunden"
        return f"verbunden ({len(v['kalender'])} Kalender)" if v["kalender"] else "verbunden, noch kein Kalender gewählt"

    def ruecksprung(code, state, benutzer, bearbeiter):
        KALENDER_AUFRUFE.append(("ruecksprung", code, state))
        ergebnis = KALENDER.get("ruecksprung")
        if isinstance(ergebnis, Exception):
            raise ergebnis
        KALENDER["verbindung"] = ergebnis
        return ergebnis

    def auswahl_speichern(kalender, bearbeiter):
        KALENDER_AUFRUFE.append(("auswahl", [k["id"] for k in kalender]))
        KALENDER["verbindung"] = {**KALENDER["verbindung"], "kalender": kalender}

    def trennen(bearbeiter):
        KALENDER_AUFRUFE.append(("trennen",))
        KALENDER["verbindung"] = None

    storage.kalender_verbindung = verbindung
    storage.kalender_status = status
    storage.kalender_verbinden_moeglich = lambda: True
    storage.kalender_anmelde_url = lambda benutzer: "https://accounts.google.com/o/oauth2/v2/auth?test=1"
    storage.kalender_ruecksprung = ruecksprung
    storage.kalender_liste = lambda: KALENDER.get("liste", [])
    storage.kalender_auswahl_speichern = auswahl_speichern
    storage.kalender_trennen = trennen


SKRIPT = f'''
import attrappe
attrappe.einsetzen()
exec(compile(open({str(APP)!r}, encoding="utf-8").read(), {str(APP)!r}, "exec"))
'''


def app(ki: dict | None = None, kalender: dict | None = None, abfrage: dict | None = None, **daten) -> AppTest:
    """Neue App mit leerer bzw. vorgegebener Ablage starten und einmal durchlaufen lassen.
    kalender: Startzustand für KALENDER; abfrage: URL-Parameter (z. B. Rücksprung von Google)."""
    for art in ARTEN:
        SPEICHER[art] = list(daten.get(art, []))
    KI.clear()
    KI.update(ki or {})
    ANFRAGEN.clear()
    LADEN.clear()
    PAPIERKORB.clear()
    KALENDER.clear()
    KALENDER.update(kalender or {})
    KALENDER_AUFRUFE.clear()
    at = AppTest.from_string(SKRIPT, default_timeout=120)
    for name, wert in (abfrage or {}).items():
        at.query_params[name] = wert
    at.run()
    assert not at.exception, [e.message for e in at.exception]
    return at


# --- kleine Helfer für lesbare Tests ----------------------------------------------------------------

def knopf(at, text):
    return next(b for b in at.button if b.label == text)


def radio(at, beginnt_mit):
    return next(r for r in at.radio if r.label.startswith(beginnt_mit))


def feld(at, beginnt_mit):
    return next(t for t in list(at.text_input) + list(at.text_area) if t.label.startswith(beginnt_mit))


def keine_fehler(at):
    assert not at.exception, [e.message for e in at.exception]
