"""Tab „Kategorien“: KI-Assistent über den Lauf-Knopf, Meldungen, Probelauf-Knopf (simulierte Ablage/KI)."""
import attrappe as A

ASSISTENT = {"erkennungsmerkmale": "Zimmer, Übernachtung", "abgrenzung": "keine Bewirtung",
             "pflichtangaben": ["Name des Gastes", "Zeitraum"], "nachfragen_wenn": "Name fehlt",
             "rueckfragen": ["Gehört Frühstück dazu?"]}


def _kategorie_uebernachtung(at):
    at.selectbox(key="kategorie_wahl").set_value("uebernachtung").run()
    return next(t for t in at.text_area if t.label.startswith("Beschreibung der Buchhaltung"))


def test_assistent_fuellt_regeln():
    at = A.app(ki={"text_antwort": ASSISTENT})
    _kategorie_uebernachtung(at).set_value("Hotelrechnungen mit Zimmer").run()
    A.knopf(at, "Mit KI-Assistent in klare Regeln übersetzen").click().run()
    A.keine_fehler(at)
    assert "Hotelrechnungen mit Zimmer" in A.ANFRAGEN[0]
    werte = {t.label: t.value for t in at.text_area}
    assert werte["Woran erkennt man die Kategorie?"] == "Zimmer, Übernachtung"
    assert werte["Pflichtangaben auf dem Beleg (eine pro Zeile)"] == "Name des Gastes\nZeitraum"
    assert any("Gehört Frühstück dazu?" in w.value for w in at.warning)
    assert A.knopf(at, "Mit KI-Assistent in klare Regeln übersetzen").disabled is False  # wieder klickbar


def test_assistent_ohne_beschreibung_meldet_fehler():
    at = A.app(ki={"text_antwort": ASSISTENT})
    _kategorie_uebernachtung(at).set_value("   ").run()
    A.knopf(at, "Mit KI-Assistent in klare Regeln übersetzen").click().run()
    assert any("zuerst eine Beschreibung" in e.value for e in at.error)
    assert A.ANFRAGEN == []


def test_assistent_nicht_erreichbar():
    at = A.app()  # keine text_antwort -> Attrappe wirft einen Fehler
    _kategorie_uebernachtung(at).set_value("Hotel").run()
    A.knopf(at, "Mit KI-Assistent in klare Regeln übersetzen").click().run()
    assert any("Assistent nicht erreichbar" in e.value for e in at.error)


def test_lernen_fehler_wird_nach_dem_lauf_angezeigt():
    at = A.app(analysen=[A.analyse_eintrag("x")],
               feedback=[A.bewertung("x", richtige_kat="uebernachtung", kommentar="Zimmer")])
    next(b for b in at.button if b.label.startswith("Verbesserungsvorschläge erstellen")).click().run()
    assert any("Vorschläge konnten nicht erstellt werden" in e.value for e in at.error)
    assert not next(b for b in at.button if b.label.startswith("Verbesserungsvorschläge erstellen")).disabled


# --- SKR04-Konto ---------------------------------------------------------------------------------------

def _zellen(at) -> set[str]:
    return {str(z) for t in at.table for z in t.value.to_numpy().ravel()}


def _speichern(at):
    A.knopf(at, "Speichern").click().run()
    A.keine_fehler(at)


def test_konto_aus_vorlage_uebernehmen_und_speichern():
    at = A.app()
    _kategorie_uebernachtung(at)
    vorlage = next(s for s in at.selectbox if s.label == "Aus der Vorlage übernehmen")
    nr = next(i for i in vorlage.options if "6660" in i)  # Optionen sind die Anzeigetexte
    vorlage.select(nr).run()
    assert A.feld(at, "Kontonummer").value == "6660"
    assert A.feld(at, "Bezeichnung").value == "Reisekosten Arbeitnehmer Übernachtungsaufwand"
    A.feld(at, "Bezeichnung").set_value("Übernachtung Mitarbeiter").run()  # Vorlage anpassen
    _speichern(at)
    gespeichert = A.SPEICHER["kategorien"][-1]
    assert gespeichert["schluessel"] == "uebernachtung"
    assert (gespeichert["skr04_konto"], gespeichert["skr04_bezeichnung"]) == ("6660", "Übernachtung Mitarbeiter")
    # nach dem Speichern steht das Konto wieder im Formular und in der Übersicht
    assert A.feld(at, "Kontonummer").value == "6660"
    assert "6660 · Übernachtung Mitarbeiter" in _zellen(at)


