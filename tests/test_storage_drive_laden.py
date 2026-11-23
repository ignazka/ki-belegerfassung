"""Einträge aus Drive laden: parallel, jeder Thread mit eigener Verbindung, nur fehlende Dateien (ohne Netz)."""
import importlib
import threading

import pytest


class _Anfrage:
    def __init__(self, ergebnis):
        self.ergebnis = ergebnis

    def execute(self, num_retries=0):
        return self.ergebnis() if callable(self.ergebnis) else self.ergebnis


class _Dateien:
    def __init__(self, inhalte, protokoll):
        self.inhalte, self.protokoll = inhalte, protokoll

    def list(self, **_kwargs):  # eine Seite, Reihenfolge wie von Drive (nach Name)
        return _Anfrage({"files": [{"id": i, "name": i} for i in self.inhalte]})

    def get_media(self, fileId, **_kwargs):
        def laden():
            self.protokoll.append((fileId, id(self), threading.get_ident()))
            return self.inhalte[fileId]
        return _Anfrage(laden)


class _Dienst:
    def __init__(self, inhalte, protokoll):
        self._dateien = _Dateien(inhalte, protokoll)

    def files(self):
        return self._dateien


@pytest.fixture
def drive(monkeypatch):
    import storage as modul
    modul = importlib.reload(modul)  # eigener, leerer _JSON_CACHE
    inhalte = {f"2026-11-0{i}_x.json": f'{{"nr": {i}}}'.encode() for i in range(1, 7)}
    inhalte["2026-11-07_kaputt.json"] = b"kein json"
    protokoll, dienste = [], []

    def dienst_bauen(_creds):
        d = _Dienst(inhalte, protokoll)
        dienste.append(d)
        return d

    monkeypatch.setattr(modul, "_drive_config", lambda: {"refresh_token": "t", "client_id": "c",
                                                         "client_secret": "s", "ordner_id": "o"})
    monkeypatch.setattr(modul, "_drive_credentials", lambda *a: object())
    monkeypatch.setattr(modul, "_unterordner_id", lambda name: "ordner")
    monkeypatch.setattr(modul, "_drive", lambda: _Dienst(inhalte, []))  # nur für die Liste
    monkeypatch.setattr(modul, "_drive_dienst_bauen", dienst_bauen)
    return modul, inhalte, protokoll, dienste


def test_alle_eintraege_in_reihenfolge_kaputte_uebersprungen(drive):
    storage, _inhalte, protokoll, _dienste = drive
    assert [e["nr"] for e in storage._drive_jsons_lesen("analysen")] == [1, 2, 3, 4, 5, 6]
    assert len(protokoll) == 7  # jede Datei genau einmal geladen


def test_jeder_thread_eigene_verbindung(drive):
    storage, _inhalte, protokoll, dienste = drive
    storage._drive_jsons_lesen("analysen")
    dienst_je_thread = {}
    for _datei, dienst, thread in protokoll:
        assert dienst_je_thread.setdefault(thread, dienst) == dienst  # nie eine Verbindung zweier Threads
    assert len(dienste) <= storage.DRIVE_PARALLEL


def test_nur_neue_dateien_werden_geladen(drive):
    storage, inhalte, protokoll, _dienste = drive
    storage._drive_jsons_lesen("analysen")
    protokoll.clear()
    inhalte["2026-11-08_neu.json"] = b'{"nr": 8}'
    assert [e["nr"] for e in storage._drive_jsons_lesen("analysen")][-1] == 8
    assert [p[0] for p in protokoll] == ["2026-11-08_neu.json"]


def test_beleg_in_papierkorb_drive(monkeypatch):
    """Nur Dateien dieses Belegs (Name endet auf _<sha16>.json) und die übergebenen Originale in den Papierkorb."""
    import storage as modul
    modul = importlib.reload(modul)
    sha = "a" * 64
    ordner = {"analysen": [f"2026-11-23T07-00-00_{sha[:16]}.json", "2026-11-23T08-00-00_bbbbbbbbbbbbbbbb.json"],
              "feedback": [f"2026-11-23T09-00-00_{sha[:16]}.json"], "nachfragen": [], "entscheidungen": [],
              "belege": ["seite1.png", "seite2.png"]}
    papierkorb = []

    class Liste:
        def __init__(self, q):
            self.q = q

        def execute(self, num_retries=0):
            name = self.q.split("'")[1]
            return {"files": [{"id": f"{name}/{n}", "name": n} for n in ordner[name]]}

    class Update:
        def __init__(self, file_id):
            self.file_id = file_id

        def execute(self, num_retries=0):
            papierkorb.append(self.file_id)

    class Dateien:
        def list(self, q, **_k):
            assert "trashed = false" in q
            return Liste(q)

        def update(self, fileId, body, **_k):
            assert body == {"trashed": True}  # nur in den Papierkorb, nie endgültig löschen
            return Update(fileId)

    monkeypatch.setattr(modul, "_drive_config", lambda: {"ordner_id": "o", "refresh_token": "t", "client_id": "c",
                                                         "client_secret": "s"})
    monkeypatch.setattr(modul, "_drive", lambda: type("D", (), {"files": lambda self: Dateien()})())
    monkeypatch.setattr(modul, "_unterordner_id", lambda name: name)
    assert modul.beleg_in_papierkorb(sha, ["belege/seite1.png"]) == 3
    assert sorted(papierkorb) == sorted([f"analysen/2026-11-23T07-00-00_{sha[:16]}.json",
                                         f"feedback/2026-11-23T09-00-00_{sha[:16]}.json", "belege/seite1.png"])
