"""Seitenleiste „Kalender verbinden“: Knopf, Rücksprung von Google, Kalender wählen, trennen (vorgetäuscht)."""
import attrappe as A
from kalender_verbindung import VerbindungsFehler

LISTE = [{"id": "annika@firma.de", "name": "Annika", "haupt": True},
         {"id": "firma@group", "name": "Firmenkalender", "haupt": False}]


def _verbindung(kalender=()):
    return {"konto": "annika@firma.de", "kalender": list(kalender), "zeitpunkt": "2026-11-22T10:00:00",
            "bearbeiter": None, "token_ok": True}


def test_nicht_verbunden_zeigt_knopf():
    at = A.app()
    A.keine_fehler(at)
    assert any("Kalender: nicht verbunden" in c.value for c in at.sidebar.caption)
    knopf = at.sidebar.get("link_button")[0]
    assert knopf.proto.label == "Verbinden" and knopf.proto.url.startswith("https://accounts.google.com/")


def test_ruecksprung_verbindet_und_fragt_nach_kalendern():
    at = A.app(kalender={"ruecksprung": _verbindung(), "liste": LISTE},
               abfrage={"code": "c0de", "state": "kal.abc"})
    A.keine_fehler(at)
    assert A.KALENDER_AUFRUFE[0] == ("ruecksprung", "c0de", "kal.abc")
    assert any("Kalender verbunden über annika@firma.de" in s.value for s in at.sidebar.success)
    assert "code" not in at.query_params  # Code nur einmal verwenden
    wahl = at.multiselect(key="kalender_wahl")  # Auswahl öffnet sich von selbst
    wahl.set_value(["firma@group"]).run()
    at.button(key="kalender_wahl_speichern").click().run()
    A.keine_fehler(at)
    assert A.KALENDER_AUFRUFE[-1] == ("auswahl", ["firma@group"])
    assert any("1 Kalender werden jetzt abgeglichen" in s.value for s in at.sidebar.success)


def test_ruecksprung_mit_fehler_zeigt_meldung():
    at = A.app(kalender={"ruecksprung": VerbindungsFehler("Google hat die Anmeldung abgelehnt: x")},
               abfrage={"code": "c0de", "state": "kal.abc"})
    A.keine_fehler(at)
    assert any("abgelehnt" in e.value for e in at.sidebar.error)
    assert any("nicht verbunden" in c.value for c in at.sidebar.caption)


def test_abgebrochen_und_fremder_state():
    at = A.app(abfrage={"error": "access_denied", "state": "kal.abc"})
    assert any("abgebrochen" in w.value for w in at.sidebar.warning)
    at = A.app(abfrage={"code": "x", "state": "nicht-von-uns"})  # z. B. anderer Dienst: nicht anfassen
    assert A.KALENDER_AUFRUFE == [] and not any("Kalender" in w.value for w in at.sidebar.warning)


def test_verbunden_trennen():
    at = A.app(kalender={"verbindung": _verbindung([{"id": "firma@group", "name": "Firmenkalender"}]),
                         "liste": LISTE})
    A.keine_fehler(at)
    at.button(key="kalender_trennen").click().run()
    A.keine_fehler(at)
    assert A.KALENDER_AUFRUFE == [("trennen",)]
    assert any("Kalender getrennt" in s.value for s in at.sidebar.success)
    assert any("Kalender: nicht verbunden" in c.value for c in at.sidebar.caption)
