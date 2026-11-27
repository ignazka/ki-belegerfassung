"""Ablauf einer Analyse (pipeline.beleg_lesen): doppelt lesen, vergleichen, Schiedsrichter – mit simulierter KI."""
import importlib

import pytest

from beleg_schema import BelegAnalyse
from extraction import AnalyseFehler

# Aral-Tankbeleg aus tests/test_logik.py: stimmig, keine Nachfrage
SAUBER = {"kategorie": "tankbeleg", "lesbar": True, "steuersatz_erkennbar": True, "datum_erkennbar": True,
          "restaurant_name": "Aral Tankstelle", "datum": "2026-08-24", "brutto": 103.27, "ec_betrag": 103.27,
          "steuerzeilen": [{"satz": 19, "netto": 86.78, "mwst": 16.49, "brutto": 103.27}]}
ANDERS = {**SAUBER, "restaurant_name": "Arel Tankstelle"}  # Lesefehler im Text (Rechnung bleibt stimmig)
NOCH_ANDERS = {**SAUBER, "restaurant_name": "Esso Station"}  # deutlich anders (kleine Tippfehler gelten als gleich)


@pytest.fixture
def pipeline(monkeypatch):
    import pipeline as modul
    modul = importlib.reload(modul)  # falls ein UI-Test beleg_lesen ersetzt hat
    monkeypatch.setattr(modul, "kontrast_variante", lambda bild: b"KONTRAST")
    return modul


def ki(pipeline, monkeypatch, original, kontrast, gross=None):
    """Antworten je Lesung: dict -> Analyse, Exception -> Fehler. Gibt die Liste der Aufrufe zurück."""
    aufrufe = []

    def analysieren(bilder, modell, system):
        variante = "gross" if modell == pipeline.MODEL_GROSS else ("kontrast" if bilder[0] == b"KONTRAST" else "original")
        aufrufe.append(variante)
        antwort = {"original": original, "kontrast": kontrast, "gross": gross}[variante]
        if isinstance(antwort, Exception):
            raise antwort
        return BelegAnalyse.model_validate(antwort), "{}", {"tokens": 1}

    monkeypatch.setattr(pipeline, "analysieren", analysieren)
    return aufrufe


def test_gleiche_lesungen_ohne_schiedsrichter(pipeline, monkeypatch):
    aufrufe = ki(pipeline, monkeypatch, SAUBER, SAUBER)
    erg = pipeline.beleg_lesen([b"BILD"])
    assert sorted(aufrufe) == ["kontrast", "original"]
    assert not erg.schiedsrichter and erg.modell == pipeline.MODEL
    assert erg.gruende == [] and erg.abweichungen == {}


def test_abweichung_schiedsrichter_entscheidet(pipeline, monkeypatch):
    aufrufe = ki(pipeline, monkeypatch, SAUBER, ANDERS, gross=SAUBER)
    erg = pipeline.beleg_lesen([b"BILD"])
    assert "gross" in aufrufe and erg.schiedsrichter and erg.modell == pipeline.MODEL_GROSS
    assert erg.abweichungen and erg.ungeklaert == []  # großes Modell bestätigt eine der beiden Lesungen
    assert not any(g.startswith("Unsicher gelesen") for g in erg.gruende)
    assert erg.analyse.restaurant_name == "Aral Tankstelle"


def test_abweichung_bleibt_unklar(pipeline, monkeypatch):
    ki(pipeline, monkeypatch, SAUBER, ANDERS, gross=NOCH_ANDERS)
    erg = pipeline.beleg_lesen([b"BILD"])
    assert erg.ungeklaert  # großes Modell liest etwas Drittes -> Mensch muss schauen
    assert any(g.startswith("Unsicher gelesen") for g in erg.gruende)


def test_eine_lesung_fehlt_schiedsrichter_liest(pipeline, monkeypatch):
    aufrufe = ki(pipeline, monkeypatch, SAUBER, RuntimeError("Zeitüberschreitung"), gross=SAUBER)
    erg = pipeline.beleg_lesen([b"BILD"])
    assert "gross" in aufrufe and erg.schiedsrichter
    assert erg.gruende == []


