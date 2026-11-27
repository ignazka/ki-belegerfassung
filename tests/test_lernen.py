"""„Aus Korrekturen lernen“: Vorsortieren, veraltete Fälle, Wirkung, Auswahl für den Probelauf (lernen.py)."""
import attrappe as A
import lernen


def test_vorsortiert_nur_eindeutige_lesefehler():
    ok = A.bewertung("a")
    assert lernen.vorsortiert(ok, ["Unsicher gelesen – Datum: 01.01. / 02.01."]) == lernen.NUR_UNSICHER_KURZ
    assert lernen.vorsortiert(ok, ["Unsicher gelesen – Datum", "Ausland"]) is None       # anderer Grund dabei
    assert lernen.vorsortiert(ok, []) is None
    assert lernen.vorsortiert(A.bewertung("a", kommentar="Datum?"), ["Unsicher gelesen"]) is None  # Kommentar
    assert lernen.vorsortiert(A.bewertung("a", felder_falsch=["brutto"]), ["Unsicher gelesen"]) is None


def test_wissensaenderungen():
    versionen = [
        # Standard-Kategorie nur mit Konto gespeichert: Text gleich -> keine Änderung
        {"schluessel": "tankbeleg", "zeitpunkt": "2026-11-01T10:00:00", "version": 1,
         "beschreibung": "Tankstelle mit Kraftstoff (Diesel, Super, AdBlue, Laden; Liter, €/l). Benötigt: Datum, "
                         "Betrag, Steuersatz. Fahrzeug und Mitarbeiter sind nicht nötig.", "skr04_konto": "6530"},
        {"schluessel": "uebernachtung", "zeitpunkt": "2026-11-02T10:00:00", "version": 1,
         "erkennungsmerkmale": "Zimmer"},
        {"schluessel": "uebernachtung", "zeitpunkt": "2026-11-05T10:00:00", "version": 2,
         "erkennungsmerkmale": "Zimmer", "skr04_konto": "6660"},                    # nur Konto -> zählt nicht
        {"schluessel": "reise", "name": "Reise", "status": "entwurf", "zeitpunkt": "2026-11-03T10:00:00"},
        {"schluessel": "reise", "name": "Reise", "status": "aktiv", "zeitpunkt": "2026-11-04T10:00:00"},  # aktiviert
    ]
    assert lernen.wissensaenderungen(versionen) == {"uebernachtung": "2026-11-02T10:00:00",
                                                    "reise": "2026-11-04T10:00:00"}


def test_veraltet():
    aenderungen = {"uebernachtung": "2026-11-02T10:00:00"}
    assert lernen.veraltet("2026-11-01T09:00:00", ["restaurant_beleg", "uebernachtung"], aenderungen)
    assert not lernen.veraltet("2026-11-03T09:00:00", ["restaurant_beleg", "uebernachtung"], aenderungen)
    assert not lernen.veraltet("2026-11-01T09:00:00", ["restaurant_beleg", None], aenderungen)


def test_wirkung():
    paare = [("2026-11-01", A.bewertung("a", ki_kat="restaurant_beleg", richtige_kat="uebernachtung")),
             ("2026-11-01", A.bewertung("b", ki_kat="uebernachtung")),
             ("2026-11-10", A.bewertung("c", ki_kat="uebernachtung", felder_falsch=["brutto"])),
             ("2026-11-10", A.bewertung("d", ki_kat="tankbeleg"))]                    # andere Kategorie
    assert lernen.wirkung(paare, "uebernachtung", "2026-11-05") == {"vorher": (1, 2), "nachher": (1, 1)}


def test_testbelege_halb_mit_fehler_halb_fehlerfrei():
    def beleg(sha, zeit, **bew):
        return {"sha": sha, "zeitpunkt": zeit, "bewertung": A.bewertung(sha, **bew)}
    belege = ([beleg(f"f{i}", f"2026-11-{10 + i}", ki_kat="restaurant_beleg", richtige_kat="uebernachtung")
               for i in range(5)]
              + [beleg(f"r{i}", f"2026-11-{10 + i}", ki_kat="uebernachtung") for i in range(5)]
              + [beleg("x", "2026-11-20", ki_kat="tankbeleg"), {"sha": "ohne", "zeitpunkt": "2026-11-21"}])
    auswahl = [b["sha"] for b in lernen.testbelege_auswaehlen(belege, {"uebernachtung"}, 4)]
    assert auswahl == ["f4", "f3", "r4", "r3"]                       # je zur Hälfte, die neuesten zuerst
    # zu wenig fehlerfreie: Rest mit Fehlerfällen auffüllen
    nur_fehler = [b for b in belege if b["sha"].startswith("f")]
    assert len(lernen.testbelege_auswaehlen(nur_fehler, {"uebernachtung"}, 4)) == 4
