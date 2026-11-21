"""Google-Login über Streamlits eingebautes OIDC (st.login / st.user).

Sicher per Voreinstellung ("fail closed"):
- Ohne [auth]-Secrets startet die App NICHT, es sei denn, lokal ist LOGIN_DEAKTIVIERT=1 gesetzt (.env).
- Reinkommen nur E-Mails aus [zugang].erlaubte_emails. Leere oder fehlende Liste = niemand.
"""

import html
import os
import re

import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _secrets_abschnitt(name: str) -> dict:
    try:
        return dict(st.secrets.get(name, {}))
    except FileNotFoundError:  # keine secrets.toml vorhanden
        return {}


def _login_deaktiviert() -> bool:
    """Nur für die lokale Entwicklung. Wird ausschließlich aus der Umgebung/.env gelesen, nie aus Secrets."""
    return os.getenv("LOGIN_DEAKTIVIERT") == "1"


def _erlaubte_emails() -> set[str]:
    liste = _secrets_abschnitt("zugang").get("erlaubte_emails", [])
    return {e.strip().lower() for e in liste if e.strip()}


# Abmelden unten links in der Seitenleiste, rot gefüllt.
# Selektoren passend zu Streamlit 1.67: die Seitenleiste wird zur Spalte, der Button (per order ans Ende
# sortiert) rutscht mit margin-top:auto nach unten – der „Ablage:“-Hinweis aus App.py bleibt darüber.
_ABMELDEN_CSS = (
    "<style>"
    'section[data-testid="stSidebar"] [data-testid="stSidebarContent"]'
    "{display:flex; flex-direction:column;}"
    'section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"]'
    "{display:flex; flex-direction:column; flex:1 1 auto; min-height:0; padding-bottom:1rem;}"
    'section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div'
    "{display:flex; flex-direction:column; flex:1 1 auto; min-height:0;}"
    'section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] div:has(> .stVerticalBlock)'
    "{display:flex; flex-direction:column; flex:1 1 auto; min-height:0;}"
    'section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] .stVerticalBlock'
    "{display:flex; flex-direction:column; flex:1 1 auto; min-height:0;}"
    'section[data-testid="stSidebar"] .st-key-abmelden{order:9999; margin-top:auto;}'
    # Weiß auf #C62828 = 5,6:1 (WCAG AA), Hover/Active dunkler
    'section[data-testid="stSidebar"] .st-key-abmelden button'
    "{width:100%; background:#C62828; border:1px solid #C62828; color:#fff;}"
    'section[data-testid="stSidebar"] .st-key-abmelden button:hover'
    "{background:#A11F1F; border-color:#A11F1F; color:#fff;}"
    'section[data-testid="stSidebar"] .st-key-abmelden button:active,'
    'section[data-testid="stSidebar"] .st-key-abmelden button:focus:not(:active)'
    "{background:#8E1B1B; border-color:#8E1B1B; color:#fff;}"
    'section[data-testid="stSidebar"] .st-key-abmelden button:focus-visible'
    "{outline:3px solid #FF8A80; outline-offset:2px;}"
    'section[data-testid="stSidebar"] .st-key-abmelden button p{color:#fff;}'
    "</style>"
)


def login_erzwingen() -> None:
    """Stoppt das Skript, solange kein freigeschalteter Benutzer angemeldet ist."""
    if _login_deaktiviert():
        st.sidebar.warning("Login deaktiviert (LOGIN_DEAKTIVIERT=1) – nur lokal verwenden!")
        return

    if not _secrets_abschnitt("auth"):
        st.error("Login ist nicht konfiguriert ([auth] fehlt in den Secrets). Die App ist gesperrt.")
        st.stop()

    if not st.user.get("is_logged_in", False):
        # spät importiert: auth soll ohne Assets lauffähig bleiben
        from marke import google_login_button, kopfzeile, login_fusszeile, thema_einbetten

        st.markdown('<div style="height:16vh"></div>', unsafe_allow_html=True)  # Inhalt etwa mittig
        kopfzeile(zentriert=True, gross=True)
        google_login_button(st.login)
        login_fusszeile()
        thema_einbetten()  # gewähltes Design auch hier (Logo, Fußzeile)
        st.stop()

    email = (st.user.get("email") or "").strip().lower()
    if not st.user.get("email_verified", False) or email not in _erlaubte_emails():
        st.error(f"Das Konto {email or '(ohne E-Mail)'} ist für diese App nicht freigeschaltet.")
        st.button("Abmelden", on_click=st.logout)
        st.stop()

    with st.sidebar:
        st.markdown(benutzer_karte(st.user.get("name") or email, email, st.user.get("picture")),
                    unsafe_allow_html=True)
        st.markdown(_ABMELDEN_CSS, unsafe_allow_html=True)
        st.button("Abmelden", key="abmelden", on_click=st.logout)


def _initialen(name: str) -> str:
    teile = [t for t in re.split(r"[\s.@_-]+", name) if t]
    return "".join(t[0] for t in teile[:2]).upper() or "?"


def benutzer_karte(name: str, email: str, bild_url: str | None) -> str:
    """'Angemeldet als' mit rundem Google-Profilbild (oder Initialen, falls keins vorhanden)."""
    n, e = html.escape(name), html.escape(email)
    if bild_url and bild_url.startswith("https://"):
        avatar = (f'<img src="{html.escape(bild_url, quote=True)}" alt="Profilbild von {n}" '
                  'referrerpolicy="no-referrer" style="width:40px;height:40px;border-radius:50%;'
                  'object-fit:cover;flex-shrink:0">')
    else:
        avatar = ('<div aria-hidden="true" style="width:40px;height:40px;border-radius:50%;flex-shrink:0;'
                  'background:#C25100;color:#fff;display:flex;align-items:center;justify-content:center;'
                  f'font-weight:700">{html.escape(_initialen(name))}</div>')
    return (
        '<div style="display:flex;align-items:center;gap:.75rem;margin-bottom:.5rem">'
        f"{avatar}"
        '<div style="line-height:1.3;min-width:0">'
        f'<div style="font-size:.85rem;opacity:.8">Angemeldet als</div>'
        f'<div style="font-weight:700;overflow-wrap:anywhere">{n}</div>'
        f'<div style="font-size:.85rem;opacity:.8;overflow-wrap:anywhere">{e}</div>'
        "</div></div>"
    )


def aktueller_benutzer() -> str | None:
    """E-Mail des angemeldeten Benutzers oder None (lokal ohne Login)."""
    if not _login_deaktiviert() and st.user.get("is_logged_in", False):
        return st.user.get("email")
    return None


def darf_kategorien_bearbeiten() -> bool:
    """[zugang].kategorien_bearbeiter = ["annika@..."] -> nur diese. Ohne Liste: alle angemeldeten Benutzer."""
    liste = {e.strip().lower() for e in _secrets_abschnitt("zugang").get("kategorien_bearbeiter", []) if e.strip()}
    if not liste:
        return True
    return (aktueller_benutzer() or "").lower() in liste
