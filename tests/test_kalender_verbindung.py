"""Kalender per Knopf verbinden: Rücksprung-Prüfung, Code einlösen, Verschlüsselung, Ablage und Abgleich
über mehrere Kalender – ohne Google, ohne Drive (lokaler Ordner)."""
import importlib
import io
import json
import urllib.error
import urllib.parse
from datetime import datetime

import pytest

import kalender_verbindung as kv
from beleg_schema import BelegAnalyse
from kalender import ZEITZONE, Termin

GEHEIM = "test-geheimnis"


# --- Baustein kalender_verbindung ---------------------------------------------------------------

def test_ruecksprung_url_aus_login_adresse():
    assert kv.ruecksprung_url("https://beleg-assistent.streamlit.app/oauth2callback") == \
        "https://beleg-assistent.streamlit.app/"
    assert kv.ruecksprung_url("http://localhost:8501/oauth2callback") == "http://localhost:8501/"


def test_state_echt_gefaelscht_alt_fremd():
    state = kv.state_erzeugen(GEHEIM, "annika@firma.de", jetzt=1000)
    assert kv.ist_kalender_state(state) and not kv.ist_kalender_state("irgendwas")
    kv.state_pruefen(GEHEIM, state, "annika@firma.de", jetzt=1100)  # ok
    with pytest.raises(kv.VerbindungsFehler, match="bestätigen"):
        kv.state_pruefen("anderes-geheimnis", state, "annika@firma.de", jetzt=1100)
    with pytest.raises(kv.VerbindungsFehler, match="zu lange"):
        kv.state_pruefen(GEHEIM, state, "annika@firma.de", jetzt=1000 + kv.STATE_MAX_ALTER_S + 1)
    with pytest.raises(kv.VerbindungsFehler, match="anderen App-Benutzer"):
        kv.state_pruefen(GEHEIM, state, "jemand@firma.de", jetzt=1100)
    with pytest.raises(kv.VerbindungsFehler):
        kv.state_pruefen(GEHEIM, "kal.kaputt", None)


def test_anmelde_url_fragt_nur_kalender_lesen_dauerhaft():
    url = kv.anmelde_url("client-123", "https://app/", "kal.x")
    werte = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert werte["scope"] == "openid email https://www.googleapis.com/auth/calendar.readonly"
    assert werte["access_type"] == "offline" and werte["prompt"] == "consent"
    assert werte["redirect_uri"] == "https://app/" and werte["state"] == "kal.x"


