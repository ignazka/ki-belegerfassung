"""Kalender per Knopf verbinden: Google-Anmeldung nur für „Kalender lesen“, direkt aus der App.

Ablauf:
1. Knopf „Kalender verbinden“ öffnet `anmelde_url(...)` (Google fragt: Kalender lesen erlauben?).
2. Google leitet zurück auf die App-Adresse mit ?code=…&state=…
3. `state_pruefen` stellt sicher, dass der Rücksprung von uns angestoßen wurde (signiert, max. 15 Minuten alt,
   für denselben App-Benutzer).
4. `code_einloesen` tauscht den Code gegen einen dauerhaften Zugang (refresh_token) + E-Mail des Kontos.
5. Der Zugang wird mit `verschluesseln` abgelegt (Schlüssel aus dem Login-Geheimnis [auth].cookie_secret),
   damit eine Kopie aus dem Drive-Ordner allein nichts nützt.

Bewusst ohne Streamlit – die App (App.py) und die Ablage (storage.py) rufen nur diese Funktionen auf.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPES = ["openid", "email", "https://www.googleapis.com/auth/calendar.readonly"]
ANMELDE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_PRAEFIX = "kal."            # erkennt unseren Rücksprung (st.login nutzt einen eigenen Pfad)
STATE_MAX_ALTER_S = 15 * 60


class VerbindungsFehler(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Adresse für den Rücksprung
# ---------------------------------------------------------------------------

def ruecksprung_url(login_redirect_uri: str) -> str:
    """Aus [auth].redirect_uri (…/oauth2callback) die App-Startseite machen: https://…streamlit.app/"""
    url = (login_redirect_uri or "").strip()
    if url.endswith("/oauth2callback"):
        url = url[: -len("oauth2callback")]
    return url if url.endswith("/") else url + "/"


# ---------------------------------------------------------------------------
# state: signiert, mit Zeitstempel und Benutzer
# ---------------------------------------------------------------------------

def _b64(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).decode().rstrip("=")


def _b64_zurueck(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signatur(geheimnis: str, nutzdaten: str) -> str:
    return _b64(hmac.new(geheimnis.encode(), ("kalender-state:" + nutzdaten).encode(), hashlib.sha256).digest())


def state_erzeugen(geheimnis: str, benutzer: str | None, jetzt: float | None = None) -> str:
    nutzdaten = _b64(json.dumps({"t": int(jetzt if jetzt is not None else time.time()), "u": benutzer or "",
                                 "n": secrets.token_hex(8)}).encode())
    return f"{STATE_PRAEFIX}{nutzdaten}.{_signatur(geheimnis, nutzdaten)}"


def ist_kalender_state(state: str | None) -> bool:
    return bool(state) and state.startswith(STATE_PRAEFIX)


def state_pruefen(geheimnis: str, state: str, benutzer: str | None, jetzt: float | None = None) -> None:
    """Wirft VerbindungsFehler, wenn der Rücksprung gefälscht, zu alt oder für einen anderen Benutzer ist."""
    try:
        nutzdaten, signatur = state[len(STATE_PRAEFIX):].split(".", 1)
        inhalt = json.loads(_b64_zurueck(nutzdaten))
    except (ValueError, json.JSONDecodeError):
        raise VerbindungsFehler("Ungültige Rückmeldung von Google – bitte noch einmal verbinden.") from None
    if not hmac.compare_digest(signatur, _signatur(geheimnis, nutzdaten)):
        raise VerbindungsFehler("Rückmeldung von Google ließ sich nicht bestätigen – bitte noch einmal verbinden.")
    alter = (jetzt if jetzt is not None else time.time()) - inhalt.get("t", 0)
    if not 0 <= alter <= STATE_MAX_ALTER_S:
        raise VerbindungsFehler("Die Anmeldung hat zu lange gedauert – bitte noch einmal verbinden.")
    if (inhalt.get("u") or "") != (benutzer or ""):
        raise VerbindungsFehler("Die Anmeldung wurde von einem anderen App-Benutzer gestartet.")


# ---------------------------------------------------------------------------
# Google-Anmeldung
# ---------------------------------------------------------------------------

def anmelde_url(client_id: str, redirect_uri: str, state: str, login_hint: str | None = None) -> str:
    werte = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",   # dauerhafter Zugang (refresh_token)
        "prompt": "consent",        # sonst liefert Google bei erneutem Verbinden keinen neuen refresh_token
        "state": state,
    }
    if login_hint:
        werte["login_hint"] = login_hint
    return f"{ANMELDE_URL}?{urllib.parse.urlencode(werte)}"


def _email_aus_id_token(id_token: str | None) -> str | None:
    """Nur zur Anzeige („verbunden über …“). Der Token kommt direkt von Google (TLS), daher ohne Signaturprüfung."""
    try:
        return json.loads(_b64_zurueck(id_token.split(".")[1])).get("email")
    except Exception:
        return None


def code_einloesen(code: str, client_id: str, client_secret: str, redirect_uri: str, *, oeffnen=None) -> dict:
    """Code gegen Zugang tauschen -> {"refresh_token", "konto", "scope"}. oeffnen: für Tests ersetzbar."""
    daten = urllib.parse.urlencode({
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": redirect_uri, "grant_type": "authorization_code",
    }).encode()
    anfrage = urllib.request.Request(TOKEN_URL, data=daten, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with (oeffnen or urllib.request.urlopen)(anfrage, timeout=20) as antwort:
            ergebnis = json.loads(antwort.read())
    except urllib.error.HTTPError as e:
        try:
            grund = json.loads(e.read()).get("error_description") or e.reason
        except Exception:
            grund = e.reason
        raise VerbindungsFehler(f"Google hat die Anmeldung abgelehnt: {grund}") from None
    except OSError as e:
        raise VerbindungsFehler(f"Google nicht erreichbar: {e}") from None
    if "calendar.readonly" not in (ergebnis.get("scope") or ""):
        raise VerbindungsFehler("Das Leserecht für den Kalender wurde nicht erteilt – beim Verbinden bitte das "
                                "Häkchen bei „Kalender ansehen“ setzen.")
    if not ergebnis.get("refresh_token"):
        raise VerbindungsFehler("Google hat keinen dauerhaften Zugang geliefert – bitte noch einmal verbinden.")
    return {"refresh_token": ergebnis["refresh_token"], "konto": _email_aus_id_token(ergebnis.get("id_token")),
            "scope": ergebnis.get("scope")}


# ---------------------------------------------------------------------------
# Verschlüsselt ablegen
# ---------------------------------------------------------------------------

def _fernet(geheimnis: str):
    from cryptography.fernet import Fernet

    schluessel = hashlib.sha256(("praktikantai-kalender:" + geheimnis).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(schluessel))


def verschluesseln(geheimnis: str, klartext: str) -> str:
    return _fernet(geheimnis).encrypt(klartext.encode()).decode()


def entschluesseln(geheimnis: str, verschluesselt: str) -> str | None:
    """None, wenn der Schlüssel nicht passt (z. B. Login-Geheimnis geändert) -> neu verbinden."""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(geheimnis).decrypt(verschluesselt.encode()).decode()
    except (InvalidToken, ValueError):
        return None
