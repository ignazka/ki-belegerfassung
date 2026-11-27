"""Bekannte Aussteller (merkmale.py) und ihr Abgleich in den Nachfragegründen (checks.py, pipeline.py)."""
import attrappe as A
import merkmale
from beleg_schema import BelegAnalyse
from checks import nachfragen_gruende, nur_fachliche_gruende


def _m(name, kategorie, quelle="hand", anzahl=0):
    return {"name": name, "kategorie": kategorie, "quelle": quelle, "anzahl": anzahl}


def test_norm_ignoriert_rechtsform_und_schreibweise():
    assert merkmale.norm("Gasthaus Zur Linde GmbH") == merkmale.norm("gasthaus zur linde")
    assert merkmale.norm("Müller & Co. KG") == merkmale.norm("Mueller und Co")
    assert merkmale.norm(None) == ""


def test_nachschlagen_tolerant_aber_eindeutig():
    liste = [_m("Hotel Am Markt", "uebernachtung"), _m("Aral", "tankbeleg")]
    assert merkmale.nachschlagen("HOTEL AM MARKT GmbH", liste)["kategorie"] == "uebernachtung"
    assert merkmale.nachschlagen("Hotel Am Markl", liste)["kategorie"] == "uebernachtung"   # Lesefehler
    assert merkmale.nachschlagen("Aral Tankstelle Speyer", liste)["kategorie"] == "tankbeleg"  # Teiltreffer
    assert merkmale.nachschlagen("Hotel Zur Post", liste) is None
    assert merkmale.nachschlagen("", liste) is None
    # passen zwei mit verschiedenen Belegarten -> nicht eindeutig
    zwei = [_m("Hotel Linde", "uebernachtung"), _m("Hotel Linde Restaurant", "restaurant_beleg")]
    assert merkmale.nachschlagen("Linde", zwei) is None


def test_aus_bewertungen_nur_eindeutig_und_oft_genug():
    bew = [
        A.bewertung("a", ki_kat="uebernachtung"),
        A.bewertung("b", ki_kat="uebernachtung"),
        A.bewertung("c", ki_kat="restaurant_beleg"), A.bewertung("d", ki_kat="restaurant_mit_ec_beleg"),
        A.bewertung("e", ki_kat="tankbeleg"),                                                   # nur einmal
        A.bewertung("f", ki_kat="restaurant_beleg"), A.bewertung("g", ki_kat="uebernachtung"),  # widersprüchlich
    ]
    namen = ["Hotel Am Markt", "Hotel am Markt GmbH", "Linde", "Linde", "Aral", "Krone", "Krone"]
    for f, name in zip(bew, namen):
        f["felder"]["restaurant_name"] = {"modell": name, "korrekt": name, "richtig": True}
    liste = {m["name"]: m for m in merkmale.aus_bewertungen(bew)}
    assert set(liste) == {"Hotel am Markt GmbH", "Linde"}
    assert liste["Linde"]["anzahl"] == 2 and liste["Linde"]["quelle"] == "belege"  # Bewirtungs-Unterarten = eine Gruppe


def test_von_hand_hat_vorrang_mehrdeutig_wird_ignoriert():
    merkmale.registrieren(
        hand=[_m("Linde", "uebernachtung"), _m("Krone", "uebernachtung"), _m("Krone", "tankbeleg")],
        auto=[_m("Linde", "restaurant_beleg", "belege", 3), _m("Krone", "restaurant_beleg", "belege", 2)])
    assert merkmale.nachschlagen("Linde")["kategorie"] == "uebernachtung"
    assert merkmale.nachschlagen("Krone") is None


def test_aus_tabelle():
    zeilen = [{"wert": " Hotel Am Markt ", "anmerkung": float("nan")}, {"wert": "hotel am markt", "anmerkung": ""},
              {"wert": None, "anmerkung": "leer"}]
    assert merkmale.aus_tabelle(zeilen) == [{"art": "aussteller", "wert": "Hotel Am Markt", "anmerkung": ""}]


def _analyse(**werte):
    return BelegAnalyse.model_validate(A.analyse(**werte))


def test_bestaetigt_raeumt_zweifel_an_der_belegart_aus():
    merkmale.registrieren([_m("Hotel Am Markt", "uebernachtung")], [])
    a = _analyse(kategorie="uebernachtung", restaurant_name="Hotel Am Markt", kategorie_unsicher=True,
                 kategorie_grund="Rechnung ohne Zimmer-Position")
    assert not any(g.startswith("Belegart unsicher") for g in nachfragen_gruende(a, []))
    assert any(g.startswith("Belegart unsicher") for g in nachfragen_gruende(a, [], mit_merkmalen=False))