def _antwort(daten: dict):
    class A(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    return A(json.dumps(daten).encode())


def _id_token(email):
    import base64
    nutz = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"kopf.{nutz}.sig"


def test_code_einloesen_ok_und_fehlerfaelle():
    gesendet = {}

    def oeffnen(anfrage, timeout):
        gesendet.update(dict(urllib.parse.parse_qsl(anfrage.data.decode())))
        return _antwort({"refresh_token": "1//rt", "scope": "openid https://www.googleapis.com/auth/calendar.readonly",
                         "id_token": _id_token("annika@firma.de")})

    z = kv.code_einloesen("c0de", "cid", "csec", "https://app/", oeffnen=oeffnen)
    assert z["refresh_token"] == "1//rt" and z["konto"] == "annika@firma.de"
    assert gesendet["grant_type"] == "authorization_code" and gesendet["redirect_uri"] == "https://app/"

    with pytest.raises(kv.VerbindungsFehler, match="Leserecht"):  # Häkchen beim Kalender nicht gesetzt
        kv.code_einloesen("c", "cid", "csec", "u", oeffnen=lambda a, timeout: _antwort(
            {"refresh_token": "x", "scope": "openid email"}))
    with pytest.raises(kv.VerbindungsFehler, match="keinen dauerhaften"):
        kv.code_einloesen("c", "cid", "csec", "u", oeffnen=lambda a, timeout: _antwort(
            {"scope": "https://www.googleapis.com/auth/calendar.readonly"}))

    def abgelehnt(anfrage, timeout):
        raise urllib.error.HTTPError(kv.TOKEN_URL, 400, "Bad Request", {},
                                     io.BytesIO(b'{"error_description": "Bad Request: redirect_uri_mismatch"}'))
    with pytest.raises(kv.VerbindungsFehler, match="redirect_uri_mismatch"):
        kv.code_einloesen("c", "cid", "csec", "u", oeffnen=abgelehnt)


def test_verschluesselung():
    geheim = kv.verschluesseln(GEHEIM, "1//refresh")
    assert "1//refresh" not in geheim
    assert kv.entschluesseln(GEHEIM, geheim) == "1//refresh"
    assert kv.entschluesseln("anderes", geheim) is None  # Login-Geheimnis geändert -> neu verbinden


# --- Ablage (lokal) -------------------------------------------------------------------------------

@pytest.fixture
def storage(monkeypatch, tmp_path):
    import storage as modul
    modul = importlib.reload(modul)
    monkeypatch.setattr(modul, "_drive_config", lambda: None)
    monkeypatch.setenv("BELEG_DATENORDNER", str(tmp_path))
    secrets = {"auth": {"client_id": "cid", "client_secret": "csec", "cookie_secret": GEHEIM,
                        "redirect_uri": "https://app.streamlit.app/oauth2callback"}}
    monkeypatch.setattr(modul, "_secrets_abschnitt", lambda name: dict(secrets.get(name, {})))
    monkeypatch.setattr(kv, "state_pruefen", lambda *a, **k: None)
    monkeypatch.setattr(kv, "code_einloesen", lambda code, *a, **k: {
        "refresh_token": f"rt-{code}", "konto": "annika@firma.de" if code != "anderes" else "chef@firma.de"})
    return modul


def test_verbinden_waehlen_trennen(storage, tmp_path):
    assert storage.kalender_verbinden_moeglich()
    assert "redirect_uri=https%3A%2F%2Fapp.streamlit.app%2F" in storage.kalender_anmelde_url("annika@firma.de")
    assert storage.kalender_verbindung() is None and storage.kalender_status() == "nicht verbunden"

    v = storage.kalender_ruecksprung("c1", "kal.x", "annika@firma.de", "annika@firma.de")
    assert v["konto"] == "annika@firma.de" and v["kalender"] == [] and v["token_ok"]
    assert storage.kalender_status() == "verbunden, noch kein Kalender gewählt"
    assert storage._kalender_zugriff() is None  # ohne Auswahl kein Abgleich
    assert "rt-c1" not in (tmp_path / "kalender_zugang.jsonl").read_text(encoding="utf-8")  # verschlüsselt

    storage.kalender_auswahl_speichern([{"id": "firma@group", "name": "Firma"}, {"id": "annika@firma.de"}], "a")
    assert storage.kalender_status() == "verbunden (2 Kalender)"
    token, cid, csec, ids, quelle = storage._kalender_zugriff()
    assert (token, cid, ids, quelle) == ("rt-c1", "cid", ["firma@group", "annika@firma.de"], "app")

    storage.kalender_ruecksprung("c2", "kal.y", None, None)  # gleiches Konto neu verbunden -> Auswahl bleibt
    assert len(storage.kalender_verbindung()["kalender"]) == 2 and storage._kalender_zugriff()[0] == "rt-c2"
    storage.kalender_ruecksprung("anderes", "kal.z", None, None)  # anderes Konto -> neu wählen
    assert storage.kalender_verbindung()["kalender"] == []

    storage.kalender_trennen("a")
    assert storage.kalender_verbindung() is None and storage._kalender_zugriff() is None
    assert len((tmp_path / "kalender_zugang.jsonl").read_text(encoding="utf-8").splitlines()) == 5  # nur angehängt


def test_geaendertes_login_geheimnis_macht_verbindung_ungueltig(storage, monkeypatch):
    storage.kalender_ruecksprung("c1", "kal.x", None, None)
    storage.kalender_auswahl_speichern([{"id": "k1", "name": "K1"}], None)
    andere = {"auth": {"client_id": "cid", "client_secret": "csec", "cookie_secret": "neu",
                       "redirect_uri": "https://app/oauth2callback"}}
    monkeypatch.setattr(storage, "_secrets_abschnitt", lambda name: dict(andere.get(name, {})))
    assert storage.kalender_verbindung()["token_ok"] is False
    assert storage.kalender_status().startswith("Verbindung ungültig")
    assert storage._kalender_zugriff() is None


def _termin(titel, start, ende):
    return Termin(titel=titel, start=datetime.fromisoformat(start).replace(tzinfo=ZEITZONE),
                  ende=datetime.fromisoformat(ende).replace(tzinfo=ZEITZONE))


def test_abgleich_sucht_in_allen_gewaehlten_kalendern(storage, monkeypatch):
    storage.kalender_ruecksprung("c1", "kal.x", None, None)
    storage.kalender_auswahl_speichern([{"id": "firma", "name": "Firma"}, {"id": "chef", "name": "Chef"}], None)
    termine = {"firma": [_termin("Teamrunde", "2026-09-04T09:00", "2026-09-04T10:00")],
               "chef": [_termin("Abendessen Kunde", "2026-09-04T17:00", "2026-09-04T18:15"),
                        _termin("Teamrunde", "2026-09-04T09:00", "2026-09-04T10:00")]}  # doppelt
    gefragt = []

    def laden(kid, von, bis, token, cid, csec):
        gefragt.append((kid, token))
        return termine[kid]
    monkeypatch.setattr(storage, "_kalender_termine", laden)
    essen = BelegAnalyse.model_validate({"kategorie": "restaurant_beleg", "datum": "2026-09-04", "uhrzeit": "18:30",
                                         "restaurant_name": "Domhof"})
    ab = storage.kalender_abgleichen(essen)
    assert gefragt == [("firma", "rt-c1"), ("chef", "rt-c1")]
    assert ab.status == "passend" and ab.termin.titel == "Abendessen Kunde"


def test_abgleich_ohne_verbindung_nutzt_weiter_die_secrets(storage, monkeypatch):
    secrets = {"kalender": {"kalender_id": "firma@group"}}
    monkeypatch.setattr(storage, "_secrets_abschnitt", lambda name: dict(secrets.get(name, {})))
    monkeypatch.setattr(storage, "_drive_config", lambda: {"refresh_token": "drive-rt", "client_id": "d",
                                                           "client_secret": "s", "ordner_id": "o"})
    monkeypatch.setattr(storage, "_eintraege_laden", lambda art: [])
    assert storage._kalender_zugriff() == ("drive-rt", "d", "s", ["firma@group"], "secrets")
    assert storage.kalender_status() == "über Secrets eingerichtet"
