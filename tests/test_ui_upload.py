"""Tab „Belege hochladen“: Analyse starten (Spinner-Durchlauf), Ergebnis, Ablage jeder Analyse."""
import attrappe as A

PNG = ("beleg.png", A.bild_png(), "image/png")


def _analysieren(at, knopf_text):
    A.knopf(at, knopf_text).click().run()  # 1. Durchlauf: Knopf wird zum Spinner
    at.run()                                # 2. Durchlauf: Analyse läuft, danach neu zeichnen
    A.keine_fehler(at)
    return at


def test_ein_beleg_wird_abgelegt_ohne_feedback_formular():
    at = _analysieren(A.app(ki={"dateien": [PNG]}), "Beleg analysieren")
    assert [a["dateiname"] for a in A.SPEICHER["analysen"]] == ["beleg.png"]
    assert A.SPEICHER["analysen"][0]["gruende"] == []
    assert any("Alles stimmig" in s.value for s in at.success)
    assert any("Prüfen und korrigieren im Tab „Belege“" in i.value and "Ungeprüft" in i.value for i in at.info)
    assert not any(b.label == "Feedback speichern" for b in at.button)
    assert A.SPEICHER["feedback"] == []  # geprüft wird nur im Tab „Belege“


def test_nachfrage_wird_angezeigt_und_abgelegt():
    at = _analysieren(A.app(ki={"dateien": [PNG], "gruende": ["Ausland"]}), "Beleg analysieren")
    assert A.SPEICHER["analysen"][0]["gruende"] == ["Ausland"]
    assert any("Nachfrage nötig" in e.value for e in at.error)
    assert any("Nachfragen offen" in i.value for i in at.info)
    assert ":orange-badge[1 offen]" in at.tabs[1].label


def test_stapel():
    dateien = [("a.png", A.bild_png(), "image/png"), ("b.png", A.bild_png() + b"x", "image/png")]
    at = A.app(ki={"dateien": dateien})
    # keine Vorauswahl: erst wählen, vorher ist „Analysieren“ gesperrt
    assert at.radio(key="upload_modus").value is None
    assert next(b for b in at.button if b.key == "laufknopf_analyse").disabled
    assert any("Bitte zuerst wählen" in c.value for c in at.caption)
    at.radio(key="upload_modus").set_value("stapel").run()
    _analysieren(at, "2 Belege analysieren")
    assert sorted(a["dateiname"] for a in A.SPEICHER["analysen"]) == ["a.png", "b.png"]
    assert [m.value for m in at.metric if m.label == "Belege"][0] == "2"


def test_mehrere_dateien_als_ein_beleg():
    dateien = [("rechnung.png", A.bild_png(), "image/png"), ("ec.png", A.bild_png() + b"x", "image/png")]
    at = A.app(ki={"dateien": dateien})
    at.radio(key="upload_modus").set_value("ein_beleg").run()
    _analysieren(at, "Beleg analysieren")
    assert [a["dateiname"] for a in A.SPEICHER["analysen"]] == ["rechnung.png, ec.png"]
    assert len(A.SPEICHER["analysen"][0]["beleg_pfade"]) == 2
