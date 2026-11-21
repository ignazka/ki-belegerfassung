"""Interaktive Einführung: Tour (driver.js) durch die Oberfläche.

Startet automatisch beim allerersten Öffnen in einem Browser und jederzeit über den Knopf in der Seitenleiste.
Die Schritte stehen in assets/einfuehrung.js. Die Tour läuft komplett im Browser; sie wechselt die Tabs selbst
und löst keine Eingaben aus (also auch keinen Neustart des Skripts).
"""

import time

import streamlit as st

from browser_skripte import skript_einbetten, skript_html

_DRIVER_CSS = "https://cdn.jsdelivr.net/npm/driver.js@1.3.1/dist/driver.css"

# RE-ALIS-Look für die Popups (Akzentfarbe wie in .streamlit/config.toml)
_STIL = """
<style>
.driver-popover.praktikant-tour {border-radius: 12px; max-width: 360px; padding: 18px 20px; color: #14151A;}
.driver-popover.praktikant-tour, .driver-popover.praktikant-tour * {
  font-family: "Source Sans", "Source Sans 3", sans-serif !important;}
.praktikant-tour .driver-popover-title {font-size: 1.15rem; font-weight: 700;}
.praktikant-tour .driver-popover-description {font-size: .98rem; line-height: 1.45; margin-top: 6px;}
.praktikant-tour .driver-popover-progress-text {color: #5B6170;}
.praktikant-tour .driver-popover-footer button {font-family: inherit; font-size: .92rem; border-radius: 8px;
  padding: 5px 12px; text-shadow: none; border: 1px solid #C25100; color: #C25100; background: #fff;}
.praktikant-tour .driver-popover-footer .driver-popover-next-btn {background: #C25100; color: #fff;}
.praktikant-tour .driver-popover-footer button:hover {filter: brightness(.95);}
.praktikant-tour .driver-popover-close-btn {color: #5B6170;}
.praktikant-tour .tour-fortschritt {margin-top: 10px; font-size: .85rem; color: #5B6170;}
/* dunkles Design (data-thema setzt assets/thema.js) */
html[data-thema="dunkel"] .driver-popover.praktikant-tour {background: #22252D; color: #ECEEF2;
  box-shadow: 0 4px 24px rgba(0,0,0,.6); border: 1px solid #3A3E48;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-title {color: #ECEEF2;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-progress-text,
html[data-thema="dunkel"] .praktikant-tour .driver-popover-close-btn,
html[data-thema="dunkel"] .praktikant-tour .tour-fortschritt {color: #A3A9B6;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-footer button {background: transparent;
  border-color: #F07A2A; color: #F07A2A;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-footer .driver-popover-next-btn {background: #D65900;
  border-color: #D65900; color: #fff;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-arrow-side-left {border-left-color: #22252D;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-arrow-side-right {border-right-color: #22252D;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-arrow-side-top {border-top-color: #22252D;}
html[data-thema="dunkel"] .praktikant-tour .driver-popover-arrow-side-bottom {border-bottom-color: #22252D;}
</style>
"""

# Stylesheet von driver.js per Skript laden (<link> filtert Streamlit aus st.html heraus)
_CSS_LADEN = (
    "if (!document.querySelector('link[href=\"" + _DRIVER_CSS + "\"]')) {"
    " const l = document.createElement('link'); l.rel = 'stylesheet';"
    " l.href = '" + _DRIVER_CSS + "'; document.head.appendChild(l); }"
)


def einfuehrung_knopf() -> None:
    """Knopf in der Seitenleiste; ein Klick startet die Tour beim nächsten Zeichnen der Seite."""
    if st.sidebar.button("Einführung starten", icon=":material/school:", key="einfuehrung_start",
                         help="Zeigt Schritt für Schritt, wie die App funktioniert."):
        st.session_state["einfuehrung_jetzt"] = time.time()


def _tour_html(auto: bool, kennung: str) -> str:
    modus = "window.TOUR_AUTO = " + ("true" if auto else "false") + ";"  # kein const: Skript läuft ggf. mehrfach
    return skript_html("einfuehrung.js", vorab=_CSS_LADEN + "\n" + modus, kennung=kennung, stil=_STIL)


def einfuehrung_ausfuehren() -> None:
    """Am Ende des Skripts aufrufen (alle Elemente sind dann gezeichnet).

    - Automatischer Start: wird bei jedem Durchlauf mit gleichem Inhalt gezeichnet (bleibt so im Browser
      bestehen und läuft nicht ständig neu). Ob die Tour startet, entscheidet der Browser selbst – nur wenn
      sie dort noch nie lief (Merker im localStorage, siehe einfuehrung.js).
    - Knopf: direkt nach dem Klick ein neues Element (Zeitstempel) -> Tour startet immer.
    """
    st.html(_tour_html(True, "auto"), unsafe_allow_javascript=True, width="content")
    start = st.session_state.pop("einfuehrung_jetzt", None)
    if start:
        st.html(_tour_html(False, str(start)), unsafe_allow_javascript=True, width="content")


def belegansicht_einbetten() -> None:
    """Große Belegansicht im Browser (assets/belegansicht.js) – gleicher Inhalt, bleibt also bestehen."""
    skript_einbetten("belegansicht.js")
