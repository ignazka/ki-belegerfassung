"""Helles/dunkles Design: Konfiguration, Umschalter und Skript (assets/thema.js)."""
import re
import tomllib
from pathlib import Path

import attrappe as A
import marke

WURZEL = Path(__file__).resolve().parents[1]


def test_config_hat_helles_und_dunkles_design():
    thema = tomllib.loads((WURZEL / ".streamlit" / "config.toml").read_text(encoding="utf-8"))["theme"]
    assert "base" not in thema  # sonst wäre das Design fest
    assert thema["light"]["backgroundColor"] == "#FFFFFF" and thema["dark"]["backgroundColor"] == "#14151A"


def test_logo_im_dunklen_design_mit_heller_schrift():
    logo = marke._logo_dunkel_data_uri()
    assert logo.startswith("data:image/svg+xml;base64,") and logo != marke._logo_data_uri()


def test_app_zeigt_umschalter_und_bettet_skript_ein():
    at = A.app()
    A.keine_fehler(at)
    knopf = at.button(key="thema_wechsel")
    assert knopf.label == "Dunkles Design"
    htmls = [h.proto for h in at.get("html")]
    thema = [h for h in htmls if "stActiveTheme-" in h.body]
    assert len(thema) == 1 and thema[0].unsafe_allow_javascript
    skript = thema[0].body.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    assert not re.findall(r"<[/\w!]", skript)  # sonst entfernt Streamlits HTML-Filter das <script>
    assert 'html[data-thema="dunkel"]' in thema[0].body  # Logo-Tausch
    knopf.click().run()  # im Browser fängt das Skript den Klick ab; hier darf er nichts kaputt machen
    A.keine_fehler(at)