def test_eigenes_konto_ohne_bezeichnung():
    at = A.app()
    _kategorie_uebernachtung(at)
    A.feld(at, "Kontonummer").set_value("6999").run()
    _speichern(at)
    gespeichert = A.SPEICHER["kategorien"][-1]
    assert (gespeichert["skr04_konto"], gespeichert["skr04_bezeichnung"]) == ("6999", "")


def test_falsche_kontonummer_wird_nicht_gespeichert():
    at = A.app()
    _kategorie_uebernachtung(at)
    A.feld(at, "Kontonummer").set_value("66a").run()
    assert any("vier Ziffern" in e.value for e in at.error)
    A.knopf(at, "Speichern").click().run()
    assert any("Nicht gespeichert" in e.value for e in at.error)
    assert A.SPEICHER["kategorien"] == []


def test_ohne_konto_nur_hinweis():
    at = A.app()
    _kategorie_uebernachtung(at)
    assert any("Noch kein Konto festgelegt" in c.value for c in at.caption)
    _speichern(at)  # ohne Konto speichern bleibt erlaubt
    assert A.SPEICHER["kategorien"][-1]["skr04_konto"] == ""


def _kategorie_mit_ausnahmen():
    return {"schluessel": "restaurant_beleg", "version": 1, "zeitpunkt": "2026-11-21T10:00:00",
            "skr04_konto": "6640", "skr04_bezeichnung": "Bewirtungskosten",
            "konto_ausnahmen": [{"wenn": "nur ein Gedeck", "konto": "6664", "bezeichnung": "Verpflegung"}]}


def test_ausnahmen_bleiben_beim_speichern_erhalten():
    at = A.app(kategorien=[_kategorie_mit_ausnahmen()])
    at.selectbox(key="kategorie_wahl").set_value("restaurant_beleg").run()
    assert "6664 · Verpflegung, wenn nur ein Gedeck" in _zellen(at)  # Übersicht
    _speichern(at)
    assert A.SPEICHER["kategorien"][-1]["konto_ausnahmen"] == _kategorie_mit_ausnahmen()["konto_ausnahmen"]


def test_konto_im_ergebnis_und_im_pruefformular():
    png = ("beleg.png", A.bild_png(), "image/png")
    at = A.app(kategorien=[_kategorie_mit_ausnahmen()], ki={"dateien": [png], "analyse": A.analyse(konto="6664")})
    A.knopf(at, "Beleg analysieren").click().run()
    at.run()
    A.keine_fehler(at)
    assert any("6664 · Verpflegung" in m.value for m in at.markdown if "Konto (SKR04)" in m.value)
    assert A.SPEICHER["analysen"][-1]["analyse"]["konto"] == "6664"

    # Prüfen im Tab „Belege“: Konto ist vorbelegt und lässt sich korrigieren
    at.segmented_control[0].set_value("ungeprueft").run()
    assert A.feld(at, "Konto").value == "6664"
    A.radio(at, "Stimmt die Belegart").set_value("ja").run()
    A.feld(at, "Konto").set_value("6640")
    A.feld(at, "Begründung").set_value("Geschäftsessen mit Kunde")
    A.knopf(at, "Prüfung speichern").click().run()
    A.keine_fehler(at)
    assert A.SPEICHER["feedback"][-1]["felder"]["konto"] == {"modell": "6664", "korrekt": "6640", "richtig": False}


