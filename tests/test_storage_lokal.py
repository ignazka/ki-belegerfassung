"""Ablage ohne Google Drive (lokaler Ordner): nur anhängen, wieder einlesen, Duplikate, Belegdateien."""
import importlib

import pytest


@pytest.fixture
def storage(monkeypatch, tmp_path):
    import storage as modul
    modul = importlib.reload(modul)  # falls ein UI-Test Funktionen ersetzt hat
    monkeypatch.setattr(modul, "_drive_config", lambda: None)  # nie Drive, auch wenn lokal Secrets da sind
    monkeypatch.setenv("BELEG_DATENORDNER", str(tmp_path))
    return modul


def test_eintraege_anhaengen_und_laden(storage, tmp_path):
    storage.feedback_speichern({"datei_sha256": "a", "kommentar": "erste"})
    storage.feedback_speichern({"datei_sha256": "a", "kommentar": "zweite"})
    storage.analyse_speichern({"datei_sha256": "b", "gruende": []})
    fb = storage.feedback_laden()
    assert [e["kommentar"] for e in fb] == ["erste", "zweite"]  # nichts überschrieben
    assert all("zeitpunkt" in e for e in fb)
    assert storage.analysen_laden()[0]["datei_sha256"] == "b"
    assert (tmp_path / "feedback.jsonl").exists() and (tmp_path / "analysen.jsonl").exists()
    assert storage.schon_bewertet("a") and not storage.schon_bewertet("x")


def test_defekte_zeile_wird_uebersprungen(storage, tmp_path):
    storage.feedback_speichern({"datei_sha256": "a"})
    with (tmp_path / "feedback.jsonl").open("a", encoding="utf-8") as f:
        f.write("{kaputt\n")
    storage.feedback_speichern({"datei_sha256": "b"})
    assert [e["datei_sha256"] for e in storage.feedback_laden()] == ["a", "b"]


def test_nachfrage_nur_einmal_pro_beleg(storage):
    assert storage.nachfrage_speichern({"datei_sha256": "n1"}) is True
    assert storage.nachfrage_speichern({"datei_sha256": "n1"}) is False
    assert len(storage.nachfragen_laden()) == 1


def test_beleg_speichern_und_laden(storage, tmp_path):
    pfad = storage.beleg_speichern(b"PDFDATEN", "Rechnung.pdf", "abc123")
    assert pfad.startswith("belege/") and pfad.endswith(".pdf")
    assert storage.beleg_speichern(b"ANDERS", "Rechnung.pdf", "abc123") == pfad  # Duplikat: nicht überschreiben
    assert storage.beleg_laden(pfad) == b"PDFDATEN"


def test_leere_ablage(storage):
    assert storage.feedback_laden() == [] and storage.analysen_laden() == []
    assert storage.ablage_beschreibung() == "lokal" and storage.ablage_link() is None


def test_beleg_in_papierkorb_lokal(storage, tmp_path):
    storage.analyse_speichern({"datei_sha256": "weg", "gruende": []})
    storage.analyse_speichern({"datei_sha256": "bleibt", "gruende": []})
    storage.feedback_speichern({"datei_sha256": "weg", "kommentar": "falsch hochgeladen"})
    pfad = storage.beleg_speichern(b"bild", "seite.png", "weg" * 6)
    assert storage.beleg_in_papierkorb("weg", [pfad]) == 3  # Analyse, Prüfung, Originaldatei
    assert [e["datei_sha256"] for e in storage.analysen_laden()] == ["bleibt"]
    assert storage.feedback_laden() == []
    korb = tmp_path / "papierkorb"
    assert (korb / "analysen.jsonl").exists() and (korb / "feedback.jsonl").exists()  # wiederherstellbar
    assert (korb / pfad.split("/")[-1]).exists() and not (tmp_path / pfad).exists()
