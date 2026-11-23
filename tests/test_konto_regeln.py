"""Konto-Ausnahmen je Kategorie: Prompt, Fingerabdruck, Auswahl der KI absichern, Nachfrage, Doppelt-Lesen."""
import pytest

from beleg_schema import KONTEN, BelegAnalyse, konten_registrieren, parse_konto
from checks import abweichungen, nachfragen_gruende, nur_fachliche_gruende
from kategorien import (aktueller_stand, als_dokument, ausnahmen_aus_tabelle, konten, konto_regeln,
                        prompt_abschnitt, wissens_hash)

AUSNAHMEN = [{"wenn": "nur ein Gedeck / allein auf Reise", "konto": "6664", "bezeichnung": "Verpflegung AN"},
             {"wenn": "nur Mitarbeiter", "konto": "6130", "bezeichnung": ""}]


def _stand(ausnahmen=()):
    return aktueller_stand([{"schluessel": "restaurant_beleg", "version": 1, "zeitpunkt": "2026-11-21T10:00:00",
                             "beschreibung": "Restaurantrechnung", "skr04_konto": "6640",
                             "skr04_bezeichnung": "Bewirtungskosten", "konto_ausnahmen": list(ausnahmen)}])


@pytest.fixture(autouse=True)
def _konten_leeren():
    yield
    konten_registrieren({})  # globale Registrierung nicht in andere Tests tragen


def test_parse_konto():
    assert parse_konto("6640") == "6640" and parse_konto("6640 · Bewirtungskosten") == "6640"
    assert parse_konto(6640) == "6640" and parse_konto(" ") is None and parse_konto("66400") is None


def test_ohne_ausnahmen_kein_konto_im_prompt():
    assert "Konto" not in prompt_abschnitt(_stand())
    assert wissens_hash(_stand()) == wissens_hash(aktueller_stand([{**_stand()["restaurant_beleg"],
                                                                      "skr04_konto": "", "version": 2}]))


def test_ausnahmen_im_prompt_und_fingerabdruck():
    mit = _stand(AUSNAHMEN)
    zeile = next(z for z in prompt_abschnitt(mit).splitlines() if "Konto (SKR04)" in z)
    assert '"6640" (Bewirtungskosten)' in zeile and '"6664" (Verpflegung AN), wenn nur ein Gedeck' in zeile
    assert '"6130" (ohne Bezeichnung), wenn nur Mitarbeiter' in zeile
    assert wissens_hash(mit) != wissens_hash(_stand())
    assert konten(mit)["restaurant_beleg"] == {"standard": "6640", "ausnahmen": ["6664", "6130"]}
    assert "Ausnahme: 6664 · Verpflegung AN, wenn nur ein Gedeck" in als_dokument(mit["restaurant_beleg"])


def test_unvollstaendige_ausnahmen_zaehlen_nicht():
    assert konto_regeln({"skr04_konto": "6640", "konto_ausnahmen": [{"wenn": "", "konto": "6664"},
                                                                     {"wenn": "x", "konto": "66"}]}) == ""


def test_ki_darf_nur_erlaubte_konten_waehlen():
    konten_registrieren(konten(_stand(AUSNAHMEN)))
    basis = {"kategorie": "restaurant_beleg"}
    assert BelegAnalyse.model_validate({**basis, "konto": "6664"}).konto == "6664"
    assert BelegAnalyse.model_validate({**basis, "konto": "6815"}).konto == "6640"  # nicht erlaubt -> Standard
    assert BelegAnalyse.model_validate(basis).konto == "6640"
    unsicher = BelegAnalyse.model_validate({**basis, "konto_unsicher": True, "konto_grund": "2 Gerichte, 1 Getränk"})
    assert unsicher.konto_unsicher and unsicher.konto == "6640"
    gruende = nachfragen_gruende(unsicher, [])
    assert "Konto unsicher: 2 Gerichte, 1 Getränk" in gruende
    assert nur_fachliche_gruende(BelegAnalyse.model_validate(
        {**basis, "konto_unsicher": True, "lesbar": True, "steuersatz_erkennbar": True, "steuerzeilen": [{"satz": 19}],
         "brutto": 10, "datum": "2026-11-20"}), []) is True


def test_ohne_ausnahmen_entscheidet_die_ki_nichts():
    konten_registrieren(konten(_stand()))
    a = BelegAnalyse.model_validate({"kategorie": "restaurant_beleg", "konto": "6664", "konto_unsicher": True})
    assert (a.konto, a.konto_unsicher) == ("6640", False)
    assert BelegAnalyse.model_validate({"kategorie": "tankbeleg"}).konto is None  # kein Konto festgelegt
    assert "tankbeleg" in KONTEN


def test_doppelt_lesen_vergleicht_das_konto():
    konten_registrieren(konten(_stand(AUSNAHMEN)))
    a = BelegAnalyse.model_validate({"kategorie": "restaurant_beleg", "konto": "6664"})
    b = BelegAnalyse.model_validate({"kategorie": "restaurant_beleg"})
    assert abweichungen(a, b) == {"Konto": ("6664", "6640")}