def test_widerspruch_gibt_nachfrage():
    merkmale.registrieren([], [_m("Hotel Am Markt", "uebernachtung", "belege", 3)])
    a = _analyse(kategorie="restaurant_beleg", restaurant_name="Hotel am Markt")
    gruende = nachfragen_gruende(a, [])
    assert any(g.startswith("Bekannter Aussteller: „Hotel Am Markt“ gehört bei 3 geprüften Belegen zu „Übernachtung")
               for g in gruende), gruende
    assert not nur_fachliche_gruende(a, [])  # großes Modell darf nachsehen
    # andere Bewirtungs-Unterart ist kein Widerspruch
    merkmale.registrieren([_m("Linde", "restaurant_mit_ec_beleg")], [])
    assert nachfragen_gruende(_analyse(kategorie="restaurant_beleg", restaurant_name="Linde"), []) == []


def test_bestaetigter_aussteller_spart_den_schiedsrichter(monkeypatch):
    import importlib

    import pipeline
    pipeline = importlib.reload(pipeline)
    monkeypatch.setattr(pipeline, "kontrast_variante", lambda bild: b"KONTRAST")
    aufrufe = []

    def analysieren(bilder, modell, system):
        aufrufe.append(modell)
        return _analyse(kategorie="uebernachtung", restaurant_name="Hotel Am Markt", kategorie_unsicher=True), "{}", {}
    monkeypatch.setattr(pipeline, "analysieren", analysieren)
    merkmale.registrieren([_m("Hotel Am Markt", "uebernachtung")], [])
    erg = pipeline.beleg_lesen([b"BILD"])
    assert not erg.schiedsrichter and erg.gruende == [] and len(aufrufe) == 2


# Automatisches Richtigstellen: KI sagt „Sonstiger Beleg“, Aussteller ist von Hand bekannt
def test_sonstiger_beleg_wird_bei_hand_eintrag_richtiggestellt():
    from beleg_schema import gueltige_konten
    from checks import belegart_richtigstellen
    merkmale.registrieren([_m("Hotel Am Markt", "uebernachtung")], [])
    a = _analyse(kategorie="sonstiger_beleg", restaurant_name="Hotel am Markt GmbH", kategorie_unsicher=True)
    neu, vermerk = belegart_richtigstellen(a)
    assert neu.kategorie == "uebernachtung" and not neu.kategorie_unsicher
    assert "Vom Programm richtiggestellt" in neu.kategorie_grund
    assert neu.konto == (gueltige_konten().get("uebernachtung") or {}).get("standard")
    assert vermerk == {"ki": "sonstiger_beleg", "neu": "uebernachtung", "aussteller": "Hotel Am Markt"}
    assert a.kategorie == "sonstiger_beleg"  # Original (Lesung) bleibt unverändert
    assert nachfragen_gruende(neu, []) == []


def test_kein_richtigstellen_ohne_hand_eintrag_oder_bei_anderer_belegart():
    from checks import belegart_richtigstellen
    a = _analyse(kategorie="sonstiger_beleg", restaurant_name="Hotel Am Markt")
    merkmale.registrieren([], [_m("Hotel Am Markt", "uebernachtung", "belege", 3)])  # nur automatisch bekannt
    assert belegart_richtigstellen(a) == (a, None)
    assert any(g.startswith("Bekannter Aussteller") for g in nachfragen_gruende(a, []))  # -> Nachfrage
    merkmale.registrieren([_m("Hotel Am Markt", "uebernachtung")], [])
    b = _analyse(kategorie="restaurant_beleg", restaurant_name="Hotel Am Markt")  # echte Wahl der KI -> nur Nachfrage
    assert belegart_richtigstellen(b) == (b, None)
    merkmale.registrieren([_m("Hotel Am Markt", "gibt_es_nicht")], [])
    assert belegart_richtigstellen(a) == (a, None)


def test_richtigstellen_spart_schiedsrichter_und_nachfrage(monkeypatch):
    import importlib

    import pipeline
    pipeline = importlib.reload(pipeline)
    monkeypatch.setattr(pipeline, "kontrast_variante", lambda bild: b"KONTRAST")
    aufrufe = []

    def analysieren(bilder, modell, system):
        aufrufe.append(modell)
        return _analyse(kategorie="sonstiger_beleg", restaurant_name="Hotel Am Markt"), "{}", {}
    monkeypatch.setattr(pipeline, "analysieren", analysieren)
    merkmale.registrieren([_m("Hotel Am Markt", "uebernachtung")], [])
    erg = pipeline.beleg_lesen([b"BILD"])
    assert erg.analyse.kategorie == "uebernachtung" and erg.gruende == [] and len(aufrufe) == 2
    assert erg.richtiggestellt["ki"] == "sonstiger_beleg"
    assert all(l.analyse.kategorie == "sonstiger_beleg" for l in erg.lesungen)  # Lesungen bleiben, wie gelesen
