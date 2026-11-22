"""Tab „Belege“: zusammenführen, Status, Filter, blättern, prüfen, korrigieren (simulierte Ablage)."""
import attrappe as A


def _daten():
    return dict(
        analysen=[A.analyse_eintrag("tank", kategorie="tankbeleg", brutto=80.0),
                  A.analyse_eintrag("rest", gruende=["Summe passt nicht"])],
        feedback=[A.bewertung("krone", ki_kat="restaurant_mit_ec_beleg", kommentar="Zimmerbuchung nicht erkannt")],
    )


def test_status_filter_und_tab_beschriftung():
    at = A.app(**_daten())
    assert ":orange-badge[1 offen]" in at.tabs[1].label
    filter_ = at.segmented_control[0]
    assert filter_.value == "offen"  # Start dort, wo es etwas zu tun gibt
    beschriftungen = filter_.options
    assert "Nachfragen offen :orange-badge[1]" in beschriftungen and "Ungeprüft :blue-badge[1]" in beschriftungen
    assert "Mit Kommentar (1)" in beschriftungen and "Alle (3)" in beschriftungen
    assert not any(o.startswith("Alle Nachfragen") for o in beschriftungen)  # Filter entfernt
    assert at.selectbox(key="beleg_wahl").value == "rest"
    assert any("Warum die KI nachfragt" in e.value for e in at.error)


def test_nachfrage_korrigieren_braucht_begruendung():
    at = A.app(**_daten())
    A.radio(at, "Stimmt die Belegart").set_value("ja").run()
    A.knopf(at, "Korrigieren").click().run()
    assert any("begründen" in e.value for e in at.error)
    assert A.SPEICHER["feedback"][-1]["datei_sha256"] == "krone"  # nichts gespeichert

    A.feld(at, "Gesamtbetrag").set_value("27,00")
    A.feld(at, "Begründung").set_value("Trinkgeld gehört dazu")
    A.knopf(at, "Korrigieren").click().run()
    A.keine_fehler(at)
    neu = A.SPEICHER["feedback"][-1]
    assert neu["datei_sha256"] == "rest" and neu["quelle"] == "nachfrage"
    assert neu["felder"]["brutto"] == {"modell": 26.5, "korrekt": 27.0, "richtig": False}
    assert neu["nachfrage_gruende"] == ["Summe passt nicht"] and neu["kommentar"] == "Trinkgeld gehört dazu"
    assert any("gespeichert" in s.value for s in at.success)  # Gegenüberstellung oben
    assert "Nachfragen offen (0)" in at.segmented_control[0].options


def test_ungepruefter_beleg_ohne_aenderung_ohne_begruendung():
    at = A.app(**_daten())
    at.segmented_control[0].set_value("ungeprueft").run()
    at.selectbox(key="beleg_wahl").set_value("tank").run()
    A.radio(at, "Stimmt die Belegart").set_value("ja").run()
    A.knopf(at, "Prüfung speichern").click().run()
    A.keine_fehler(at)
    neu = A.SPEICHER["feedback"][-1]
    assert neu["datei_sha256"] == "tank" and neu["quelle"] == "pruefung" and neu["kategorie"]["richtig"]


def test_ungepruefter_beleg_mit_aenderung_braucht_begruendung():
    at = A.app(**_daten())
    at.segmented_control[0].set_value("ungeprueft").run()
    at.selectbox(key="beleg_wahl").set_value("tank").run()
    A.radio(at, "Stimmt die Belegart").set_value("ja").run()
    A.feld(at, "Gesamtbetrag").set_value("81,00")
    A.knopf(at, "Prüfung speichern").click().run()
    assert any("begründen" in e.value for e in at.error)
    assert not any(f["datei_sha256"] == "tank" for f in A.SPEICHER["feedback"])


def test_belegart_frage_ist_pflicht():
    at = A.app(**_daten())
    A.feld(at, "Begründung").set_value("x")
    A.knopf(at, "Korrigieren").click().run()
    assert any("Belegart stimmt" in e.value for e in at.error)


def test_gepruefter_beleg_korrigieren_und_abbrechen():
    at = A.app(**_daten())
    at.segmented_control[0].set_value("kommentar").run()
    assert at.selectbox(key="beleg_wahl").value == "krone"
    A.knopf(at, "Korrigieren").click().run()
    assert any(b.label == "Abbrechen" for b in at.button)
    A.knopf(at, "Abbrechen").click().run()
    assert not any(b.label == "Abbrechen" for b in at.button)

    A.knopf(at, "Korrigieren").click().run()
    assert A.radio(at, "Stimmt die Belegart").value == "ja"  # bisherige Prüfung vorausgewählt
    A.radio(at, "Stimmt die Belegart").set_value("nein").run()
    next(s for s in at.selectbox if s.label == "Richtige Belegart").set_value("uebernachtung").run()
    A.feld(at, "Begründung").set_value("Zimmerbuchung")
    A.knopf(at, "Korrigieren").click().run()
    A.keine_fehler(at)
    neu = A.SPEICHER["feedback"][-1]
    alt = A.SPEICHER["feedback"][0]
    assert neu["kategorie"] == {"modell": "restaurant_mit_ec_beleg", "korrekt": "uebernachtung", "richtig": False}
    assert neu["korrektur_von"] == alt["zeitpunkt"] and neu["kommentar_vorher"] == "Zimmerbuchung nicht erkannt"


