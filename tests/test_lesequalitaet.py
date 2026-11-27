"""Lesequalität (lesequalitaet.py) und ihre Anzeige in der Auswertung."""
import attrappe as A
import lesequalitaet as LQ

BASIS = {"kategorie": "restaurant_beleg", "lesbar": True, "restaurant_name": "Domhof", "belegnummer": "1976",
         "datum": "2026-09-04", "brutto": 133.4, "steuersaetze": [7, 19]}


def lesung(variante, **abweichend):
    return {"modell": "m", "variante": variante, "analyse": {**BASIS, **abweichend}}


def bewertung(richtig_felder: dict, kategorie="restaurant_beleg", ki_kat="restaurant_beleg", falsch=()):
    """Endergebnis = Lesung 1; falsch: Felder, die der Mensch korrigiert hat (richtig_felder = richtige Werte)."""
    felder = {}
    for key, _l, _t in __import__("beleg_schema").FEEDBACK_FELDER:
        korrekt = richtig_felder.get(key, BASIS.get(key))
        felder[key] = {"modell": BASIS.get(key), "korrekt": korrekt, "richtig": key not in falsch}
    return {"kategorie": {"modell": ki_kat, "korrekt": kategorie, "richtig": ki_kat == kategorie}, "felder": felder}


def test_alles_richtig():
    erg = LQ.auswerten([{"bewertung": bewertung({}), "lesungen": [lesung("original"), lesung("kontrast")],
                         "dateiname": "a.jpg", "seiten": 1}])
    assert erg["belege"] == 1
    assert erg["felder"]["brutto"] == {"original": [1, 1], "kontrast": [1, 1], "ergebnis": [1, 1]}
    assert erg["belegart"]["original"] == [1, 1]
    assert erg["nur_original"] == erg["nur_kontrast"] == 0
    assert erg["je_typ"]["Foto/Bild"][0] == erg["je_typ"]["Foto/Bild"][1]
    assert "einseitig" in erg["je_typ"]


def test_kontrast_und_schiedsrichter():
    # Mensch: Belegnummer ist 1916. Original las 1976 (falsch), Kontrast 1916 (richtig), Schiedsrichter 1916.
    # Endergebnis (Schiedsrichter) war richtig -> Feld nicht korrigiert.
    b = bewertung({"belegnummer": "1916"})
    erg = LQ.auswerten([{"bewertung": b, "dateiname": "rechnung.pdf", "seiten": 2, "lesungen": [
        lesung("original"), lesung("kontrast", belegnummer="1916"), lesung("hochaufgelöst", belegnummer="1916")]}])
    assert erg["felder"]["belegnummer"]["original"] == [0, 1]
    assert erg["felder"]["belegnummer"]["kontrast"] == [1, 1]
    assert erg["nur_kontrast"] == 1 and erg["schiedsrichter"]["eingesetzt"] == 1
    assert erg["schiedsrichter"]["gerettet"] == 0  # eine der ersten lag ja richtig
    # Name, Adresse und Mitarbeiter (leer=leer) richtig, Nummer falsch
    assert erg["gruppen"]["Textfelder"]["original"] == [3, 4]
    assert "PDF" in erg["je_typ"] and "mehrseitig" in erg["je_typ"]


def test_schiedsrichter_rettet_und_verschlechtert():
    gerettet = bewertung({"brutto": 144.8})  # beide ersten lasen 133,40, Schiedsrichter 144,80
    verschlechtert = bewertung({}, falsch=("brutto",))  # erste richtig, Endergebnis falsch
    erg = LQ.auswerten([
        {"bewertung": gerettet, "lesungen": [lesung("original"), lesung("kontrast"),
                                             lesung("hochaufgelöst", brutto=144.8)]},
        {"bewertung": verschlechtert, "lesungen": [lesung("original"), lesung("kontrast"),
                                                   lesung("hochaufgelöst", brutto=99.0)]},
    ])
    assert erg["schiedsrichter"] == {"eingesetzt": 2, "gerettet": 1, "verschlechtert": 1}


def test_ohne_lesungen_und_kaputte_lesungen():
    erg = LQ.auswerten([{"bewertung": bewertung({}), "lesungen": None},
                        {"bewertung": bewertung({}), "lesungen": [{"variante": "original", "analyse": None},
                                                                   {"variante": "unbekannt", "analyse": BASIS}]}])
    assert erg["belege"] == 0


