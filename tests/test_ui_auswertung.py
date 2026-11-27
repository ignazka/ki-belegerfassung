"""Tab „Auswertung“: Kennzahlen und „Aus Korrekturen lernen“ bis zur Übernahme in den Kategorien-Tab."""
import attrappe as A


def _daten():
    return dict(
        analysen=[A.analyse_eintrag("n1", gruende=["Unsicher gelesen"]),
                  A.analyse_eintrag("n2", gruende=["Ausland"]),
                  A.analyse_eintrag("ok")],
        feedback=[
            A.bewertung("n1"),                                         # Nachfrage, alles richtig -> unnötig
            A.bewertung("ok", ki_kat="restaurant_mit_ec_beleg", richtige_kat="uebernachtung",
                        kommentar="Zimmerbuchung"),
            A.bewertung("ok", ki_kat="restaurant_mit_ec_beleg", richtige_kat="uebernachtung",
                        felder_falsch=["brutto"], kommentar="Zimmerbuchung, Betrag falsch"),  # jüngste zählt
        ],
    )


def _metrik(at, label):
    return next(m.value for m in at.metric if m.label == label)


def test_kennzahlen():
    daten = _daten()
    # alles richtig, aber Ausland/Kalender: ohnehin nötig -> zählt nicht als unnötige Nachfrage
    daten["analysen"].append(A.analyse_eintrag("n3", gruende=[
        "Auslandsbeleg – dafür gilt eine abweichende Handhabe.", "Kalender: kein Termin am 04.09.2026 gefunden."]))
    daten["feedback"].insert(1, A.bewertung("n3"))
    at = A.app(**daten)
    assert _metrik(at, "Belege") == "4"
    assert _metrik(at, "Geprüft") == "3 von 4"
    assert _metrik(at, "Nachfragen der KI") == "3"
    assert _metrik(at, "Unnötige Nachfragen") == "1 von 2"   # n3 war wegen Ausland/Kalender ohnehin nötig
    assert next(m for m in at.metric if m.label == "Unnötige Nachfragen").delta == "1 waren ohnehin nötig"
    assert _metrik(at, "Geprüfte Belege") == "3"            # „ok“ zählt einmal (jüngste Prüfung)
    assert _metrik(at, "Belegart richtig") == "2 von 3"
    assert _metrik(at, "Alle Felder richtig") == "2 von 3"


_ANTWORT = {
    "faelle": [{"nr": 1, "ursache": "regel", "kurz": "Zimmer als Bewirtung"},
               {"nr": 2, "ursache": "bewertung_widerspruechlich", "kurz": "Kommentar widerspricht"}],
    "vorschlaege": [{"kategorie": "uebernachtung", "feld": "erkennungsmerkmale",
                     "text": "Zimmer-Positionen bedeuten Übernachtung.", "faelle": [1, 2],
                     "sicherheit": "hoch"},
                    {"kategorie": "gibtsnicht", "feld": "abgrenzung", "text": "wird verworfen"}],
    "rueckfragen": ["Gehört Frühstück zur Übernachtung?"],
}


