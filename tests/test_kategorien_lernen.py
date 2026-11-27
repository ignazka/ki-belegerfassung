"""„Aus Korrekturen lernen“: Nachricht an das Modell und Absicherung seiner Antwort (kategorien.py)."""
import json

from kategorien import LERN_FELDER, URSACHEN, aktueller_stand, lern_antwort_pruefen, lern_nachricht

STAND = aktueller_stand([{"schluessel": "reisekosten", "name": "Reisekosten", "status": "entwurf",
                          "beschreibung": "Flug, Bahn", "zeitpunkt": "2026-11-17T10:00:00", "version": 1}])


def test_nachricht_enthaelt_wissen_und_faelle():
    faelle = [{"nr": 1, "kommentar_mensch": "Zimmerbuchung"}]
    text = lern_nachricht(STAND, faelle)
    assert '"uebernachtung"' in text and "KATEGORIE-WISSEN" in text
    assert json.loads(text.split("FÄLLE:\n", 1)[1]) == faelle


def test_antwort_wird_abgesichert():
    antwort = {
        "faelle": [{"nr": 1, "ursache": "regel", "kurz": "Zimmer"}, {"nr": 2, "ursache": "quatsch"},
                   {"nr": 9, "ursache": "regel"}, "kein dict"],
        "vorschlaege": [
            {"kategorie": "uebernachtung", "feld": "erkennungsmerkmale", "text": " Zimmer = Übernachtung ",
             "faelle": [1], "sicherheit": "hoch"},
            {"kategorie": "reisekosten", "feld": "abgrenzung", "text": "Flug ist Reise", "faelle": [1, 2, 99],
             "sicherheit": "hoch"},
            {"kategorie": "gibtsnicht", "feld": "abgrenzung", "text": "x"},
            {"kategorie": "uebernachtung", "feld": "name", "text": "x"},
            {"kategorie": "uebernachtung", "feld": "abgrenzung", "text": "   "},
        ],
        "rueckfragen": ["Frühstück?", "  "],
    }
    erg = lern_antwort_pruefen(antwort, STAND, anzahl_faelle=2)
    assert [f["nr"] for f in erg["faelle"]] == [1, 2]  # Nr. 9 außerhalb, „kein dict“ verworfen
    assert erg["faelle"][1]["ursache"] == "unklar"     # unbekannte Ursache
    assert [v["kategorie"] for v in erg["vorschlaege"]] == ["uebernachtung", "reisekosten"]
    einzel, mehrere = erg["vorschlaege"]
    assert einzel["text"] == "Zimmer = Übernachtung"
    assert einzel["sicherheit"] == "niedrig"            # ein Fall ist kein Muster – egal was das Modell sagt
    assert mehrere["faelle"] == [1, 2] and mehrere["sicherheit"] == "hoch"
    assert erg["rueckfragen"] == ["Frühstück?"]


def test_leere_antwort():
    assert lern_antwort_pruefen({}, STAND, 3) == {"faelle": [], "vorschlaege": [], "rueckfragen": []}


def test_konstanten():
    assert "nachfragen_wenn" in LERN_FELDER and "beschreibung" not in LERN_FELDER
    assert set(URSACHEN) >= {"regel", "nachfrage_zu_streng", "lesefehler", "bewertung_widerspruechlich", "unklar"}


def test_hoechste_version_gilt_auch_bei_verdrehter_uhrzeit():
    # Cloud speichert UTC, ein lokales Skript MEZ -> die ältere Version kann die spätere Uhrzeit haben
    from kategorien import aktueller_stand
    versionen = [
        {"zeitpunkt": "2026-11-27T13:58:42", "schluessel": "reise", "name": "Reise", "status": "entwurf", "version": 2},
        {"zeitpunkt": "2026-11-27T13:04:08", "schluessel": "reise", "name": "Reise", "status": "aktiv", "version": 3},
    ]
    assert aktueller_stand(versionen)["reise"]["status"] == "aktiv"
