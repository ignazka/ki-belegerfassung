"""Name und Kopfzeile der App: „PraktikantAI“ (AI fett, in Marken-Orange), darunter „powered by“ + Logo."""

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

APP_NAME = "PraktikantAI"
# Marken-Orange leicht abgedunkelt: 4,0:1 auf Weiß – reicht für große Schrift (WCAG AA verlangt dort 3:1)
_AI_FARBE = "#D65900"
ASSETS = Path(__file__).parent / "assets"


@lru_cache(maxsize=1)
def _logo_data_uri() -> str:
    """Logo direkt in die Seite einbetten (kein zusätzlicher Dateiabruf nötig)."""
    svg = (ASSETS / "realis-logo.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")


@lru_cache(maxsize=1)
def _logo_dunkel_data_uri() -> str:
    """Logo für das dunkle Design: Schriftzug hell statt schwarz (das Orange bleibt)."""
    svg = (ASSETS / "realis-logo.svg").read_text(encoding="utf-8").replace("#14151A", _TEXT_DUNKEL)
    svg = svg.replace("<svg ", f'<svg fill="{_TEXT_DUNKEL}" ', 1)  # Teile ohne eigene Farbe (Bindestrich)
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")


_TEXT_DUNKEL = "#ECEEF2"  # Schriftfarbe im dunklen Design (wie textColor in .streamlit/config.toml)


_THEMA_HILFE = ("Helles oder dunkles Design. Die Seite lädt dabei neu – nicht gespeicherte Eingaben gehen "
                "verloren.")


def thema_knopf() -> None:
    """Umschalter Hell/Dunkel als reines Symbol (Mond bzw. Sonne). Im aktuellen Container zeichnen (in der
    Seitenleiste neben „Abmelden“, siehe auth.py). Den Klick behandelt assets/thema.js im Browser."""
    st.button("", icon=":material/dark_mode:", key="thema_wechsel", help=_THEMA_HILFE)


def thema_einbetten() -> None:
    """Hell/Dunkel: Skript assets/thema.js (setzt <html data-thema>, bedient den Knopf thema_wechsel) und das
    Logo für das dunkle Design."""
    from browser_skripte import skript_einbetten  # erst hier: marke wird auch von der Login-Seite genutzt

    try:
        logo = _logo_dunkel_data_uri()
        stil = ('<style>html[data-thema="dunkel"] img[data-testid="stSidebarLogo"],'
                ' html[data-thema="dunkel"] img[data-testid="stHeaderLogo"],'
                f' html[data-thema="dunkel"] img.realis-logo {{content: url("{logo}");}}'
                ' html[data-thema="dunkel"] footer.login-fuss {background: #14151A !important;}</style>')
    except OSError:
        stil = ""
    skript_einbetten("thema.js", stil=stil)


def kopfzeile(zentriert: bool = False, gross: bool = False) -> None:
    """Hauptüberschrift als echte h1 (für Screenreader), darunter „powered by RE-ALIS“.
    gross=True für die Login-Seite (Titel und Logo deutlich größer)."""
    titel_groesse, logo_hoehe, text_groesse = ("clamp(2.4rem, 9vw, 4.6rem)", "2.4rem", "1.1rem") if gross else ("3.2rem", "1.6rem", ".85rem")
    try:
        logo = (f'<img class="realis-logo" src="{_logo_data_uri()}" alt="RE-ALIS" '
                f'style="height:{logo_hoehe};width:auto;vertical-align:middle">')
    except OSError:  # Logo-Datei fehlt -> Text statt Bild
        logo = "<strong>RE-ALIS</strong>"
    st.markdown(
        f'<h1 style="margin-bottom:0;padding-bottom:0;font-size:{titel_groesse};line-height:1.1;'
        f'letter-spacing:-.02em;text-align:{"center" if zentriert else "left"}">'
        '<span style="font-weight:400">Praktikant</span>'
        f'<span style="font-weight:800;color:{_AI_FARBE}">AI</span></h1>'
        '<div style="display:flex;align-items:center;gap:.6rem;margin:.2rem 0 1.75rem;'
        f'justify-content:{"center" if zentriert else "flex-start"};'
        f'font-size:{text_groesse};opacity:.75">powered by {logo}</div>',
        unsafe_allow_html=True,
    )


# Offizielles Google-„G“ (Google Sign-In Branding) als eingebettetes SVG
_GOOGLE_G = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
    '<path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 '
    '5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 '
    '7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>'
    '<path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 '
    '20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>'
    '<path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 '
    '0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>'
    "</svg>"
)


def google_login_button(on_click) -> None:
    """Button im Standard-Design „Mit Google anmelden“ (hell, Pillenform, buntes G), mittig, nur so breit wie
    sein Inhalt. Technisch ein normaler Streamlit-Button (Tastatur/Screenreader bleiben erhalten)."""
    g = "data:image/svg+xml;base64," + base64.b64encode(_GOOGLE_G.encode()).decode("ascii")
    st.markdown(
        "<style>"
        # Jede Ebene um den Button zentriert seinen Inhalt; der Button selbst bleibt so breit wie sein Text
        ".st-key-google_login, .st-key-google_login > div, .st-key-google_login .stButton {"
        " display: flex !important; justify-content: center !important; width: 100% !important;}"
        ".st-key-google_login button {width: auto !important; flex: 0 0 auto !important;}"
        ".st-key-google_login button {background: #FFFFFF; color: #1F1F1F; border: 1px solid #747775;"
        " border-radius: 20px; height: 44px; padding: 0 16px 0 12px; font-family: Roboto, Arial, sans-serif;"
        " font-weight: 500; font-size: 15px; letter-spacing: .25px; box-shadow: none;}"
        ".st-key-google_login button:hover {background: #F8F9FA; border-color: #747775; color: #1F1F1F;"
        " box-shadow: 0 1px 2px rgba(60,64,67,.30), 0 1px 3px 1px rgba(60,64,67,.15);}"
        ".st-key-google_login button:active, .st-key-google_login button:focus:not(:active) {"
        " background: #F1F3F4; border-color: #747775; color: #1F1F1F;}"
        ".st-key-google_login button:focus-visible {outline: 3px solid #1A73E8; outline-offset: 2px;}"
        ".st-key-google_login button::before {content: ''; width: 20px; height: 20px; margin-right: 12px;"
        f" background: url('{g}') center / contain no-repeat; flex-shrink: 0;}}"
        ".st-key-google_login button p {font-size: 15px; font-weight: 500;}"
        "</style>",
        unsafe_allow_html=True,
    )
    st.button("Mit Google anmelden", key="google_login", on_click=on_click)


def login_fusszeile() -> None:
    """Fußzeile ganz unten auf der Login-Seite mit Link zur Datenschutzerklärung."""
    st.markdown(
        '<footer class="login-fuss" style="position:fixed;left:0;right:0;bottom:0;padding:.9rem 1rem;text-align:center;'
        'font-size:.85rem;background:#FFFFFF;border-top:1px solid rgba(128,128,128,.25)">'
        '<a href="?seite=datenschutz" target="_self">Datenschutzerklärung</a>'
        "</footer>",
        unsafe_allow_html=True,
    )
