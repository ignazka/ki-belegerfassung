"""Schnelltests der Rechen-, Prüf- und Parse-Logik ohne API-Aufruf.

Läuft mit allen anderen Tests über  python -m pytest  oder allein über  python tests/test_logik.py.
Die Prüfungen stehen bewusst direkt im Modul (werden beim Import ausgeführt).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from beleg_schema import BelegAnalyse, parse_betrag, parse_datum, parse_saetze, werte_gleich
from extraction import _json_extrahieren

# Beträge
assert parse_betrag("12,50 €") == 12.5
assert parse_betrag("1.234,56") == 1234.56
assert parse_betrag("1,234.56") == 1234.56
assert parse_betrag("") is None
assert parse_betrag("abc") is None
assert parse_betrag(7) == 7.0

# Datum
assert parse_datum("17.11.2026") == "2026-11-17"
assert parse_datum("17.11.26") == "2026-11-17"
assert parse_datum("2026-11-17T12:00") == "2026-11-17"
assert parse_datum("Montag") is None

# Steuersätze
assert parse_saetze("7, 19") == [7, 19]
assert parse_saetze([19, "7%"]) == [7, 19]
assert parse_saetze(None) == []
assert parse_saetze("7,19") == [7, 19]
assert parse_saetze("7 und 19 %") == [7, 19]

# Vergleich
assert werte_gleich("betrag", 85.0, "85,00")
assert not werte_gleich("betrag", 85.0, "85,10")
assert werte_gleich("betrag", None, "")
assert werte_gleich("betrag", 0.0, "")
assert not werte_gleich("betrag", None, "5,00")
assert werte_gleich("text", "Gasthaus  Zur Linde", "gasthaus zur linde")
assert werte_gleich("datum", "2026-11-14", "14.11.2026")
assert werte_gleich("saetze", [19, 7], "7,19")

# JSON-Extraktion
assert _json_extrahieren('{"a": 1}') == {"a": 1}
assert _json_extrahieren('```json\n{"a": 1}\n```') == {"a": 1}
assert _json_extrahieren('Hier das Ergebnis:\n```\n{"a": 1}\n```\nViel Erfolg') == {"a": 1}
assert _json_extrahieren('Ergebnis: {"a": {"b": 2}} fertig') == {"a": {"b": 2}}

# Pydantic: tolerant gegenüber schmutzigen Modell-Ausgaben
a = BelegAnalyse.model_validate({
    "kategorie": "Restaurant-Beleg / Quittung",
    "lesbar": "true",
    "brutto": "85,00",
    "trinkgeld": 5,
    "datum": "14.11.2026",
    "steuersaetze": "7 und 19",
    "hinweise": "nur ein String",
    "unbekanntes_feld": 1,
})
assert a.kategorie == "restaurant_beleg", a.kategorie
assert a.lesbar is True and a.brutto == 85.0 and a.datum == "2026-11-14"
assert a.steuersaetze == [7, 19] and a.hinweise == ["nur ein String"]
assert a.bewirtungsdaten()["Gesamtbetrag inkl. Trinkgeld"] == 90.0
assert BelegAnalyse.model_validate({"kategorie": "Quatsch"}).kategorie == "sonstiger_beleg"

from beleg_schema import anzeige  # noqa: E402

assert anzeige([7.0, 19.0]) == "7, 19"
assert anzeige(85.0) == "85,00"
assert anzeige(1234.5) == "1.234,50"
assert anzeige(None) == ""
assert anzeige("2026-09-04") == "04.09.2026"
# Anzeige -> Eingabefeld -> zurückgelesen muss denselben Wert ergeben
assert parse_betrag(anzeige(1234.5)) == 1234.5 and parse_datum(anzeige("2026-09-04")) == "2026-09-04"
assert werte_gleich("betrag", 133.4, anzeige(133.4))

from beleg_schema import zeitpunkt_de  # noqa: E402

assert zeitpunkt_de("2026-11-17T16:20:05") == "17.11.2026 16:20"
assert zeitpunkt_de(None) == ""

# Mehrseitige PDFs: alle Seiten werden gelesen (früher nur 2)
import pymupdf  # noqa: E402

from extraction import MAX_SEITEN, dateien_zu_bildern  # noqa: E402


def _pdf(seiten: int) -> bytes:
    doc = pymupdf.open()
    for i in range(seiten):
        doc.new_page().insert_text((72, 72), f"Seite {i + 1}")
    return doc.tobytes()


bilder, gesamt, gelesen = dateien_zu_bildern([("a.pdf", _pdf(3), "application/pdf")])
assert (len(bilder), gesamt, gelesen) == (3, 3, 3)
bilder, gesamt, gelesen = dateien_zu_bildern([("a.pdf", _pdf(4), "application/pdf"),
                                              ("b.pdf", _pdf(2), "application/pdf")])
assert (gesamt, gelesen) == (6, 6)
bilder, gesamt, gelesen = dateien_zu_bildern([("gross.pdf", _pdf(MAX_SEITEN + 3), "application/pdf")])
assert (gesamt, gelesen) == (MAX_SEITEN + 3, MAX_SEITEN)

# ---------------------------------------------------------------------------
# Echte Fälle aus dem Feedback (2026-11-17)
# ---------------------------------------------------------------------------
from checks import nachfragen_gruende, pruefen  # noqa: E402

# Hausbrauerei im Domhof: Rechnung 133,40 €, EC-Beleg 150,00 € -> Code rechnet MwSt. und Trinkgeld
domhof = BelegAnalyse.model_validate({
    "kategorie": "restaurant_mit_ec_beleg", "lesbar": True, "steuersatz_erkennbar": True,
    "datum_erkennbar": True, "ec_passt_zur_rechnung": True,
    "belegnummer": "1976", "restaurant_name": "Hausbrauerei im Domhof", "datum": "2026-09-04",
    "brutto": 133.40, "ec_betrag": 150.00,
    "trinkgeld": 11.40,  # vom Modell selbst (falsch) gerechnet -> muss überschrieben werden
    "mwst": 11.40,       # dito
    "steuerzeilen": [
        {"satz": 19, "netto": 23.45, "mwst": 4.45},
        {"satz": "7%", "netto": "98,60", "mwst": "6,90"},
    ],
})
assert domhof.mwst == 11.35, domhof.mwst
assert domhof.netto == 122.05, domhof.netto
assert domhof.trinkgeld == 16.60, domhof.trinkgeld
assert domhof.gesamtbetrag() == 150.00
assert domhof.steuersaetze == [7, 19]
assert pruefen(domhof) == [], pruefen(domhof)
assert nachfragen_gruende(domhof, []) == []

# Derselbe Beleg, aber Gesamtbetrag falsch gelesen (144,80 statt 133,40) -> Rechenprüfung schlägt an
falsch = domhof.model_copy(update={"brutto": 144.80})
befunde = pruefen(falsch)
assert any("Steuerzeilen ergeben 133,40 €" in b for b in befunde), befunde
assert any(g.startswith("Rechenprüfung") for g in nachfragen_gruende(falsch, befunde))

# Aral Tankstelle -> Tankbeleg, keine Bewirtung, keine Nachfrage nötig
aral = BelegAnalyse.model_validate({
    "kategorie": "tankbeleg", "lesbar": True, "steuersatz_erkennbar": True, "datum_erkennbar": True,
    "restaurant_name": "Aral Tankstelle", "datum": "2026-08-24", "brutto": 103.27, "ec_betrag": 103.27,
    "steuerzeilen": [{"satz": 19, "netto": 86.78, "mwst": 16.49, "brutto": 103.27}],
})
assert not aral.ist_bewirtung and aral.trinkgeld is None
assert "Aussteller" in aral.bewirtungsdaten() and "Trinkgeld" not in aral.bewirtungsdaten()
assert pruefen(aral) == [] and nachfragen_gruende(aral, []) == []

# Unsichere Kategorie / Ausland / EC passt nicht / kein Steuersatz -> Nachfrage
unsicher = aral.model_copy(update={"kategorie_unsicher": True, "kategorie_grund": "nur Snacks gekauft"})
assert any("nur Snacks" in g for g in nachfragen_gruende(unsicher, []))
assert any("Ausland" in g for g in nachfragen_gruende(aral.model_copy(update={"ausland": True}), []))
assert any("EC-Beleg passt nicht" in g
           for g in nachfragen_gruende(domhof.model_copy(update={"ec_passt_zur_rechnung": False}), []))
ohne_satz = BelegAnalyse.model_validate({"kategorie": "restaurant_beleg", "lesbar": True,
                                         "datum": "2026-09-04", "brutto": 20})
assert any("Steuersatz" in g for g in nachfragen_gruende(ohne_satz, []))
assert any("Ungewöhnlicher Steuersatz" in g
           for g in nachfragen_gruende(aral.model_copy(update={"steuersaetze": [16]}), []))
assert nachfragen_gruende(BelegAnalyse.model_validate({"kategorie": "sonstiger_beleg", "lesbar": True,
                                                       "steuersatz_erkennbar": True, "datum": "2026-01-01",
                                                       "brutto": 5}), [])
assert BelegAnalyse.model_validate({"ec_passt_zur_rechnung": "null"}).ec_passt_zur_rechnung is None

# Doppelt-Lesen: Vergleich zweier Lesungen
from checks import abweichungen  # noqa: E402

assert abweichungen(domhof, domhof) == {}
zahlendreher = domhof.model_copy(update={"belegnummer": "1916", "brutto": 138.40})
diff = abweichungen(domhof, zahlendreher)
assert set(diff) == {"Belegnummer", "Gesamtbetrag"}, diff
assert diff["Gesamtbetrag"] == ("133,40 €", "138,40 €")
# Schreibweise des Namens ist kein Lesefehler
assert abweichungen(aral, aral.model_copy(update={"restaurant_name": "ARAL Tankstelle Speyer"})) == {}
assert "Aussteller" in abweichungen(aral, aral.model_copy(update={"restaurant_name": "Shell"}))

# Cent-genaues Rechnen (keine Float-Fehler)
from beleg_schema import differenz, mwst_aus_brutto, mwst_aus_netto, summe  # noqa: E402

assert summe([0.1, 0.2]) == 0.3 and summe([4.45, 6.90]) == 11.35
assert differenz(150.00, 133.40) == 16.60
assert mwst_aus_netto(23.45, 19) == 4.46 and mwst_aus_brutto(20.00, 19) == 3.19

# Spalten-Verwechslung: Brutto pro Satz als Netto gelesen (echter Fall aus den Beispielbelegen)
verwechselt = BelegAnalyse.model_validate({
    "kategorie": "restaurant_beleg", "lesbar": True, "steuersatz_erkennbar": True, "datum": "2026-08-25",
    "brutto": 26.50,
    "steuerzeilen": [{"satz": 19, "netto": 20.00, "mwst": 3.19}, {"satz": 7, "netto": 6.50, "mwst": 0.43}],
})
assert [(z.netto, z.brutto) for z in verwechselt.steuerzeilen] == [(16.81, 20.00), (6.07, 6.50)]
assert verwechselt.netto == 22.88 and verwechselt.mwst == 3.62 and len(verwechselt.korrekturen) == 2
assert pruefen(verwechselt) == [], pruefen(verwechselt)
# ... aber NICHT umdeuten, wenn die Summe danach nicht zum Gesamtbetrag passt
falsch_gesamt = BelegAnalyse.model_validate({**verwechselt.model_dump(exclude={"steuerzeilen", "korrekturen"}),
    "brutto": 30.80,
    "steuerzeilen": [{"satz": 19, "netto": 20.00, "mwst": 3.19}, {"satz": 7, "netto": 6.50, "mwst": 0.43}]})
assert falsch_gesamt.korrekturen == [] and falsch_gesamt.steuerzeilen[0].netto == 20.00
assert any("ergeben 30,12 €" in b for b in pruefen(falsch_gesamt))
# Zeile in sich falsch: Netto + MwSt. != Brutto
kaputt = BelegAnalyse.model_validate({"brutto": 10, "steuerzeilen": [{"satz": None, "netto": 8, "mwst": 1, "brutto": 10}]})
assert any("≠ Brutto" in b for b in pruefen(kaputt))

# Gesamtbetrag inkl. aufgedrucktem Trinkgeld gelesen (echter Fall maximilian: Summe 66,80, Trinkgeld 3,20, Karte 70,00)
maxi = BelegAnalyse.model_validate({
    "kategorie": "restaurant_mit_ec_beleg", "lesbar": True, "steuersatz_erkennbar": True, "datum": "2026-05-21",
    "brutto": 70.00, "ec_betrag": 70.00, "trinkgeld": 3.20,
    "steuerzeilen": [{"satz": 7, "netto": 49.25, "mwst": 3.45, "brutto": 52.70},
                     {"satz": 19, "netto": 11.85, "mwst": 2.25, "brutto": 14.10}],
})
assert maxi.brutto == 66.80 and maxi.trinkgeld == 3.20 and maxi.ec_betrag == 70.00, maxi
assert maxi.gesamtbetrag() == 70.00 and pruefen(maxi) == [] and len(maxi.korrekturen) == 1
# Beides zugleich (echter Fall: Brutto-Spalte als Netto UND Gesamt inkl. 2,00 Trinkgeld)
beides = BelegAnalyse.model_validate({
    "brutto": 32.80, "ec_betrag": 32.80, "trinkgeld": 2.00,
    "steuerzeilen": [{"satz": 7, "netto": 26.90, "mwst": 1.76}, {"satz": 19, "netto": 3.90, "mwst": 0.62}],
})
assert beides.brutto == 30.80 and beides.trinkgeld == 2.00 and pruefen(beides) == [], (beides, pruefen(beides))
# Ohne aufgedrucktes Trinkgeld wird NICHT geraten
ohne_tg = BelegAnalyse.model_validate({"brutto": 70.00, "ec_betrag": 70.00, "steuerzeilen": maxi.model_dump()["steuerzeilen"]})
assert ohne_tg.brutto == 70.00 and ohne_tg.korrekturen == [] and pruefen(ohne_tg)

# Kategorien aus der App: Versionen, Löschen, Prompt, Validierung
from beleg_schema import KATEGORIEN, kategorien_registrieren  # noqa: E402
from kategorien import aktiv, aktueller_stand, auswahl, labels, prompt_abschnitt, schluessel_aus_name, wissens_hash  # noqa: E402
from prompts import system_prompt  # noqa: E402

assert schluessel_aus_name("Reisekosten Bahn & Flug") == "reisekosten_bahn_flug"
assert schluessel_aus_name("Übernachtung Ausland") == "uebernachtung_ausland"
versionen = [
    {"schluessel": "parken", "name": "Parken", "status": "entwurf", "version": 1, "zeitpunkt": "2026-11-17T10:00:00"},
    {"schluessel": "parken", "name": "Parkbeleg", "status": "aktiv", "version": 2, "zeitpunkt": "2026-11-17T11:00:00",
     "beschreibung": "Parkhaus, Parkschein", "pflichtangaben": ["Datum"]},
    {"schluessel": "tankbeleg", "name": "Umbenannt?", "status": "geloescht", "version": 1,
     "zeitpunkt": "2026-11-17T12:00:00", "beschreibung": "Auch Ladestrom"},
]
stand = aktueller_stand(versionen)
assert stand["parken"]["name"] == "Parkbeleg" and stand["parken"]["status"] == "aktiv"
assert stand["tankbeleg"]["name"] == "Tankbeleg (Kraftstoff)" and stand["tankbeleg"]["status"] == "aktiv"  # Standard bleibt
assert "Auch Ladestrom" in prompt_abschnitt(stand) and '"parken": Parkbeleg' in prompt_abschnitt(stand)
assert wissens_hash(stand) != wissens_hash(aktueller_stand([]))
geloescht = aktueller_stand(versionen + [{"schluessel": "parken", "status": "geloescht", "version": 3,
                                          "zeitpunkt": "2026-11-17T12:30:00"}])
assert "parken" not in aktiv(geloescht)
kategorien_registrieren(labels(stand))
assert BelegAnalyse.model_validate({"kategorie": "parken"}).kategorie == "parken"
kategorien_registrieren(labels(geloescht))
assert "parken" not in KATEGORIEN and BelegAnalyse.model_validate({"kategorie": "parken"}).kategorie == "sonstiger_beleg"
assert '"parken"' in system_prompt(prompt_abschnitt(stand))
assert any("Pflichtangaben laut Kategorie" in g for g in nachfragen_gruende(
    aral.model_copy(update={"fehlende_pflichtangaben": ["Mitarbeitername"]}), []))
# Auswahllisten für Menschen: Entwürfe sind wählbar (gekennzeichnet), gelöschte nicht
entwurf_stand = aktueller_stand([
    {"schluessel": "reisekosten", "name": "Reisekosten - Mitarbeiter", "status": "entwurf", "version": 1,
     "zeitpunkt": "2026-11-17T13:00:00"},
    {"schluessel": "parken", "name": "Parkbeleg", "status": "geloescht", "version": 3,
     "zeitpunkt": "2026-11-17T13:30:00"},
])
menschliche_auswahl = auswahl(entwurf_stand)
assert menschliche_auswahl["reisekosten"] == "Reisekosten - Mitarbeiter (Entwurf)"
assert menschliche_auswahl["tankbeleg"] == "Tankbeleg (Kraftstoff)"
assert "parken" not in menschliche_auswahl  # gelöscht -> nicht wählbar
assert "reisekosten" not in labels(entwurf_stand)  # Entwürfe bleiben aus dem Prompt
kategorien_registrieren(labels(entwurf_stand))
assert "reisekosten" not in KATEGORIEN  # ... und damit auch aus der KI-Validierung


# Testlauf: Erwartung und Zusammenfassung
from testlauf import Ergebnis, erwartete_kategorien, zusammenfassung  # noqa: E402

assert erwartete_kategorien("restaurant_beleg") >= {"restaurant_beleg", "restaurant_mit_ec_beleg"}
assert erwartete_kategorien("parken") == {"parken"}
lauf = {
    "a.pdf": {"vorher": Ergebnis("sonstiger_beleg", True, ["x"], "–", "–"),
              "nachher": Ergebnis("parken", False, [], "3,00 €", "01.01.2026")},
    "b.pdf": {"vorher": Ergebnis("parken", True, ["y"], "–", "–"),
              "nachher": Ergebnis(None, True, [], "", "", "Timeout")},
}
assert zusammenfassung(lauf, "vorher", {"parken"}) == {"belege": 2, "erkannt": 1, "nachfragen": 2, "fehler": 0,
                                                    "konten": {}}
assert zusammenfassung(lauf, "nachher", {"parken"}) == {"belege": 2, "erkannt": 1, "nachfragen": 1, "fehler": 1,
                                                     "konten": {}}

# Profilbild in der Seitenleiste (Google-Avatar, sonst Initialen; Namen werden HTML-sicher eingesetzt)
from auth import benutzer_karte  # noqa: E402

karte = benutzer_karte("Philipp <b>", "p@x.de", "https://lh3.googleusercontent.com/a/abc=s96-c")
assert "&lt;b&gt;" in karte and "<b>" not in karte and 'referrerpolicy="no-referrer"' in karte
assert ">AW</div>" in benutzer_karte("Annika Wahl", "a@x.de", None)
assert "javascript" not in benutzer_karte("X", "x@x.de", "javascript:alert(1)")

# Kalenderabgleich (Bewirtung / Übernachtung <-> Termin)
from datetime import datetime as _dt  # noqa: E402

from kalender import ZEITZONE, Termin, abgleichen, stadt_aus_adresse, termin_aus_api  # noqa: E402


def _t(titel, start, ende, ort="", teilnehmer=(), ganztags=False):
    return Termin(titel, _dt.fromisoformat(start).replace(tzinfo=ZEITZONE),
                  _dt.fromisoformat(ende).replace(tzinfo=ZEITZONE), ganztags, ort, "", list(teilnehmer))


assert stadt_aus_adresse("Große Himmelsgasse 6, 67346 Speyer") == "Speyer"
essen = BelegAnalyse.model_validate({"kategorie": "restaurant_mit_ec_beleg", "datum": "2026-09-04",
                                     "uhrzeit": "18:30", "restaurant_name": "Hausbrauerei im Domhof",
                                     "adresse": "Große Himmelsgasse 6, 67346 Speyer"})
# passt zeitlich (Termin 16:30–18:15, Zahlung 18:30)
ab = abgleichen(essen, [_t("Abendessen Kunde Müller", "2026-09-04T16:30", "2026-09-04T18:15",
                           teilnehmer=["Herr Müller", "Max Beispiel"])])
assert ab.status == "passend" and ab.termin.teilnehmer == ["Herr Müller", "Max Beispiel"], ab
# passt über den Namen, obwohl ohne Uhrzeit
ohne_zeit = essen.model_copy(update={"uhrzeit": None})
assert abgleichen(ohne_zeit, [_t("Team-Essen Domhof", "2026-09-04T12:00", "2026-09-04T13:00")]).status == "passend"
# Termin am Tag, aber falsche Zeit und anderer Ort -> Nachfrage, Termin als Kandidat
ab = abgleichen(essen, [_t("Zahnarzt", "2026-09-04T08:00", "2026-09-04T09:00", ort="Mannheim")])
assert ab.status == "kein_termin" and len(ab.kandidaten) == 1 and ab.nachfrage_grund
# gar kein Termin
assert abgleichen(essen, []).status == "kein_termin"
# Übernachtung: mehrtägige Reise über das Rechnungsdatum bzw. Ort im Termin
hotel = BelegAnalyse.model_validate({"kategorie": "uebernachtung", "datum": "2026-10-09",
                                     "restaurant_name": "Hotel Adler", "adresse": "Markt 1, 80331 München"})
assert abgleichen(hotel, [_t("Messe", "2026-10-07T00:00", "2026-10-10T00:00", ganztags=True)]).status == "passend"
assert abgleichen(hotel, [_t("Kundentermin München", "2026-10-08T10:00", "2026-10-08T12:00")]).status == "passend"
assert abgleichen(hotel, [_t("Kundentermin Köln", "2026-10-08T10:00", "2026-10-08T12:00")]).status == "kein_termin"
# Tankbeleg braucht keinen Termin
assert abgleichen(aral, []).status == "nicht_noetig"
# Google-API-Format
api = termin_aus_api({"summary": "Essen", "start": {"dateTime": "2026-09-04T16:30:00Z"},
                      "end": {"dateTime": "2026-09-04T18:00:00Z"}, "location": "Speyer",
                      "attendees": [{"email": "a@x.de", "displayName": "Anna"}, {"email": "raum@x.de", "resource": True},
                                    {"email": "nein@x.de", "responseStatus": "declined"}]})
assert api.start.hour == 18 and api.teilnehmer == ["Anna"]  # UTC -> Berlin (Sommerzeit), ohne Räume/Absagen
assert termin_aus_api({"start": {"date": "2026-10-07"}, "end": {"date": "2026-10-10"}}).ganztags



def test_logik():
    """Für pytest: Die Prüfungen oben liefen schon beim Import – kommt pytest hier an, ist alles grün."""


if __name__ == "__main__":
    print("Alle Logik-Tests bestanden.")