def test_vergleich_wie_im_formular():
    assert LQ._gleich("brutto", 133.4, 133.40) and LQ._gleich("trinkgeld", 0.0, None)
    assert LQ._gleich("steuersaetze", [7.0, 19.0], [7, 19])
    assert LQ._gleich("restaurant_name", "Domhof  ", "domhof")
    assert LQ._gleich("datum", "2026-09-04", "2026-09-04") and not LQ._gleich("datum", "2026-09-04", "2026-09-05")


def test_anzeige_in_der_auswertung():
    eintrag = A.analyse_eintrag("lq")
    eintrag["lesungen"] = [lesung("original", brutto=26.5), lesung("kontrast", brutto=62.5)]
    at = A.app(analysen=[eintrag], feedback=[A.bewertung("lq")])
    A.keine_fehler(at)
    assert any(m.value == "**Lesequalität**" for m in at.markdown)
    assert any("Belege mit Lesungen · 1" in m.value and "Nur Original richtig · 1" in m.value for m in at.markdown)
    tabelle = next(t for t in at.get("table") if "Lesung 2 (Kontrast)" in str(t.proto))
    assert "Endergebnis" in str(tabelle.proto)


def test_anzeige_ohne_lesungen():
    at = A.app(analysen=[A.analyse_eintrag("x")], feedback=[A.bewertung("x")])
    assert any("Noch keine geprüften Belege mit gespeicherten Lesungen" in i.value for i in at.info)


# Wann hilft der Schiedsrichter?
STIMMIG = {"steuersatz_erkennbar": True, "steuerzeilen": [{"satz": 19, "netto": 112.1, "mwst": 21.3}]}


def test_grund_art():
    assert LQ.grund_art("Belegart unsicher: kein Gericht") == "Belegart unsicher"
    assert LQ.grund_art("Auslandsbeleg – dafür gilt eine abweichende Handhabe.") == "Auslandsbeleg"
    assert LQ.grund_art("Kein Steuersatz ausgewiesen.") == "Kein Steuersatz ausgewiesen"


def test_wirkung_abweichung_geklaert_und_besser():
    # Original 1976, Kontrast 1916 -> Abweichung; Schiedsrichter 1916 klärt sie; Mensch: 1916 ist richtig
    beleg = {"lesungen": [lesung("original", **STIMMIG), lesung("kontrast", belegnummer="1916", **STIMMIG),
                          lesung("hochaufgelöst", belegnummer="1916", **STIMMIG)],
             "bewertung": bewertung({"belegnummer": "1916"})}
    w = LQ.schiedsrichter_wirkung([beleg])
    assert w[LQ.ABWEICHUNG] == {"einsaetze": 1, "aufgeloest": 1, "geaendert": 1, "geprueft": 1,
                                "besser": 1, "schlechter": 0}


def test_wirkung_grund_bleibt_kandidat_zum_ueberspringen():
    # beide Lesungen gleich, aber Belegart unsicher; Schiedsrichter sieht es genauso -> nichts bewirkt
    unsicher = {**STIMMIG, "kategorie_unsicher": True, "kategorie_grund": "kein Gericht erkennbar"}
    belege = [{"lesungen": [lesung(v, **unsicher) for v in ("original", "kontrast", "hochaufgelöst")],
               "bewertung": None}] * 5
    w = LQ.schiedsrichter_wirkung(belege)
    assert w["Belegart unsicher"]["einsaetze"] == 5 and not w["Belegart unsicher"]["aufgeloest"]
    assert LQ.ABWEICHUNG not in w and LQ.ueberspringen_kandidaten(w) == ["Belegart unsicher"]
    # ohne Schiedsrichter oder ohne Lesungen zählt nichts
    assert LQ.schiedsrichter_wirkung([{"lesungen": [lesung("original")], "bewertung": None},
                                      {"lesungen": None, "bewertung": None}]) == {}


def test_wirkung_in_der_auswertung():
    analyse = {"datei_sha256": "x", "dateiname": "a.jpg", "gruende": [], "lesungen": [
        lesung("original", **STIMMIG), lesung("kontrast", belegnummer="1916", **STIMMIG),
        lesung("hochaufgelöst", belegnummer="1916", **STIMMIG)]}
    fb = {"datei_sha256": "x", "dateiname": "a.jpg", "quelle": "pruefung", **bewertung({"belegnummer": "1916"})}
    at = A.app(analysen=[analyse], feedback=[fb])
    A.keine_fehler(at)
    assert any("Wann hilft der Schiedsrichter?" in m.value for m in at.markdown)
    zeilen = [str(t.value.to_dict("records")) for t in at.table] + [str(d.value.to_dict("records")) for d in at.dataframe]
    assert any(LQ.ABWEICHUNG in z and "1 / 0 (bei 1 Belegen)" in z for z in zeilen), zeilen