def test_ausnahmen_aus_tabelle():
    zeilen = [{"wenn": " nur Mitarbeiter ", "konto": "6130", "bezeichnung": None},
              {"wenn": None, "konto": float("nan"), "bezeichnung": None},       # leere Zeile
              {"wenn": "Teamessen", "konto": "6644", "bezeichnung": "eigener Name"}]
    ausnahmen, fehler = ausnahmen_aus_tabelle(zeilen)
    assert fehler is None
    assert ausnahmen[0] == {"wenn": "nur Mitarbeiter", "konto": "6130", "bezeichnung": ""}  # nicht in der Vorlage
    assert ausnahmen[1]["bezeichnung"] == "eigener Name"
    assert ausnahmen_aus_tabelle([{"wenn": "x", "konto": "6664"}])[0][0]["bezeichnung"].startswith("Reisekosten")
    _, fehler = ausnahmen_aus_tabelle([{"wenn": "", "konto": "6664"}, {"wenn": "x", "konto": "66"}])
    assert "Zeile 1" in fehler and "Zeile 2" in fehler


# --- Probelauf: Konto je Variante -----------------------------------------------------------------------

def test_probelauf_waehlt_konto_je_variante(monkeypatch):
    import pipeline
    import testlauf

    vorher = konten(_stand())            # nur Standardkonto
    nachher = konten(_stand(AUSNAHMEN))  # neue, noch nicht gespeicherte Ausnahme 6664
    assert testlauf.konten_vereinigen(vorher, nachher)["restaurant_beleg"] == {
        "standard": None, "ausnahmen": ["6130", "6640", "6664"]}

    def lesen(*_a, **_k):  # die KI wählt in beiden Läufen die Ausnahme und ist unsicher
        a = BelegAnalyse.model_validate({"kategorie": "restaurant_beleg", "konto": "6664", "konto_unsicher": True,
                                         "konto_grund": "1 Gericht"})
        return pipeline.LeseErgebnis(a, "{}", "m", [], gruende=["Konto unsicher: 1 Gericht"])
    monkeypatch.setattr(testlauf, "beleg_lesen", lesen)
    monkeypatch.setattr(testlauf, "dateien_zu_bildern", lambda d: ([b""], 1, 1))

    erg = testlauf.ausfuehren([("a.png", b"", "image/png")], {"vorher": "p1", "nachher": "p2"},
                              konten={"vorher": vorher, "nachher": nachher})["a.png"]
    assert (erg["vorher"].konto, erg["vorher"].konto_unsicher, erg["vorher"].nachfrage) == ("6640", False, False)
    assert (erg["nachher"].konto, erg["nachher"].konto_unsicher, erg["nachher"].nachfrage) == ("6664", True, True)
    assert testlauf.zusammenfassung({"a.png": erg}, "nachher", {"restaurant_beleg"})["konten"] == {"6664": 1}
    assert KONTEN == {}  # die Probelauf-Konten waren nur im Lauf gültig, nicht global


def test_probelauf_sonderstand_gilt_nur_im_lauf(monkeypatch):
    """Neue Kategorie/Konten des Probelaufs: gültig in den Lese-Threads der Pipeline, aber nicht für andere
    (gleichzeitige echte Analysen laufen ohne den Sonderstand)."""
    import threading

    import pipeline
    import testlauf
    from beleg_schema import gueltige_kategorien, sonderstand

    gesehen = []

    def analysieren(bilder, modell, system):  # läuft in pipeline.beleg_lesens eigenen Threads
        a = BelegAnalyse.model_validate({"kategorie": "parken", "konto": "6570"})
        gesehen.append((a.kategorie, a.konto))
        return a, "{}", {}
    monkeypatch.setattr(pipeline, "analysieren", analysieren)
    monkeypatch.setattr(pipeline, "kontrast_variante", lambda b: b)
    monkeypatch.setattr(testlauf, "dateien_zu_bildern", lambda d: ([b"x"], 1, 1))

    neben = {}
    with sonderstand({"parken": "Parken"}, {"parken": {"standard": "6570", "ausnahmen": []}}):
        t = threading.Thread(target=lambda: neben.update(k=dict(gueltige_kategorien())))
        t.start()
        t.join()
    assert "parken" not in neben["k"]  # anderer Thread (= andere Sitzung) sieht nichts

    testlauf.ausfuehren([("a.png", b"", "image/png")], {"nachher": "p"},
                        konten={"nachher": {"parken": {"standard": "6570", "ausnahmen": []}}},
                        kategorien={"parken": "Parken"})
    assert gesehen and all(g == ("parken", "6570") for g in gesehen), gesehen
    assert "parken" not in gueltige_kategorien()  # danach wieder der normale Stand
    assert BelegAnalyse.model_validate({"kategorie": "parken"}).kategorie == "sonstiger_beleg"