def test_blaettern():
    at = A.app(**_daten())
    at.segmented_control[0].set_value("alle").run()
    at.selectbox(key="beleg_wahl").set_value("krone").run()  # neuester = erster in der Liste
    assert A.knopf(at, "Vorheriger").disabled
    assert any("Beleg **1** von 3" in m.value for m in at.markdown)
    A.knopf(at, "Nächster").click().run()
    assert at.selectbox(key="beleg_wahl").value == "rest"
    assert not A.knopf(at, "Vorheriger").disabled
    A.knopf(at, "Nächster").click().run()
    assert at.selectbox(key="beleg_wahl").value == "tank" and A.knopf(at, "Nächster").disabled


def test_alte_nachfrage_und_entscheidung_werden_gelesen():
    at = A.app(
        nachfragen=[{"zeitpunkt": A.zeitpunkt(), "datei_sha256": "alt", "dateiname": "alt.png",
                     "beleg_pfade": ["belege/alt.png"], "kategorie": "restaurant_beleg",
                     "gruende": ["Ausland"], "analyse": A.analyse()}],
        entscheidungen=[{"zeitpunkt": A.zeitpunkt(), "datei_sha256": "alt", "status": "verworfen",
                         "bearbeiter": "annika"}],
    )
    at.segmented_control[0].set_value("alle").run()
    assert "Erledigt (ohne Bewertung)" in at.selectbox(key="beleg_wahl").options[0]
    assert any("ersten Version erledigt" in i.value for i in at.info)


def test_leere_ablage():
    at = A.app()
    assert any("Noch keine Belege" in i.value for i in at.info)


# --- Suche und Filter -------------------------------------------------------------------------------

def _suchdaten():
    return dict(
        analysen=[
            A.analyse_eintrag("flug", kategorie="sonstiger_beleg", restaurant_name="Wizz Air", datum="2026-03-02",
                              belegnummer="W6-4711"),
            A.analyse_eintrag("hotel", kategorie="uebernachtung", restaurant_name="Hotel Krone", datum="2026-03-03",
                              adresse="Hauptstr. 13, Neresheim"),
            A.analyse_eintrag("essen", restaurant_name="D'Oro", datum="2026-01-31", adresse="Unter den Linden 39, Berlin"),
        ],
        # geprüft: die KI las „Sonstiger Beleg“, richtig ist Übernachtung; Belegnummer korrigiert
        feedback=[{**A.bewertung("flug", ki_kat="sonstiger_beleg", richtige_kat="uebernachtung"),
                   "felder": {"belegnummer": {"modell": "W6-4711", "korrekt": "W6-4712", "richtig": False},
                              "datum": {"modell": "2026-03-02", "korrekt": "2026-03-02", "richtig": True}}}],
    )


def _alle(at):
    at.segmented_control[0].set_value("alle").run()
    return at


def _optionen(at):
    return at.selectbox(key="beleg_wahl").options


def test_suche_nach_aussteller_und_ort():
    at = _alle(A.app(**_suchdaten()))
    at.text_input(key="belege_suche").set_value("krone").run()
    assert len(_optionen(at)) == 1 and "hotel.png" in _optionen(at)[0]
    assert any("1 von 3 Belegen" in c.value for c in at.caption)
    at.text_input(key="belege_suche").set_value("berlin linden").run()  # alle Wörter müssen vorkommen
    assert len(_optionen(at)) == 1 and "essen.png" in _optionen(at)[0]
    at.text_input(key="belege_suche").set_value("berlin krone").run()
    assert any("Keine Belege passen zur Suche" in i.value for i in at.info)


def test_suche_nutzt_korrigierte_werte():
    at = _alle(A.app(**_suchdaten()))
    at.text_input(key="belege_suche").set_value("W6-4712").run()  # korrigierte Belegnummer
    assert len(_optionen(at)) == 1 and "flug.png" in _optionen(at)[0]
    at.text_input(key="belege_suche").set_value("W6-4711").run()  # alte KI-Lesung findet nichts mehr
    assert any("Keine Belege passen zur Suche" in i.value for i in at.info)


def test_filter_belegart_und_zeitraum_und_zuruecksetzen():
    from datetime import date

    at = _alle(A.app(**_suchdaten()))
    at.multiselect(key="belege_arten").set_value(["uebernachtung"]).run()  # Flug zählt geprüft als Übernachtung
    assert len(_optionen(at)) == 2
    at.date_input(key="belege_zeitraum").set_value((date(2026, 3, 3), date(2026, 3, 31))).run()
    assert len(_optionen(at)) == 1 and "hotel.png" in _optionen(at)[0]
    A.knopf(at, "Filter zurücksetzen").click().run()
    A.keine_fehler(at)
    assert len(_optionen(at)) == 3 and at.text_input(key="belege_suche").value == ""


def test_veralteter_filter_in_sitzung_faellt_auf_start_zurueck():
    at = A.app(**_daten())
    at.session_state["belege_filter_naechste"] = None
    at.session_state["belege_filter"] = "nachfrage"  # gab es früher („Alle Nachfragen“)
    at.run()
    A.keine_fehler(at)
    assert at.segmented_control[0].value == "offen"