def test_grosses_modell_nicht_erreichbar(pipeline, monkeypatch):
    ki(pipeline, monkeypatch, SAUBER, ANDERS, gross=RuntimeError("503"))
    erg = pipeline.beleg_lesen([b"BILD"])
    assert erg.modell == pipeline.MODEL  # Ergebnis der ersten Lesung gilt …
    assert any("Großes Modell nicht verfügbar" in g for g in erg.gruende)  # … aber mit Nachfrage
    assert any("Doppelt gelesen, Abweichung" in g for g in erg.gruende)


def test_alle_lesungen_fehlgeschlagen(pipeline, monkeypatch):
    fehler = RuntimeError("kein Netz")
    ki(pipeline, monkeypatch, fehler, fehler, gross=fehler)
    with pytest.raises(AnalyseFehler):
        pipeline.beleg_lesen([b"BILD"])


def test_rechenpruefung_loest_schiedsrichter_aus(pipeline, monkeypatch):
    falsch = {**SAUBER, "brutto": 113.27}  # Gesamtbetrag passt nicht zu den Steuerzeilen
    aufrufe = ki(pipeline, monkeypatch, falsch, falsch, gross=falsch)
    erg = pipeline.beleg_lesen([b"BILD"])
    assert "gross" in aufrufe
    assert any(g.startswith("Rechenprüfung") for g in erg.gruende)


# --- Schiedsrichter überspringen, wenn genaueres Lesen nichts ändert ------------------------------------

def test_nur_fachlicher_grund_ohne_schiedsrichter(pipeline, monkeypatch):
    ausland = {**SAUBER, "ausland": True}
    aufrufe = ki(pipeline, monkeypatch, ausland, ausland, gross=RuntimeError("darf nicht gerufen werden"))
    erg = pipeline.beleg_lesen([b"BILD"])
    assert "gross" not in aufrufe and not erg.schiedsrichter
    assert any("Auslandsbeleg" in g for g in erg.gruende)  # Nachfrage an den Menschen bleibt


def test_fachlich_plus_lesbarer_grund_mit_schiedsrichter(pipeline, monkeypatch):
    beides = {**SAUBER, "ausland": True, "kategorie_unsicher": True, "kategorie_grund": "nur Snacks"}
    aufrufe = ki(pipeline, monkeypatch, beides, beides, gross=beides)
    pipeline.beleg_lesen([b"BILD"])
    assert "gross" in aufrufe


def test_fachlich_aber_lesungen_weichen_ab_mit_schiedsrichter(pipeline, monkeypatch):
    a, b = {**SAUBER, "ausland": True}, {**ANDERS, "ausland": True}
    aufrufe = ki(pipeline, monkeypatch, a, b, gross=a)
    pipeline.beleg_lesen([b"BILD"])
    assert "gross" in aufrufe


def test_einordnung_der_gruende():
    from checks import nur_fachliche_gruende

    def analyse(**x):
        return BelegAnalyse.model_validate({**SAUBER, **x})

    assert not nur_fachliche_gruende(analyse(), [])                                 # gar kein Grund
    assert nur_fachliche_gruende(analyse(ausland=True), [])
    assert nur_fachliche_gruende(analyse(kategorie="nur_ec_beleg"), [])
    assert nur_fachliche_gruende(analyse(steuersaetze=[16], steuerzeilen=[]), [])    # Satz steht so da
    assert not nur_fachliche_gruende(analyse(ausland=True), ["Summe passt nicht"])  # Rechenprüfung: lesen!
    assert not nur_fachliche_gruende(analyse(kategorie_unsicher=True), [])
    assert not nur_fachliche_gruende(analyse(fehlende_pflichtangaben=["Anlass"]), [])
    assert not nur_fachliche_gruende(analyse(ec_passt_zur_rechnung=False), [])
    assert not nur_fachliche_gruende(analyse(lesbar=False), [])


def test_uhrzeit_abweichung_ruft_schiedsrichter(pipeline, monkeypatch):
    aufrufe = ki(pipeline, monkeypatch, {**SAUBER, "uhrzeit": "18:30"}, {**SAUBER, "uhrzeit": "16:30"},
                 gross={**SAUBER, "uhrzeit": "18:30"})
    erg = pipeline.beleg_lesen([b"BILD"])
    assert "gross" in aufrufe and erg.abweichungen == {"Uhrzeit": ("18:30", "16:30")}
    assert erg.ungeklaert == [] and erg.analyse.uhrzeit == "18:30"