def test_probelauf_zeigt_konto():
    from testlauf import Ergebnis
    at = A.app(kategorien=[_kategorie_mit_ausnahmen()])
    at.selectbox(key="kategorie_wahl").set_value("restaurant_beleg").run()
    at.session_state["testlauf_restaurant_beleg"] = {
        "ergebnisse": {"a.png": {"vorher": Ergebnis("restaurant_beleg", False, [], "20,00 €", "–", konto="6640"),
                                 "nachher": Ergebnis("restaurant_beleg", True, ["Konto unsicher: 1 Gericht"],
                                                     "20,00 €", "–", konto="6664", konto_unsicher=True)}},
        "varianten": ["vorher", "nachher"], "erwartet": {"restaurant_beleg"}, "name": "Restaurant",
        "schluessel": "restaurant_beleg"}
    at.run()
    A.keine_fehler(at)
    assert any("Konten: 6664 · Verpflegung (1×)" in m.value for m in at.markdown)
    zellen = _zellen(at)
    assert any("Konto 6640 · ok" in z for z in zellen) and any("Konto 6664? · Nachfrage" in z for z in zellen)
    assert "anders" in zellen


def test_probelauf_mit_musterloesung():
    """Beispielbeleg schon geprüft -> Felder werden gegen die Prüfung gezählt, falsche Felder genannt."""
    from testlauf import Ergebnis
    at = A.app(kategorien=[_kategorie_mit_ausnahmen()])
    at.selectbox(key="kategorie_wahl").set_value("restaurant_beleg").run()
    werte_alt = {"brutto": 20.0, "datum": "2026-01-01"}
    werte_neu = {"brutto": 20.0, "datum": "2026-01-02"}
    at.session_state["testlauf_restaurant_beleg"] = {
        "ergebnisse": {"a.png": {"vorher": Ergebnis("restaurant_beleg", False, [], "20,00 €", "01.01.2026",
                                                    werte=werte_alt),
                                 "nachher": Ergebnis("restaurant_beleg", False, [], "20,00 €", "02.01.2026",
                                                     werte=werte_neu)}},
        "varianten": ["vorher", "nachher"], "erwartet": {"restaurant_beleg"}, "name": "Restaurant",
        "schluessel": "restaurant_beleg",
        "muster": {"a.png": {"kategorie": "restaurant_beleg", "felder": {"brutto": 20.0, "datum": "2026-01-01"}}}}
    at.run()
    A.keine_fehler(at)
    texte = [m.value for m in at.markdown]
    assert any("Felder richtig gelesen (bei 1 geprüften Belegen): **2 von 2**" in t for t in texte), texte
    assert any("**1 von 2**" in t for t in texte)
    zellen = _zellen(at)
    assert any("falsch: Datum" in z for z in zellen) and "anders" in zellen
    assert any("Eher nicht speichern" in w.value for w in at.warning)


def test_beispielbelege_zum_pruefen_ablegen():
    """Knopf im Probelauf-Fenster: Beispielbelege einmal analysieren und im Tab „Belege“ ablegen (Musterlösung)."""
    import io

    from PIL import Image
    puffer = io.BytesIO()
    Image.new("RGB", (300, 200), "gray").save(puffer, "PNG")
    beispiele = {"Übernachtung": [("hotel1.png", A.bild_png(), "image/png"), ("hotel2.png", puffer.getvalue(),
                                  "image/png"), ("kaputt.png", b"kein bild", "image/png")]}
    at = A.app(ki={"beispiele": beispiele})
    at.selectbox(key="kategorie_wahl").set_value("uebernachtung").run()

    def ablegen_klicken():
        A.knopf(at, "Testen").click().run()  # Fenster öffnen: Knopf ist da
        assert any(b.key == "laufknopf_beispiele_ablegen" for b in at.button)
        # Ein Klick im Fenster löst in AppTest einen kompletten Neuaufbau aus, bei dem das Fenster zu ist – der
        # Klick käme nie an. Im Browser setzt der Klick den Merker und baut nur das Fenster neu; das hier
        # nachgestellt: Merker setzen, Fenster öffnen -> Vorgang läuft; noch einmal öffnen -> Ergebnis-Meldung.
        at.session_state["laeuft_beispiele_ablegen"] = True
        A.knopf(at, "Testen").click().run()
        A.knopf(at, "Testen").click().run()
        A.keine_fehler(at)

    ablegen_klicken()
    abgelegt = A.SPEICHER["analysen"]
    assert len(abgelegt) == 2 and all(e["herkunft"] == "beispielordner" for e in abgelegt), abgelegt
    meldung = " ".join(w.value for w in at.warning)
    assert "2 Beispielbeleg(e) analysiert" in meldung and "Nicht möglich: kaputt.png" in meldung, meldung
    ablegen_klicken()  # zweites Mal: die beiden liegen schon da -> nichts doppelt (der kaputte scheitert erneut)
    assert len(A.SPEICHER["analysen"]) == 2
    meldung = " ".join(w.value for w in at.warning)
    assert "2 lag(en) schon dort" in meldung and "analysiert" not in meldung, meldung