def test_aus_korrekturen_lernen_bis_kategorie():
    n2 = A.bewertung("n2", kommentar="Ausland stimmt nicht")  # älter als die übrigen Prüfungen -> Fall 2
    daten = _daten()
    daten["feedback"].append(n2)
    at = A.app(ki={"text_antwort": _ANTWORT}, **daten)
    knopf = next(b for b in at.button if b.label.startswith("Verbesserungsvorschläge erstellen"))
    assert "(2 Fälle)" in knopf.label  # „ok“ und „n2“; n1 (nur „Unsicher gelesen“, alles richtig) ohne KI
    assert any("1 Fall ohne KI als Lesefehler einsortiert" in c.value for c in at.caption)
    knopf.click().run()
    A.keine_fehler(at)
    nachricht = A.ANFRAGEN[0]
    assert "FÄLLE" in nachricht and "Zimmerbuchung, Betrag falsch" in nachricht and '"n1' not in nachricht
    assert '"aussteller"' not in nachricht and '"ausland"' not in nachricht  # leere Angaben fallen weg
    assert [m.value for m in at.markdown if m.value.startswith("> ")] == ["> Zimmer-Positionen bedeuten Übernachtung."]
    texte = [m.value for m in at.markdown]
    assert any("Regel fehlte · 1" in t and "Bewertung widersprüchlich · 1" in t for t in texte)  # kompakt
    assert any(t.startswith("**Bewertung widersprüchlich**") for t in texte)                    # eigene Gruppe
    assert any("Kommentar widerspricht" in t for t in texte)  # Fall ohne Vorschlag als kleine Karte
    runde = A.SPEICHER["lernrunden"]
    assert len(runde) == 1 and runde[0]["shas"] == ["ok", "n2"] and runde[0]["vorsortiert"] == 1

    # Fall ohne Vorschlag: Beleg im Tab „Belege“ vorauswählen
    A.knopf(at, "Im Tab „Belege“ öffnen").click().run()
    A.keine_fehler(at)
    assert at.segmented_control[0].value == "alle" and at.selectbox(key="beleg_wahl").value == "n2"  # Fall 2
    assert any("Im Tab „Belege“ ausgewählt" in c.value for c in at.caption)
    assert any("Rückfragen an die Buchhaltung" in w.value for w in at.warning)

    A.knopf(at, "In Kategorie übernehmen").click().run()
    A.keine_fehler(at)
    assert at.selectbox(key="kategorie_wahl").value == "uebernachtung"
    feld = next(t for t in at.text_area if t.label == "Woran erkennt man die Kategorie?")
    assert feld.value.endswith("Zimmer-Positionen bedeuten Übernachtung.")
    assert any("noch nicht gespeichert" in i.value for i in at.info)
    assert A.SPEICHER["kategorien"] == []  # übernommen heißt nicht gespeichert

    # Speichern: Herkunft steht in der Kategorie-Version, die Auswertung zeigt die Wirkung
    A.knopf(at, "Speichern").click().run()
    A.keine_fehler(at)
    version = A.SPEICHER["kategorien"][-1]
    assert version["aus_lernrunde"] == [{"runde": runde[0]["erstellt"], "feld": "erkennungsmerkmale",
                                         "text": "Zimmer-Positionen bedeuten Übernachtung."}]
    assert any("In der Kategorie gespeichert" in c.value for c in at.caption)
    assert any(m.value == "**Wirkung übernommener Vorschläge**" for m in at.markdown)
    tabelle = next(t for t in at.table if "Mit Fehler vorher" in t.value.columns).value
    assert tabelle["Mit Fehler vorher"][0] == "1 von 1 (100%)"            # „ok“: falsche Belegart
    assert tabelle["Mit Fehler nachher"][0] == "noch keine geprüften Belege"


def test_aeltere_faelle_nach_kategorie_aenderung():
    """Kategorie nach der Analyse geändert -> Fall bleibt draußen, außer man bezieht ältere Fälle ein."""
    geaendert = {"schluessel": "uebernachtung", "zeitpunkt": "2099-12-31T00:00:00", "version": 1,
                 "erkennungsmerkmale": "Zimmer"}
    at = A.app(kategorien=[geaendert], **_daten())
    assert not any(b.label.startswith("Verbesserungsvorschläge erstellen") for b in at.button)
    assert any("Gerade keine Fälle" in i.value for i in at.info)
    at.checkbox(key="lern_mit_alten").check().run()
    A.keine_fehler(at)
    knopf = next(b for b in at.button if b.label.startswith("Verbesserungsvorschläge erstellen"))
    assert "(1 Fall)" in knopf.label


def test_letzte_runde_nach_neuladen_sichtbar():
    runde = {"erstellt": "2099-01-01T00:00:00", "anzahl": 1, "dateien": ["ok.png"], "shas": ["ok"],
             "faelle": [{"nr": 1, "ursache": "regel", "kurz": "Zimmer"}], "rueckfragen": [],
             "vorschlaege": [{"kategorie": "uebernachtung", "feld": "abgrenzung", "text": "Gespeicherter Vorschlag.",
                              "begruendung": "", "faelle": [1], "sicherheit": "niedrig"}]}
    at = A.app(lernrunden=[runde], **_daten())
    A.keine_fehler(at)
    assert any(m.value == "> Gespeicherter Vorschlag." for m in at.markdown)


def test_ohne_pruefungen():
    at = A.app(analysen=[A.analyse_eintrag("x")])
    assert any("Noch keine geprüften Belege" in i.value for i in at.info)


def test_belege_nur_einmal_pro_durchlauf_geladen():
    A.app(**_daten())
    assert A.LADEN.get("analysen") == 1, A.LADEN  # Tab-Beschriftung, Tab „Belege“ und Auswertung teilen sich