def test_nur_grosses_modell_liest_mit_nachfrage(pipeline, monkeypatch):
    fehler = RuntimeError("Zeitüberschreitung")
    ki(pipeline, monkeypatch, fehler, fehler, gross=SAUBER)
    erg = pipeline.beleg_lesen([b"BILD"])
    assert erg.modell == pipeline.MODEL_GROSS
    assert any("ohne Gegenprobe" in g for g in erg.gruende)  # niemand hat gegengelesen -> Mensch schaut


def test_modellaufruf_wiederholt_nur_bei_abgelehnter_anfrage(monkeypatch):
    """Ohne JSON-Vorgabe erneut nur, wenn der Anbieter die Anfrage ablehnt – nicht bei Zeitüberschreitung."""
    import openai

    import extraction

    def fehler_von(art):  # ohne Netzwerk-Objekte erzeugen; für das except zählt nur die Klasse
        return art.__new__(art)

    for fehler, erwartet in [(fehler_von(openai.BadRequestError), 2), (fehler_von(openai.APITimeoutError), 1)]:
        aufrufe = []

        def create(fehler=fehler, aufrufe=aufrufe, **kwargs):
            aufrufe.append(kwargs)
            if "response_format" in kwargs:
                raise fehler
            return "ok"

        client = type("C", (), {})()
        client.chat = type("Ch", (), {})()
        client.chat.completions = type("Co", (), {"create": staticmethod(create)})()
        monkeypatch.setattr(extraction, "get_client", lambda: client)
        if erwartet == 2:
            assert extraction._modell_aufrufen("x", "m") == "ok"
        else:
            with pytest.raises(openai.APITimeoutError):
                extraction._modell_aufrufen("x", "m")
        assert len(aufrufe) == erwartet


def test_mitarbeiter_wird_doppelt_gelesen(pipeline, monkeypatch):
    """Mitarbeiter/Gast ist Vergleichsfeld: „Herr Max Muster“ vs. „Max Muster“ ist gleich, ein anderer Name nicht."""
    ki(pipeline, monkeypatch, {**SAUBER, "mitarbeiter": "Herr Max Muster"}, {**SAUBER, "mitarbeiter": "Max Muster"})
    assert not pipeline.beleg_lesen([b"BILD"]).schiedsrichter
    ki(pipeline, monkeypatch, {**SAUBER, "mitarbeiter": "Max Muster"}, {**SAUBER, "mitarbeiter": "Erika Beispiel"},
       gross={**SAUBER, "mitarbeiter": "Max Muster"})
    erg = pipeline.beleg_lesen([b"BILD"])
    assert erg.schiedsrichter and "Mitarbeiter" in erg.abweichungen and erg.ungeklaert == []
    assert erg.analyse.mitarbeiter == "Max Muster"


def test_schiedsrichter_abgeschaltet(pipeline, monkeypatch):
    """Schalter aus: großes Modell wird nie gefragt, Zweifel gehen als Nachfrage an den Menschen."""
    aufrufe = ki(pipeline, monkeypatch, SAUBER, ANDERS, gross=SAUBER)
    erg = pipeline.beleg_lesen([b"BILD"], schiedsrichter=False)
    assert "gross" not in aufrufe and not erg.schiedsrichter and erg.modell == pipeline.MODEL
    assert erg.ungeklaert == ["Aussteller"]
    assert erg.gruende == ["Unsicher gelesen – Aussteller: Aral Tankstelle / Arel Tankstelle"]
    # nur eine Lesung gelungen -> ohne Gegenprobe zur Nachfrage
    aufrufe = ki(pipeline, monkeypatch, SAUBER, RuntimeError("Zeitüberschreitung"), gross=SAUBER)
    erg = pipeline.beleg_lesen([b"BILD"], schiedsrichter=False)
    assert "gross" not in aufrufe and any(g.startswith("Nur eine Lesung gelungen") for g in erg.gruende)
    # beide gescheitert -> Fehler wie ohne Schalter
    ki(pipeline, monkeypatch, RuntimeError("a"), RuntimeError("b"))
    with pytest.raises(AnalyseFehler):
        pipeline.beleg_lesen([b"BILD"], schiedsrichter=False)