def test_entwurf_gut_sichtbar_als_nicht_aktiv():
    entwurf = {"schluessel": "reisekosten", "name": "Reisekosten - Mitarbeiter", "status": "entwurf", "version": 1,
               "zeitpunkt": "2026-11-17T17:30:01", "beschreibung": "Bahn, Flug"}
    at = A.app(kategorien=[entwurf])
    A.keine_fehler(at)
    oben = [w.value for w in at.warning]
    assert any("noch Entwurf und damit nicht aktiv" in w and "„Reisekosten - Mitarbeiter“" in w for w in oben), oben
    at.selectbox(key="kategorie_wahl").set_value("reisekosten").run()
    assert any("Entwurf – nicht aktiv" in w.value for w in at.warning)
    # aktive Kategorie: kein Hinweis
    at = A.app(kategorien=[{**entwurf, "status": "aktiv"}])
    assert not any("Entwurf" in w.value for w in at.warning)


def test_probelauf_mit_geprueften_belegen(monkeypatch):
    """Probelauf mit schon geprüften Belegen der Kategorie: richtige Werte sind bekannt (Musterlösung)."""
    import pipeline
    import testlauf
    monkeypatch.setattr(testlauf, "beleg_lesen", lambda *a, **k: pipeline.beleg_lesen(*a, **k))  # Attrappe
    at = A.app(
        analysen=[A.analyse_eintrag("h1"), A.analyse_eintrag("h2", kategorie="uebernachtung")],
        feedback=[A.bewertung("h1", ki_kat="restaurant_beleg", richtige_kat="uebernachtung"),
                  A.bewertung("h2", ki_kat="uebernachtung")],
    )
    at.selectbox(key="kategorie_wahl").set_value("uebernachtung").run()
    A.knopf(at, "Testen").click().run()
    A.keine_fehler(at)
    auswahl = next(s for s in at.selectbox if s.label == "Mit welchen Belegen testen?")
    assert auswahl.value == "Geprüfte Belege dieser Kategorie (2)"
    assert any("1 mit Fehler, 1 fehlerfrei" in m.value for m in at.markdown)
    assert not any(b.key == "laufknopf_beispiele_ablegen" for b in at.button)  # nur für Drive-Ordner
    # Klick im Fenster wie in test_beispielbelege_zum_pruefen_ablegen nachgestellt
    at.session_state["laeuft_probelauf"] = True
    A.knopf(at, "Testen").click().run()
    A.knopf(at, "Testen").click().run()
    A.keine_fehler(at)
    t = at.session_state["testlauf_uebernachtung"]
    assert t["gepruefte"] and set(t["muster"]) == {"h1.png", "h2.png"}
    assert t["muster"]["h1.png"]["kategorie"] == "uebernachtung"
    texte = [m.value for m in at.markdown]
    assert any("Belegart richtig erkannt: **0 von 2**" in x for x in texte), texte  # KI-Attrappe: Restaurant
