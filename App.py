"""BelegAssistent (RE-ALIS) – Belege analysieren, Nachfragen, Kategorien, Auswertung."""

from datetime import date, datetime
from types import SimpleNamespace
import csv
import html
import io
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import streamlit as st

from auth import aktueller_benutzer, darf_kategorien_bearbeiten, login_erzwingen
from beleg_schema import FEEDBACK_FELDER, KATEGORIEN, STANDARD_KATEGORIEN, BelegAnalyse, parse_datum, kategorien_registrieren, konten_registrieren, anzeige, normalisieren, werte_gleich, zeitpunkt_de
from datenschutz import ist_datenschutzseite, zeige_datenschutz
from extraction import MAX_SEITEN, MODEL, MODEL_GROSS, AnalyseFehler, dateien_zu_bildern, text_anfrage_json
from pipeline import beleg_lesen
from kalender_verbindung import VerbindungsFehler, ist_kalender_state
from testlauf import MAX_BELEGE as MAX_TESTBELEGE
from testlauf import ausfuehren as testlauf_ausfuehren
from testlauf import erwartete_kategorien, konten_vereinigen
from testlauf import zusammenfassung as testlauf_zusammenfassung
from marke import APP_NAME, kopfzeile, thema_einbetten, thema_knopf
from einfuehrung import belegansicht_einbetten, einfuehrung_ausfuehren, einfuehrung_knopf
from kategorien import ASSISTENT_PROMPT, aktueller_stand, assistent_nachricht, labels, prompt_abschnitt, wissens_hash
from kategorien import aktiv as kat_aktiv
from kategorien import als_dokument as kat_dokument
from kategorien import auswahl as kat_auswahl
from kategorien import schluessel_aus_name as kat_schluessel
from kategorien import sichtbar as kat_sichtbar
from kategorien import FELD_LABEL as KAT_FELD_LABEL
from kategorien import konten as kat_konten
from kategorien import ausnahmen_aus_tabelle, konto_ausnahmen, konto_text
import pandas as pd
import skr04
from kategorien import LERN_PROMPT, URSACHEN, lern_antwort_pruefen, lern_nachricht
import lesequalitaet
from prompts import prompt_version, system_prompt
from storage import (
    AblageFehler,
    ablage_beschreibung,
    ablage_link,
    ablage_pruefen,
    beleg_speichern,
    datei_hash,
    feedback_laden,
    beleg_laden,
    analyse_speichern,
    analysen_laden,
    entscheidungen_laden,
    anlage_ordner,
    beispielbeleg_hochladen,
    beispielbeleg_laden,
    beispielbelege,
    kategorie_dokument_ablegen,
    kategorie_speichern,
    kalender_abgleichen,
    kalender_anmelde_url,
    kalender_auswahl_speichern,
    kalender_liste,
    kalender_ruecksprung,
    kalender_status,
    kalender_trennen,
    kalender_verbinden_moeglich,
    kalender_verbindung,
    kategorien_laden,
    feedback_speichern,
    nachfragen_laden,
)

_ASSETS = Path(__file__).parent / "assets"
if not _ASSETS.exists():  # z. B. wenn App.py aus einem anderen Ordner ausgeführt wird
    _ASSETS = Path.cwd() / "assets"
st.set_page_config(page_title=f"{APP_NAME} – RE-ALIS", page_icon=str(_ASSETS / "realis-symbol.svg"),
                   layout="wide")
st.logo(str(_ASSETS / "realis-logo.svg"), icon_image=str(_ASSETS / "realis-symbol.svg"), size="large")

if ist_datenschutzseite():  # öffentlich, ohne Login (von Google für den OAuth-Produktionsmodus verlangt)
    zeige_datenschutz()
    st.stop()

login_erzwingen()

try:
    ablage_pruefen()  # Drive falsch konfiguriert -> sofort sperren statt Daten zu verlieren
except AblageFehler as e:
    st.error(f"Ablage nicht verfügbar: {e}")
    st.stop()
_link = ablage_link()
st.sidebar.caption(
    f"Ablage: [{ablage_beschreibung()} :material/open_in_new:]({_link})" if _link
    else f"Ablage: {ablage_beschreibung()}",
    help="Öffnet den Drive-Ordner mit Belegen, Nachfragen und Feedback in einem neuen Tab. "
         "Funktioniert nur für Personen, die auf den Ordner Zugriff haben." if _link else None,
)


# ---------------------------------------------------------------------------
# Kalender verbinden (Seitenleiste, unter dem Drive-Link) – siehe kalender_verbindung.py
# ---------------------------------------------------------------------------

def _kalender_ruecksprung_verarbeiten() -> None:
    """Google leitet nach „Kalender verbinden“ mit ?code=…&state=… auf die App zurück."""
    state = st.query_params.get("state")
    if not ist_kalender_state(state):
        return
    code, abgebrochen = st.query_params.get("code"), st.query_params.get("error")
    st.query_params.clear()  # Code nur einmal verwenden, Adresse wieder sauber
    if abgebrochen or not code:
        st.session_state["kalender_meldung"] = ("warnung", "Kalender verbinden wurde abgebrochen.")
        return
    try:
        with st.sidebar, st.spinner("Kalender wird verbunden …"):
            verbindung = kalender_ruecksprung(code, state, aktueller_benutzer(), aktueller_benutzer())
    except (VerbindungsFehler, AblageFehler) as e:
        st.session_state["kalender_meldung"] = ("fehler", str(e))
        return
    except Exception as e:
        st.session_state["kalender_meldung"] = ("fehler", f"Kalender verbinden fehlgeschlagen: {e}")
        return
    konto = (verbindung or {}).get("konto") or "Google-Konto"
    st.session_state["kalender_meldung"] = ("ok", f"Kalender verbunden über {konto}.")
    if verbindung and not verbindung["kalender"]:
        st.session_state["kalender_wahl_offen"] = True  # gleich auswählen lassen, welche Kalender gelten


def _kalender_wahl_schliessen() -> None:
    st.session_state.pop("kalender_wahl_offen", None)
    st.session_state.pop("kalender_liste", None)


@st.dialog("Welche Kalender sollen abgeglichen werden?", on_dismiss=_kalender_wahl_schliessen)
def _kalender_wahl_dialog() -> None:
    ss = st.session_state
    if "kalender_liste" not in ss:
        try:
            ss["kalender_liste"] = kalender_liste()
        except Exception as e:
            st.error(f"Kalender konnten nicht geladen werden: {e}")
            return
    liste = ss["kalender_liste"]
    if not liste:
        st.warning("Dieses Google-Konto sieht keine Kalender.")
        return
    namen = {k["id"]: k["name"] + (" (eigener Kalender)" if k["haupt"] else "") for k in liste}
    gewaehlt = {k["id"] for k in (kalender_verbindung() or {}).get("kalender", [])}
    st.caption("Zu jeder Bewirtung und Übernachtung sucht die App in **allen** gewählten Kalendern nach einem "
               "passenden Termin. Gibt es keinen, fragt sie nach.")
    wahl = st.multiselect("Kalender", list(namen), default=[i for i in namen if i in gewaehlt],
                          format_func=namen.get, key="kalender_wahl", placeholder="Kalender auswählen")
    if st.button("Speichern", type="primary", disabled=not wahl, key="kalender_wahl_speichern"):
        kalender_auswahl_speichern([{"id": i, "name": next(k["name"] for k in liste if k["id"] == i)}
                                    for i in wahl], aktueller_benutzer())
        _kalender_wahl_schliessen()
        ss["kalender_meldung"] = ("ok", f"{len(wahl)} Kalender werden jetzt abgeglichen.")
        st.rerun()


def _kalender_seitenleiste() -> None:
    ss = st.session_state
    verbindung = kalender_verbindung()
    moeglich = kalender_verbinden_moeglich()
    url = kalender_anmelde_url(aktueller_benutzer()) if moeglich else None
    hilfe = ("Zu Bewirtungen und Übernachtungen sucht die App einen passenden Termin im Google-Kalender. "
             "„Kalender verbinden“ öffnet Google in einem neuen Tab: mit dem Konto anmelden, das die Termine "
             "sieht, und „Kalender ansehen“ erlauben. Die App liest nur, sie ändert nichts.")
    if verbindung:
        kurz = ("neu verbinden" if not verbindung["token_ok"] else
                "verbunden" if verbindung["kalender"] else "bitte Kalender wählen")
        with st.sidebar.popover(f"Kalender: {kurz}", icon=":material/event:",
                                key="kalender_verbindung", width="stretch"):
            st.caption(f"Verbunden über **{verbindung['konto'] or 'Google-Konto'}**"
                       + (f", eingerichtet am {zeitpunkt_de(verbindung['zeitpunkt'])}" if verbindung.get("zeitpunkt")
                          else "") + ".")
            if verbindung["kalender"]:
                st.markdown("Abgeglichen werden:\n" + "\n".join(f"- {k['name']}" for k in verbindung["kalender"]))
            if verbindung["token_ok"] and st.button("Kalender auswählen", icon=":material/checklist:",
                                                    key="kalender_auswahl_oeffnen", width="stretch"):
                ss.pop("kalender_liste", None)
                ss["kalender_wahl_offen"] = True
            if url:
                st.link_button("Neu verbinden" if verbindung["token_ok"] else "Neu verbinden (nötig)", url,
                               icon=":material/sync:", key="kalender_neu_verbinden", width="stretch",
                               help="Öffnet Google in einem neuen Tab, z. B. für ein anderes Konto.")
            if st.button("Trennen", icon=":material/link_off:", key="kalender_trennen", width="stretch"):
                kalender_trennen(aktueller_benutzer())
                ss["kalender_meldung"] = ("ok", "Kalender getrennt.")
                st.rerun()
    else:
        st.sidebar.caption(f"Kalender: {kalender_status()}", help=hilfe)
        if url:
            st.sidebar.link_button("Kalender verbinden", url, icon=":material/event:", key="kalender_verbinden",
                                   help=hilfe)
    meldung = ss.pop("kalender_meldung", None)
    if meldung:
        art, text = meldung
        {"ok": st.sidebar.success, "warnung": st.sidebar.warning}.get(art, st.sidebar.error)(text)
    if ss.get("kalender_wahl_offen"):  # bleibt offen, bis gespeichert oder geschlossen (on_dismiss)
        _kalender_wahl_dialog()


_kalender_ruecksprung_verarbeiten()
try:
    _kalender_seitenleiste()
except Exception as e:  # Kalender darf die App nie blockieren
    st.sidebar.caption(f"Kalender: nicht verfügbar ({e})")
einfuehrung_knopf()
thema_einbetten()
thema_knopf()  # oben rechts neben dem Menü

# Kategorie-Wissen aus der App -> gültige Kategorien + Prompt (gilt für alle Benutzer gleich)
try:
    KAT_STAND = aktueller_stand(kategorien_laden())
except Exception as e:
    st.warning(f"Kategorien konnten nicht geladen werden, es gelten nur die Standard-Kategorien: {e}")
    KAT_STAND = aktueller_stand([])
kategorien_registrieren(labels(KAT_STAND))
konten_registrieren(kat_konten(KAT_STAND))
SYSTEM_PROMPT_AKTUELL = system_prompt(prompt_abschnitt(KAT_STAND))
PROMPT_VERSION = prompt_version(wissens_hash(KAT_STAND))


def _kategorie_label(key):
    """Anzeigename einer Belegart – auch für Entwürfe und inzwischen gelöschte Kategorien."""
    return (KAT_STAND.get(key) or {}).get("name") or KATEGORIEN.get(key, key)


def _konto_label(nummer: str | None, kategorie: str | None = None) -> str:
    """'6640' -> '6640 · Bewirtungskosten' (Bezeichnung aus der Kategorie, sonst aus der Vorlage)."""
    if not nummer:
        return "noch nicht festgelegt"
    k = KAT_STAND.get(kategorie) or {}
    namen = {k.get("skr04_konto"): k.get("skr04_bezeichnung")}
    namen.update({a["konto"]: a["bezeichnung"] for a in konto_ausnahmen(k)})
    return skr04.als_text(nummer, namen.get(nummer) or dict(reversed(skr04.VORLAGE)).get(nummer))


# ---------------------------------------------------------------------------
# Analyse ausführen und Ergebnis im Session-State halten
# ---------------------------------------------------------------------------

def _dateien(uploads) -> list[tuple[str, bytes, str]]:
    return [(u.name, u.getvalue(), u.type) for u in uploads]


def beleg_hash(dateien) -> str:
    """Eine Datei: Hash der Datei (wie bisher). Mehrere: Hash über die Einzel-Hashes in Upload-Reihenfolge."""
    if len(dateien) == 1:
        return datei_hash(dateien[0][1])
    return datei_hash("|".join(datei_hash(b) for _, b, _ in dateien).encode())


def _belege_speichern(dateien) -> list[str]:
    return [beleg_speichern(b, name, datei_hash(b)) for name, b, _ in dateien]


class DateiFehler(Exception):
    """Datei nicht lesbar (defektes PDF, unbekanntes Bildformat)."""


def _beleg_verarbeiten(dateien, status=None) -> dict:
    """Ein Beleg (eine oder mehrere Dateien) -> Ergebnis-Dict. Ohne Streamlit-Aufrufe, läuft auch parallel.
    Wirft DateiFehler bzw. AnalyseFehler/Exception bei Modellproblemen. Legt KEINE Nachfrage ab."""
    sha = beleg_hash(dateien)
    dateiname = ", ".join(name for name, _, _ in dateien)
    try:
        bilder, seiten_gesamt, seiten_gelesen = dateien_zu_bildern(dateien)
    except Exception as e:
        raise DateiFehler("Datei konnte nicht geöffnet werden – beschädigt oder kein gültiges PDF/Bild.") from e

    t0 = time.time()
    lese = beleg_lesen(bilder, dateien, status=status, system=SYSTEM_PROMPT_AKTUELL)
    gruende = list(lese.gruende)
    if status:
        status("Gleiche mit dem Firmenkalender ab …")
    kalender = kalender_abgleichen(lese.analyse)
    if kalender.nachfrage_grund:
        gruende.append(kalender.nachfrage_grund)
    if seiten_gelesen < seiten_gesamt:
        gruende.append(f"Nur {seiten_gelesen} von {seiten_gesamt} Seiten gelesen (Obergrenze {MAX_SEITEN}).")
    return {
        "sha": sha,
        "dateiname": dateiname,
        "dateien": dateien,
        "vorschau": bilder,
        "seiten_gesamt": seiten_gesamt,
        "seiten_gelesen": seiten_gelesen,
        "analyse": lese.analyse,
        "modell": lese.modell,
        "lesungen": lese.lesungen,
        "abweichungen": lese.abweichungen,
        "ungeklaert": lese.ungeklaert,
        "schiedsrichter": lese.schiedsrichter,
        "befunde": lese.befunde,
        "nachfrage_gruende": gruende,
        "raw": lese.raw,
        "usage": lese.usage,
        "dauer_s": round(time.time() - t0, 1),
        "prompt_version": PROMPT_VERSION,
        "kalender": kalender,
    }


def analyse_starten(uploads):
    """Alle hochgeladenen Dateien als EINEN Beleg analysieren."""
    with st.status("Analysiere Beleg …", expanded=False) as fortschritt:
        try:
            erg = _beleg_verarbeiten(_dateien(uploads), status=lambda text: fortschritt.update(label=text))
        except DateiFehler as e:
            st.session_state["fehler"] = (str(e), None)
        except AnalyseFehler as e:
            st.session_state["fehler"] = (str(e), e.raw)
        except Exception as e:
            st.session_state["fehler"] = (f"Fehler beim Modell-Aufruf: {e}", None)
        else:
            fortschritt.update(label="Analyse fertig", state="complete")
            st.session_state.pop("fehler", None)
            erg["ablage_status"] = _beleg_ablegen(erg)
            st.session_state["ergebnis"] = erg
            return
        fortschritt.update(label="Analyse fehlgeschlagen", state="error")


MAX_STAPEL = 30
STAPEL_PARALLEL = 3


def stapel_starten(uploads):
    """Jede Datei als EIGENEN Beleg analysieren, mehrere gleichzeitig."""
    belege = [[d] for d in _dateien(uploads)[:MAX_STAPEL]]
    ergebnisse: list[dict] = [None] * len(belege)
    balken = st.progress(0.0, text=f"Analysiere {len(belege)} Belege …")
    with ThreadPoolExecutor(max_workers=STAPEL_PARALLEL) as pool:
        futures = {pool.submit(_beleg_verarbeiten, b): i for i, b in enumerate(belege)}
        for fertig, f in enumerate(as_completed(futures), start=1):
            i = futures[f]
            try:
                ergebnisse[i] = f.result()
            except Exception as e:
                ergebnisse[i] = {"sha": beleg_hash(belege[i]), "dateiname": belege[i][0][0], "fehler": str(e)}
            balken.progress(fertig / len(belege), text=f"{fertig} von {len(belege)} Belegen fertig")
    # Ablage im Hauptthread (Drive-Zugriffe), nicht in den Arbeits-Threads
    for erg in ergebnisse:
        if "fehler" not in erg:
            erg["ablage_status"] = _beleg_ablegen(erg)
    balken.empty()
    st.session_state["stapel"] = ergebnisse


def _status_text(erg: dict) -> str:
    if "fehler" in erg:
        return "Fehler"
    return "Nachfrage" if erg["nachfrage_gruende"] else "stimmig"


def zeige_stapel(ergebnisse: list[dict]):
    n = len(ergebnisse)
    stimmig = sum(1 for e in ergebnisse if _status_text(e) == "stimmig")
    nachfrage = sum(1 for e in ergebnisse if _status_text(e) == "Nachfrage")
    fehler = n - stimmig - nachfrage
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Belege", n)
    m2.metric("Stimmig", stimmig)
    m3.metric("Zur Nachfrage", nachfrage)
    m4.metric("Fehler", fehler)
    st.info("**Prüfen und korrigieren im Tab „Belege“**" + (
        f" – {nachfrage} Beleg(e) mit Nachfrage stehen dort unter „Nachfragen offen“, alle anderen unter „Ungeprüft“."
        if nachfrage else " – die Belege stehen dort unter „Ungeprüft“."), icon=":material/arrow_forward:")
    fehlgeschlagen = [e["dateiname"] for e in ergebnisse if (e.get("ablage_status") or "").startswith("Ablegen")]
    if fehlgeschlagen:
        st.warning("Nicht abgelegt (bitte erneut hochladen): " + ", ".join(fehlgeschlagen))

    zeilen = []
    for e in ergebnisse:
        a = e.get("analyse")
        zeilen.append({
            "Datei": e["dateiname"],
            "Status": _status_text(e),
            "Belegart": _kategorie_label(a.kategorie) if a else "–",
            "Aussteller": (a.restaurant_name or "–") if a else "–",
            "Datum": anzeige(a.datum) or "–" if a else "–",
            "Gesamtbetrag": _wert(a.brutto) if a else "–",
            "Grund": " | ".join(e.get("nachfrage_gruende") or []) or e.get("fehler") or "",
        })
    _farbtabelle(zeilen, ["Status"], ganze_zeile=True)

    puffer = io.StringIO()
    schreiber = csv.DictWriter(puffer, fieldnames=list(zeilen[0]), delimiter=";")
    schreiber.writeheader()
    schreiber.writerows(zeilen)
    st.download_button("Tabelle als CSV herunterladen", puffer.getvalue().encode("utf-8-sig"),
                       file_name="beleg-stapel.csv", mime="text/csv", icon=":material/download:")

    analysierbar = [e for e in ergebnisse if "fehler" not in e]
    if not analysierbar:
        return
    st.divider()
    gewaehlt = st.selectbox(
        "Analyse eines Belegs im Detail ansehen",
        analysierbar,
        format_func=lambda e: f"{e['dateiname']} – {_status_text(e)}",
        key="stapel_detail",
    )
    zeige_ergebnis(gewaehlt)


def _lesungen_protokoll(erg) -> list[dict]:
    """Alle Lesungen (Modell, Variante, Rohantwort) – für spätere Auswertung, wer wie oft richtig lag."""
    return [{"modell": l.modell, "variante": l.variante, "rohantwort": l.raw, "fehler": l.fehler,
             "analyse": l.analyse.model_dump() if l.analyse else None} for l in erg["lesungen"]]


def _beleg_ablegen(erg) -> str:
    """Jeden analysierten Beleg ablegen (Original + Ergebnis) – damit er im Tab „Belege“ geprüft werden kann."""
    analyse = erg["analyse"]
    try:
        pfade = _belege_speichern(erg["dateien"])
        analyse_speichern({
            "datei_sha256": erg["sha"],
            "dateiname": erg["dateiname"],
            "beleg_pfad": pfade[0],
            "beleg_pfade": pfade,
            "seiten": erg["seiten_gesamt"],
            "kategorie": analyse.kategorie,
            "gruende": erg["nachfrage_gruende"],  # leer = keine Nachfrage
            "analyse": analyse.model_dump(),
            "rohantwort": erg["raw"],
            "lesungen": _lesungen_protokoll(erg),
            "schiedsrichter": erg.get("schiedsrichter", False),
            "kalender": erg["kalender"].als_dict() if erg.get("kalender") else None,
            "modell": erg["modell"],
            "prompt_version": erg["prompt_version"],
            "dauer_s": erg["dauer_s"],
            "benutzer_email": aktueller_benutzer(),
        })
    except Exception as e:
        return f"Ablegen fehlgeschlagen: {e}"
    return "abgelegt"


# ---------------------------------------------------------------------------
# Anzeige
# ---------------------------------------------------------------------------

def _wert(v) -> str:
    """Tabellenwert: Beträge mit €, leere Werte als Gedankenstrich (wird vorgelesen als 'Strich')."""
    if isinstance(v, float):
        return f"{anzeige(v)} €"
    if isinstance(v, list):  # Steuersätze
        return ", ".join(f"{anzeige([s])} %" for s in v) or "–"
    return anzeige(v) or "–"


# Status-Farben (Hintergrund, Schrift) als CSS-Variablen (Werte für hell/dunkel im <style> unten) – Kontrast > 8:1.
# Der Status steht immer zusätzlich als Wort in der Zelle (nicht nur Farbe).
_STATUS_FARBE = {s: (f"var(--status-{s}-hg)", f"var(--status-{s}-text)") for s in ("ok", "nachfrage", "fehler")}


def _status_von(text) -> str | None:
    t = str(text).casefold()
    if "fehler" in t:
        return "fehler"
    if "nachfrage" in t or "korrigiert" in t:
        return "nachfrage"
    if t.endswith("ok") or "stimmig" in t:
        return "ok"
    return None


def _farbtabelle(zeilen: list[dict], status_spalten: list[str], ganze_zeile: bool = False) -> None:
    """Tabelle mit grün (ok) / rot (Nachfrage) / grau (Fehler) hinterlegten Zellen bzw. Zeilen."""
    import pandas as pd

    def css(status):
        if not status:
            return ""
        hg, schrift = _STATUS_FARBE[status]
        return f"background-color: {hg}; color: {schrift}"

    df = pd.DataFrame(zeilen)
    if ganze_zeile:
        stil = df.style.apply(lambda zeile: [css(_status_von(zeile[status_spalten[0]]))] * len(zeile), axis=1)
    else:
        stil = df.style.map(lambda wert: css(_status_von(wert)), subset=status_spalten)
    st.table(stil.hide(axis="index"))


def _tabelle(zeilen: list[dict]) -> None:
    # st.table statt st.dataframe: echte HTML-Tabelle, für Screenreader lesbar, nichts wird abgeschnitten
    st.table(zeilen)


def _pruefzeile(name: str, ok: bool) -> str:
    # Ergebnis immer als Wort, nicht nur als Symbol/Farbe
    return f"- {':material/check_circle:' if ok else ':material/cancel:'} {name}: **{'ja' if ok else 'nein'}**"


def _lauf_knopf(label: str, name: str, *, ort=None, scope: str = "app", **knopf_args) -> bool:
    """Knopf für längere Vorgänge (KI-Aufruf, Analyse, Probelauf).

    Klick -> neuer Durchlauf, in dem derselbe Knopf ausgegraut nur einen Spinner zeigt und die anderen Tabs
    gesperrt sind (CSS über key „laufknopf_…“) – so ist sichtbar, dass es läuft, und ein zweiter Klick oder
    ein Klick woanders kann den Vorgang nicht abbrechen. Gibt True zurück, wenn der Vorgang JETZT laufen soll;
    der Aufrufer ruft danach st.rerun(scope=scope) auf (dann ist der Knopf wieder normal).
    ort: Spalte/Container (Standard: st); scope="fragment" innerhalb von st.dialog."""
    ort = ort or st
    merker = f"laeuft_{name}"
    if st.session_state.pop(merker, False):
        knopf_args.pop("icon", None)
        knopf_args.pop("disabled", None)
        ort.button(label, key=f"laufknopf_{name}", disabled=True, icon=":material/progress_activity:", **knopf_args)
        return True
    if ort.button(label, key=f"laufknopf_{name}", **knopf_args):
        st.session_state[merker] = True
        st.rerun(scope=scope)
    return False


def _lauf_meldung(name: str) -> None:
    """Fehler/Hinweis aus dem letzten Lauf anzeigen (wird vor dem Neuzeichnen in session_state abgelegt)."""
    meldung = st.session_state.pop(f"meldung_{name}", None)
    if meldung:
        st.error(meldung)


def _beleg_vorschau(bilder: list[bytes], titel: str, key: str) -> None:
    """Belegansicht: die aktuelle Seite groß (in der Belegspalte so hoch wie das Formular daneben), bei mehreren
    Seiten darunter „‹ Seite x von n ›“ und eine Leiste mit Mini-Vorschauen.

    Gezeichnet werden alle Seiten; sichtbar ist nur die gewählte. Das Blättern übernimmt assets/belegansicht.js
    im Browser – sofort, ohne Neuberechnung durch Streamlit. titel: Dateiname (derzeit nur informativ)."""
    if not bilder:
        return
    n = len(bilder)
    with st.container(key=f"belegbild_{key}"):
        for bild in bilder:
            st.image(bild)
    if n > 1:
        st.html(
            f'<div class="belegnav" data-key="{html.escape(key)}" role="group" aria-label="Seiten blättern">'
            '<button type="button" data-schritt="-1" aria-label="Vorherige Seite" disabled>‹</button>'
            f'<span aria-live="polite">Seite 1 von {n}</span>'
            '<button type="button" data-schritt="1" aria-label="Nächste Seite">›</button></div>'
        )
        with st.container(key=f"belegdaumen_{key}", horizontal=True, horizontal_alignment="center", gap="small"):
            for bild in bilder:
                st.image(bild, width=64)


def _zeige_kalender(k: dict) -> None:
    """Ergebnis des Kalenderabgleichs (auch für gespeicherte Nachfragen, daher als dict)."""
    if not k or k["status"] == "nicht_noetig":
        return
    if k["status"] == "nicht_eingerichtet":
        st.caption(":material/event: Kalenderabgleich ist noch nicht eingerichtet.")
        return
    t = k.get("termin")
    if k["status"] == "passend" and t:
        zeilen = [f"**Kalendertermin:** {t['titel']} · {t['zeitraum']}" + (f" · {t['ort']}" if t["ort"] else ""),
                  k["grund"]]
        if t["teilnehmer"]:
            zeilen.append("**Teilnehmer laut Kalender** (Vorschlag für „bewirtete Personen“): "
                          + ", ".join(t["teilnehmer"]))
        if t.get("link"):
            zeilen.append(f"[Termin im Kalender öffnen]({t['link']})")
        st.info("\n\n".join(zeilen), icon=":material/event_available:")
        return
    st.warning(f"**Kein passender Kalendertermin:** {k['grund']}", icon=":material/event_busy:")
    if k.get("kandidaten"):
        with st.expander(f"Termine im Zeitraum ({len(k['kandidaten'])}) – vielleicht ist einer davon gemeint"):
            for kand in k["kandidaten"]:
                st.markdown(f"- {kand['titel']} · {kand['zeitraum']}" + (f" · {kand['ort']}" if kand["ort"] else "")
                            + (f" · Teilnehmer: {', '.join(kand['teilnehmer'])}" if kand["teilnehmer"] else ""))


def zeige_ergebnis(erg):
    analyse = erg["analyse"]
    gruende = erg.get("nachfrage_gruende") or []
    status = erg.get("ablage_status") or ""

    # 1. Gesamtergebnis zuerst – das Wichtigste oben
    if gruende:
        st.error("**Nachfrage nötig.** Die KI ist sich nicht sicher:\n\n" + "\n".join(f"- {g}" for g in gruende),
                 icon=":material/help:")
    else:
        st.success("**Alles stimmig.** Alle Prüfungen bestanden, keine Nachfrage nötig.",
                   icon=":material/check_circle:")
    if status.startswith("Ablegen fehlgeschlagen"):
        st.warning(f"{status} – der Beleg erscheint deshalb nicht im Tab „Belege“.")

    col_bild, col_daten = st.columns([2, 3], gap="large")

    # 2. Beleg
    with col_bild:
        st.subheader("Beleg")
        gesamt, gelesen = erg["seiten_gesamt"], erg["seiten_gelesen"]
        if gelesen < gesamt:
            st.warning(f"{gesamt} Seiten – nur die ersten {gelesen} wurden gelesen (Obergrenze {MAX_SEITEN}).")
        else:
            st.caption(f"{gesamt} Seite(n) aus {len(erg['dateien'])} Datei(en): {erg['dateiname']}")
        _beleg_vorschau(erg["vorschau"], erg["dateiname"], f"analyse_{erg['sha']}")

    # 3. Ergebnis
    with col_daten:
        st.subheader("Ergebnis")
        st.markdown(f"**Belegart:** {_kategorie_label(analyse.kategorie)}")
        if analyse.kategorie_unsicher:
            st.markdown(f"**Unsicher, weil:** {analyse.kategorie_grund or 'keine Begründung'}")
        st.markdown(f"**Konto (SKR04):** {_konto_label(analyse.konto, analyse.kategorie)}")
        if analyse.konto_unsicher:
            st.markdown(f"**Konto unsicher, weil:** {analyse.konto_grund or 'keine Begründung'}")

        st.markdown("**Prüfungen**")
        st.markdown("\n".join([
            _pruefzeile("Lesbar", analyse.lesbar),
            _pruefzeile("Steuersatz ausgewiesen", analyse.steuersatz_erkennbar or bool(analyse.steuerzeilen)),
            _pruefzeile("Datum erkennbar", analyse.datum_erkennbar or bool(analyse.datum)),
            _pruefzeile("Rechnung geht rechnerisch auf", not erg.get("befunde")),
            _pruefzeile("Zweimal gleich gelesen", not erg.get("abweichungen")),
        ] + ([_pruefzeile("EC-Beleg passt zur Rechnung", analyse.ec_passt_zur_rechnung)]
             if analyse.ec_passt_zur_rechnung is not None else [])
          + ([_pruefzeile("Passender Kalendertermin", erg["kalender"].status == "passend")]
             if erg.get("kalender") and erg["kalender"].status in ("passend", "kein_termin", "fehler") else [])))
        if erg.get("kalender"):
            _zeige_kalender(erg["kalender"].als_dict())
        if erg.get("schiedsrichter"):
            geklaert = len(erg.get("abweichungen", {})) - len(erg.get("ungeklaert", []))
            st.caption(
                f"Wegen Zweifeln hat zusätzlich das große Modell (`{erg['modell']}`) in höherer Auflösung "
                f"gelesen; dessen Ergebnis wird angezeigt. Abweichungen geklärt: {geklaert} von "
                f"{len(erg.get('abweichungen', {}))}."
            )

        if analyse.korrekturen:
            st.info("**Vom Code umgedeutet** (rechnerisch eindeutig, Summe geht danach exakt auf)\n\n"
                    + "\n".join(f"- {k}" for k in analyse.korrekturen), icon=":material/calculate:")

        if analyse.hinweise:
            st.info("**Hinweise der KI**\n\n" + "\n".join(f"- {h}" for h in analyse.hinweise),
                    icon=":material/info:")

        st.subheader("Daten für den Bewirtungsbeleg" if analyse.ist_bewirtung else "Belegdaten")
        _tabelle([{"Feld": k, "Wert": _wert(v)} for k, v in analyse.bewirtungsdaten().items()])

        if analyse.steuerzeilen:
            st.markdown("**MwSt.-Aufstellung** (wie auf dem Beleg abgelesen)")
            _tabelle([{
                "Steuersatz": f"{anzeige(z.satz)} %" if z.satz is not None else "–",
                "Netto": _wert(z.netto), "MwSt.": _wert(z.mwst), "Brutto": _wert(z.brutto),
            } for z in analyse.steuerzeilen])

        with st.expander("Technische Details"):
            dauer = f"{erg['dauer_s']:.1f}".replace(".", ",")
            st.caption(f"Ergebnis von `{erg['modell']}` · Prompt-Version `{erg['prompt_version']}` · Dauer {dauer} s")
            if erg.get("abweichungen"):
                _tabelle([{"Feld": f, "Lesung 1": x or "–", "Lesung 2": y or "–"}
                          for f, (x, y) in erg["abweichungen"].items()])
            for nr, l in enumerate(erg["lesungen"], start=1):
                st.markdown(f"**Lesung {nr}:** `{l.modell}`, Bild {l.variante}")
                st.code(l.raw or l.fehler or "", language="json")
            st.json(erg["usage"])

    if not (erg.get("ablage_status") or "").startswith("Ablegen fehlgeschlagen"):
        st.info("**Prüfen und korrigieren im Tab „Belege“** – der Beleg steht dort unter "
                + ("„Nachfragen offen“." if gruende else "„Ungeprüft“."), icon=":material/arrow_forward:")


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def _felder_eingabe(analyse, praefix: str) -> dict[str, str]:
    """Eingabefelder für alle FEEDBACK_FELDER, vorbelegt mit dem KI-Ergebnis (nur innerhalb von st.form)."""
    korrekturen = {}
    # Zeilenweise (je 2 Felder), damit die Tab-Reihenfolge der Lesereihenfolge entspricht
    for i in range(0, len(FEEDBACK_FELDER), 2):
        for spalte, (key, label, _typ) in zip(st.columns(2), FEEDBACK_FELDER[i:i + 2]):
            korrekturen[key] = spalte.text_input(
                label, value=anzeige(getattr(analyse, key)), key=f"{praefix}_{key}"
            )
    return korrekturen


def _felder_auswerten(analyse, korrekturen: dict[str, str]):
    """-> (felder, ungueltig). felder[key] = {modell, korrekt, richtig}; ungueltig = Labels nicht lesbarer Eingaben."""
    ungueltig, felder = [], {}
    for key, label, typ in FEEDBACK_FELDER:
        modell_wert = getattr(analyse, key)
        eingabe = korrekturen[key]
        korrekt = normalisieren(typ, eingabe)
        # Eingabe nicht leer, aber nicht lesbar -> Fehler statt stillem Datenverlust
        if eingabe.strip() and typ in ("betrag", "datum", "konto") and korrekt is None:
            ungueltig.append(label)
        felder[key] = {
            "modell": modell_wert,
            "korrekt": korrekt,
            "richtig": werte_gleich(typ, modell_wert, eingabe),
        }
    return felder, ungueltig


def _belegart_frage(ki_kat: str, key: str, richtig: bool | None = None, korrekt: str | None = None) -> str | None:
    """Ausdrückliche Frage „Stimmt die Belegart?“ – nichts ist vorausgewählt, damit niemand die KI-Antwort
    versehentlich bestätigt. -> richtige Belegart oder None (noch nicht beantwortet). Außerhalb von st.form."""
    namen = kat_auswahl(KAT_STAND)  # auch Entwürfe: neu angelegte Kategorien sofort wählbar
    antwort = st.radio(
        f"Stimmt die Belegart „{_kategorie_label(ki_kat)}“?",
        ["ja", "nein"],
        format_func={"ja": "Ja, stimmt", "nein": "Nein, es ist eine andere Belegart"}.get,
        index=None if richtig is None else (0 if richtig else 1),
        horizontal=True,
        key=f"{key}_kat_ok",
    )
    if antwort == "ja":
        return ki_kat
    if antwort == "nein":
        andere = [k for k in namen if k != ki_kat]
        return st.selectbox("Richtige Belegart", andere, format_func=namen.get, key=f"{key}_kat_wahl",
                            index=andere.index(korrekt) if korrekt in andere else None,
                            placeholder="Bitte wählen …")
    return None


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------

def _juengste_bewertungen(eintraege: list[dict]) -> list[dict]:
    """Pro Beleg (Datei-Hash) nur die jüngste Bewertung – sonst zählt ein mehrfach bewerteter Beleg doppelt."""
    juengste = {}
    for e in sorted(eintraege, key=lambda e: e.get("zeitpunkt") or ""):
        juengste[e.get("datei_sha256") or id(e)] = e
    return list(juengste.values())


def _feld_fehler(e: dict) -> list[str]:
    return [key for key, f in (e.get("felder") or {}).items() if not f.get("richtig")]


def _fehlerfrei(e: dict) -> bool:
    return e["kategorie"]["richtig"] and not _feld_fehler(e)


def zeige_auswertung():
    st.caption(
        "Wie gut erkennt die KI eure Belege? Gezählt werden alle Belege, die ein Mensch im Tab „Belege“ geprüft "
        "hat. Jeder Beleg zählt einmal (mit seiner jüngsten Prüfung). Einzelne Belege ansehen und korrigieren: "
        "Tab „Belege“."
    )
    try:
        alle = feedback_laden()
        belege = _alle_belege()
    except Exception as e:
        st.error(f"Daten konnten nicht geladen werden: {e}")
        return
    if belege:
        st.markdown("**Belege und Nachfragen**")
        nf = [b for b in belege if b["gruende"]]
        nf_geprueft = [b for b in nf if b.get("bewertung")]
        unnoetig = sum(1 for b in nf_geprueft if _fehlerfrei(b["bewertung"]))
        geprueft = sum(1 for b in belege if b.get("bewertung"))
        offen = sum(1 for b in nf if b["status"] == "offen")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Belege", len(belege), help="Alle analysierten Belege (je Beleg einmal).")
        c2.metric("Geprüft", f"{geprueft} von {len(belege)}", f"{geprueft / len(belege):.0%}", delta_color="off",
                  delta_arrow="off", help="Von einem Menschen im Tab „Belege“ geprüft.")
        c3.metric("Nachfragen der KI", len(nf), f"{offen} offen" if offen else "alle erledigt", delta_color="off",
                  delta_arrow="off", help="Belege, bei denen die KI unsicher war oder eine Prüfung nicht aufging.")
        c4.metric("Unnötige Nachfragen", f"{unnoetig} von {len(nf_geprueft)}" if nf_geprueft else "–",
                  help="Die KI hat nachgefragt, bei der Prüfung war aber alles richtig. Viele unnötige Nachfragen "
                       "= Regeln zu streng.")
        st.divider()
    if not alle:
        st.info("Noch keine geprüften Belege. Prüfen geht im Tab „Belege“.")
        return
    st.markdown("**Erkennungsqualität**")

    with st.expander("Filter: Prompt-Version und Modell"):
        versionen = sorted({e.get("prompt_version") or "?" for e in alle}, reverse=True)
        modelle = sorted({e.get("modell") or "?" for e in alle})
        f1, f2 = st.columns(2)
        v_auswahl = f1.multiselect("Prompt-Version", versionen, default=versionen,
                                   help="Jede Änderung an Anweisungen oder Kategorien erzeugt eine neue Version.")
        m_auswahl = f2.multiselect("Modell", modelle, default=modelle)
    eintraege = _juengste_bewertungen([
        e for e in alle
        if (e.get("prompt_version") or "?") in v_auswahl and (e.get("modell") or "?") in m_auswahl
    ])
    if not eintraege:
        st.warning("Keine Einträge für diese Auswahl.")
        return

    n = len(eintraege)
    kat_richtig = sum(1 for e in eintraege if e["kategorie"]["richtig"])
    felder_richtig = sum(1 for e in eintraege if not _feld_fehler(e))
    komplett = sum(1 for e in eintraege if _fehlerfrei(e))
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Geprüfte Belege", n)
    m2.metric("Belegart richtig", f"{kat_richtig} von {n}", f"{kat_richtig / n:.0%}", delta_color="off", delta_arrow="off",
              help="Die KI hat die Belegart (Kategorie) gewählt, die auch der Mensch als richtig bestätigt hat.")
    m3.metric("Alle Felder richtig", f"{felder_richtig} von {n}", f"{felder_richtig / n:.0%}", delta_color="off", delta_arrow="off",
              help="Kein einziges Feld (Belegnummer, Datum, Beträge, …) musste korrigiert werden. "
                   "Ein Feld gilt als richtig, wenn es beim Bewerten nicht geändert wurde.")
    m4.metric("Komplett richtig", f"{komplett} von {n}", f"{komplett / n:.0%}", delta_color="off", delta_arrow="off",
              help="Belegart richtig UND alle Felder richtig.")

    # Falsche Belegart, weil die richtige Kategorie neu ist? Dann konnte die KI sie evtl. noch nicht kennen.
    neue_kat = [e for e in eintraege
                if not e["kategorie"]["richtig"] and e["kategorie"]["korrekt"] not in STANDARD_KATEGORIEN]
    if neue_kat:
        namen = sorted({_kategorie_label(e["kategorie"]["korrekt"]) for e in neue_kat})
        st.info(
            f"{len(neue_kat)} der {n - kat_richtig} falschen Belegarten betreffen eigene, neu angelegte Kategorien "
            f"({', '.join(f'„{x}“' for x in namen)}). Wurden die Belege analysiert, bevor die Kategorie aktiv war, "
            "konnte die KI sie noch nicht kennen – dann ist das kein echter Fehler. Am besten diese Belege nach dem "
            "Aktivieren noch einmal analysieren.",
            icon=":material/info:",
        )

    links, rechts = st.columns(2, gap="large")
    with links:
        st.markdown("**Trefferquote pro Feld**")
        zeilen = []
        for key, label, _typ in FEEDBACK_FELDER:
            werte = [e["felder"][key]["richtig"] for e in eintraege if key in (e.get("felder") or {})]
            if werte:
                zeilen.append({"Feld": label, "Trefferquote": sum(werte) / len(werte),
                               "Richtig": f"{sum(werte)} von {len(werte)}"})
        st.dataframe(zeilen, hide_index=True, width="stretch", column_config={
            "Trefferquote": st.column_config.ProgressColumn(format="percent", min_value=0, max_value=1)})
    with rechts:
        st.markdown("**Trefferquote pro Belegart** (laut Bewertung)")
        pro_art = {}
        for e in eintraege:
            z = pro_art.setdefault(e["kategorie"]["korrekt"], [0, 0])
            z[0] += e["kategorie"]["richtig"]
            z[1] += 1
        st.dataframe([{"Belegart": _kategorie_label(k), "Trefferquote": r / g, "Richtig": f"{r} von {g}"}
                      for k, (r, g) in sorted(pro_art.items(), key=lambda x: -x[1][1])],
                     hide_index=True, width="stretch", column_config={
                         "Belegart": st.column_config.TextColumn(width="medium"),
                         "Trefferquote": st.column_config.ProgressColumn(format="percent", min_value=0,
                                                                         max_value=1, width="small"),
                         "Richtig": st.column_config.TextColumn(width="small")})
        verwechslungen = [e for e in eintraege if not e["kategorie"]["richtig"]]
        if verwechslungen:
            st.caption("Verwechslungen: " + "; ".join(
                f"„{_kategorie_label(e['kategorie']['modell'])}“ statt „{_kategorie_label(e['kategorie']['korrekt'])}“"
                for e in verwechslungen))

    st.divider()
    _zeige_lesequalitaet(eintraege)
    st.divider()
    _aus_korrekturen_lernen(eintraege)


# ---------------------------------------------------------------------------
# Lesequalität: welche Lesung lag richtig? (lesequalitaet.py)
# ---------------------------------------------------------------------------

_LQ_SPALTEN = {**lesequalitaet.VARIANTEN, "ergebnis": "Endergebnis"}


def _lq_zelle(zaehler) -> str:
    q = lesequalitaet.quote(zaehler)
    return "–" if q is None else f"{q:.0%} ({zaehler[0]}/{zaehler[1]})".replace("%", " %")


def _lq_hinweise(erg: dict) -> list[str]:
    """Erste Schlussfolgerungen – nur, wenn genug Belege da sind."""
    if erg["belege"] < 10:
        return []
    hinweise = []
    gruppen = {name: lesequalitaet.quote(z.get("ergebnis")) for name, z in erg["gruppen"].items()}
    gruppen = {n: q for n, q in gruppen.items() if q is not None}
    if gruppen:
        schwach, q = min(gruppen.items(), key=lambda x: x[1])
        if q < 0.95:
            hinweise.append(f"Schwachstelle sind die **{schwach}** ({q:.0%} richtig im Endergebnis)."
                            .replace("%", " %"))
    sr = erg["schiedsrichter"]
    if sr["eingesetzt"] >= 5 and not sr["gerettet"]:
        hinweise.append("Der Schiedsrichter hat bisher kein Feld gerettet – lohnt sich sein Aufruf?")
    if sr["verschlechtert"]:
        hinweise.append(f"In {sr['verschlechtert']} Feld(ern) lag eine der ersten Lesungen richtig, das Endergebnis "
                        "aber falsch – dort hat der Schiedsrichter verschlechtert.")
    if erg["belege"] >= 20 and not erg["nur_kontrast"]:
        hinweise.append("Die Kontrast-Lesung war bisher nie als einzige richtig – sie dient nur noch als Gegenprobe.")
    return hinweise


def _zeige_lesequalitaet(eintraege: list[dict]) -> None:
    import pandas as pd

    st.markdown("**Lesequalität**")
    st.caption(
        "Welche Lesung lag bei den geprüften Belegen richtig? Jeder Beleg wird zweimal gelesen (Original und "
        "Kontrast-Variante), bei Zweifel liest der Schiedsrichter in hoher Auflösung. So seht ihr, wo falsch "
        "gelesen wird und ob die zusätzlichen Lesungen etwas bringen. Endergebnis = das, was die App ausgegeben hat."
    )
    try:
        belege = {b["sha"]: b for b in _alle_belege()}
    except Exception as ex:
        st.error(f"Lesungen konnten nicht geladen werden: {ex}")
        return
    faelle = []
    for e in eintraege:
        b = belege.get(e.get("datei_sha256")) or {}
        a = b.get("analyse_eintrag") or {}
        faelle.append({"bewertung": e, "lesungen": a.get("lesungen") or e.get("lesungen"),
                       "dateiname": e.get("dateiname") or a.get("dateiname"),
                       "seiten": a.get("seiten") or e.get("seiten")})
    erg = lesequalitaet.auswerten(faelle)
    if not erg["belege"]:
        st.info("Noch keine geprüften Belege mit gespeicherten Lesungen.")
        return

    sr = erg["schiedsrichter"]
    badges = [
        ("gray", f"Belege mit Lesungen · {erg['belege']}"),
        ("blue", f"Schiedsrichter eingesetzt · {sr['eingesetzt']}"),
        ("green", f"Schiedsrichter rettete · {sr['gerettet']} Feld(er)"),
        ("red" if sr["verschlechtert"] else "gray", f"Schiedsrichter verschlechterte · {sr['verschlechtert']}"),
        ("gray", f"Nur Original richtig · {erg['nur_original']}"),
        ("gray", f"Nur Kontrast richtig · {erg['nur_kontrast']}"),
    ]
    st.markdown("  ".join(f":{farbe}-badge[{text}]" for farbe, text in badges),
                help="„rettete“: beide ersten Lesungen falsch, Schiedsrichter richtig. „verschlechterte“: eine der "
                     "ersten Lesungen war richtig, das Endergebnis trotzdem falsch. „Nur … richtig“: Felder, in "
                     "denen genau eine der beiden ersten Lesungen stimmte.")
    if erg["belege"] < 20:
        st.caption(f":material/info: Erst {erg['belege']} Belege – die Zahlen sind noch vorläufig, aussagekräftig "
                   "wird es ab einigen Dutzend.")

    labels = {key: label for key, label, _t in FEEDBACK_FELDER}
    zeilen, quoten = [], []
    for name, zaehler in ([("Belegart", erg["belegart"])]
                          + [(f"Σ {g}", z) for g, z in erg["gruppen"].items() if z]
                          + [(labels[k], z) for k, z in erg["felder"].items() if z]):
        zeilen.append({"Feld": name, **{titel: _lq_zelle(zaehler.get(v)) for v, titel in _LQ_SPALTEN.items()}})
        quoten.append([None] + [lesequalitaet.quote(zaehler.get(v)) for v in _LQ_SPALTEN])
    df = pd.DataFrame(zeilen)

    def faerben(_df):  # unter 100 % hervorheben, unter 90 % deutlicher
        farben = []
        for q_zeile in quoten:
            farben.append(["" if q is None or q >= 0.995 else
                           ("background-color: var(--lq-stark); color: var(--lq-text)" if q < 0.9 else
                            "background-color: var(--lq-leicht); color: var(--lq-text)") for q in q_zeile])
        return pd.DataFrame(farben, index=_df.index, columns=_df.columns)

    stil = df.style.apply(faerben, axis=None).apply(
        lambda zeile: ["font-weight: 600" if str(zeile["Feld"]).startswith(("Σ", "Belegart")) else ""] * len(zeile),
        axis=1)
    st.table(stil.hide(axis="index"))

    if erg["je_typ"]:
        st.caption("Endergebnis je Belegtyp: " + " · ".join(
            f"{typ} {_lq_zelle(z)}" for typ, z in sorted(erg["je_typ"].items())))
    for hinweis in _lq_hinweise(erg):
        st.info(hinweis, icon=":material/lightbulb:")


# ---------------------------------------------------------------------------
# Aus Korrekturen lernen: Vorschläge für das Kategorie-Wissen
# ---------------------------------------------------------------------------

_MAX_LERNFAELLE = 60


def _lernfaelle(eintraege: list[dict]) -> tuple[list[dict], list[dict]]:
    """Bewertungen, aus denen sich etwas lernen lässt: korrigiert, kommentiert oder nachgefragt.
    -> (nummerierte Fälle fürs Modell, zugehörige Einträge)."""
    # Nachfragegründe: aus der Prüfung selbst oder – bei älteren Prüfungen ohne dieses Feld – aus der Analyse
    try:
        gruende_je_beleg = {b["sha"]: b["gruende"] for b in _alle_belege()}
    except Exception:
        gruende_je_beleg = {}

    def gruende(e):
        return e.get("nachfrage_gruende") or gruende_je_beleg.get(e.get("datei_sha256")) or []

    quellen = [e for e in eintraege
               if not _fehlerfrei(e) or (e.get("kommentar") or "").strip() or gruende(e)]
    quellen = sorted(quellen, key=lambda e: e.get("zeitpunkt") or "", reverse=True)[:_MAX_LERNFAELLE]
    faelle = []
    for nr, e in enumerate(quellen, start=1):
        k, felder = e["kategorie"], e.get("felder") or {}
        faelle.append({
            "nr": nr,
            "belegart_ki": f'{k["modell"]} ({_kategorie_label(k["modell"])})',
            "belegart_richtig": f'{k["korrekt"]} ({_kategorie_label(k["korrekt"])})',
            "belegart_vom_menschen_bestaetigt": bool(k["richtig"]),
            "beleg_laut_ki": {  # Eckdaten, damit das Modell nicht raten muss, worum es ging
                "aussteller": (e.get("analyse") or {}).get("restaurant_name"),
                "ausland": (e.get("analyse") or {}).get("ausland"),
                "begruendung_der_belegart": (e.get("analyse") or {}).get("kategorie_grund"),
                "hinweise": ((e.get("analyse") or {}).get("hinweise") or [])[:5],
            },
            "geaenderte_felder": [{"feld": label, "ki": anzeige(felder[key]["modell"]) or "–",
                                   "richtig": anzeige(felder[key]["korrekt"]) or "–"}
                                  for key, label, _t in FEEDBACK_FELDER
                                  if key in felder and not felder[key]["richtig"]],
            "nachfragegruende_ki": gruende(e),
            "kommentar_mensch": (e.get("kommentar") or "").strip(),
            "quelle": _QUELLE.get(e.get("quelle"), _QUELLE_ALT),
        })
    return faelle, quellen


def _aus_korrekturen_lernen(eintraege: list[dict]) -> None:
    st.subheader("Aus Korrekturen lernen")
    st.caption(
        "Ein großes KI-Modell liest alle Korrekturen, die Nachfragegründe der KI und eure Kommentare, sucht "
        "Muster und schlägt Ergänzungen für die Kategorie-Beschreibungen vor. Automatisch übernommen wird "
        "nichts: Ein Vorschlag landet als ungespeicherte Änderung im Tab „Kategorien“ – dort prüfen, mit "
        "„Testen“ ausprobieren und erst dann speichern."
    )
    faelle, quellen = _lernfaelle(eintraege)
    if not faelle:
        st.info("Noch keine Korrekturen, Kommentare oder Nachfragen – es gibt noch nichts zu lernen.")
        return
    if len(faelle) < 20:
        st.caption(f":material/info: Erst {len(faelle)} Fälle. Mit wenigen Fällen sind Vorschläge oft "
                   "Einzelfälle – richtig aussagekräftig wird es ab etwa 20–30 Korrekturen.")
    _lauf_meldung("lernen")
    if _lauf_knopf(f"Verbesserungsvorschläge erstellen ({len(faelle)} {'Fall' if len(faelle) == 1 else 'Fälle'})",
                   "lernen", icon=":material/auto_awesome:", help=f"Modell: {MODEL_GROSS}."):
        # auch Entwürfe zeigen: Fehler betreffen oft gerade neu angelegte Kategorien
        stand = {key: {**k, "status": "aktiv"} for key, k in kat_sichtbar(KAT_STAND).items()}
        try:
            with st.spinner("KI sucht Muster in den Korrekturen …"):
                antwort = text_anfrage_json(LERN_PROMPT, lern_nachricht(stand, faelle))
        except Exception as ex:
            st.session_state["meldung_lernen"] = f"Vorschläge konnten nicht erstellt werden: {ex}"
        else:
            st.session_state["lern_ergebnis"] = {
                **lern_antwort_pruefen(antwort, KAT_STAND, len(faelle)),
                "dateien": [e.get("dateiname") or "?" for e in quellen],
                "shas": [e.get("datei_sha256") for e in quellen],
                "erstellt": datetime.now().isoformat(timespec="seconds"),
                "anzahl": len(faelle),
            }
            st.session_state["lern_uebernommen"] = set()
        st.rerun()
    erg = st.session_state.get("lern_ergebnis")
    if erg:
        _lern_ergebnis_zeigen(erg)


# Reihenfolge, Farbe und Erklärung der Ursachen in der Anzeige
_URSACHE_ANZEIGE = {
    "regel": ("orange", "Der KI fehlte Wissen – die Vorschläge ergänzen die Kategorie-Beschreibung."),
    "nachfrage_zu_streng": ("blue", "Die KI hat nachgefragt, obwohl alles stimmte – die Vorschläge präzisieren, "
                                    "wann nicht nachgefragt werden muss."),
    "bewertung_widerspruechlich": ("red", "Kommentar und Bewertung passen nicht zusammen – im Tab „Belege“ "
                                          "(Ansicht „Mit Kommentar“) öffnen und über „Korrigieren“ richtigstellen."),
    "lesefehler": ("gray", "Zahl oder Text falsch abgelesen – lässt sich nicht über Regeln beheben. Wo und wie oft "
                           "falsch gelesen wird, zeigt „Lesequalität“ weiter oben."),
    "unklar": ("violet", "Die KI konnte keine eindeutige Ursache erkennen."),
}


def _vorschlag_ursache(v: dict, ursache_je_fall: dict[int, str]) -> str:
    """Ein Vorschlag gehört zur häufigsten Ursache seiner Fälle (ohne Fälle: nach dem Feld)."""
    zaehler: dict[str, int] = {}
    for nr in v["faelle"]:
        u = ursache_je_fall.get(nr)
        if u in ("regel", "nachfrage_zu_streng"):
            zaehler[u] = zaehler.get(u, 0) + 1
    if zaehler:
        return max(zaehler, key=lambda u: (zaehler[u], u == "regel"))
    return "nachfrage_zu_streng" if v["feld"] == "nachfragen_wenn" else "regel"


def _lernfall_karte(f: dict, dateiname: str, sha: str | None, ursache: str) -> None:
    """Kleine Karte für einen Fall ohne Vorschlag: was schiefging + Beleg im Tab „Belege“ vorauswählen."""
    with st.container(border=True, key=f"lernfall_{ursache}_{f['nr']}"):
        text, knopf = st.columns([5, 2], vertical_alignment="center")
        text.markdown(f"**{dateiname}**  \n{f['kurz'] or '–'}")
        geoeffnet = st.session_state.setdefault("lern_geoeffnet", set())
        if not sha:
            return
        if sha in geoeffnet:
            knopf.caption(":material/check: Im Tab „Belege“ ausgewählt")
        elif knopf.button("Im Tab „Belege“ öffnen", icon=":material/arrow_forward:", type="tertiary",
                          key=f"lern_beleg_{ursache}_{f['nr']}"):
            st.session_state["beleg_wahl_naechste"] = sha
            st.session_state["belege_filter_naechste"] = "alle"  # Filter so, dass der Beleg sicher drin ist
            geoeffnet.add(sha)
            st.toast("Beleg im Tab „Belege“ ausgewählt – dort ansehen und ggf. korrigieren.",
                     icon=":material/arrow_forward:")
            st.rerun()


def _lern_ergebnis_zeigen(erg: dict) -> None:
    dateien = erg["dateien"]

    def datei(nr):
        return dateien[nr - 1] if 1 <= nr <= len(dateien) else f"Fall {nr}"

    def sha(nr):
        shas = erg.get("shas") or []  # ältere Ergebnisse dieser Sitzung haben noch keine Hashes
        return shas[nr - 1] if 1 <= nr <= len(shas) else None

    ursache_je_fall = {f["nr"]: f["ursache"] for f in erg["faelle"]}
    faelle_je_ursache = {u: [f for f in erg["faelle"] if f["ursache"] == u] for u in URSACHEN}
    vorschlaege_je_ursache: dict[str, list[tuple[int, dict]]] = {u: [] for u in URSACHEN}
    for i, v in enumerate(erg["vorschlaege"]):
        vorschlaege_je_ursache[_vorschlag_ursache(v, ursache_je_fall)].append((i, v))

    # Kompakte Übersicht: eine Zeile mit farbigen Zählern
    zaehler = "  ".join(f":{_URSACHE_ANZEIGE[u][0]}-badge[{URSACHEN[u]} · {len(faelle_je_ursache[u])}]"
                        for u in _URSACHE_ANZEIGE if faelle_je_ursache[u])
    st.markdown(f"{zaehler}  \n:small[:gray[Erstellt am {zeitpunkt_de(erg['erstellt'])} aus {erg['anzahl']} "
                f"Fällen · {len(erg['vorschlaege'])} {'Vorschlag' if len(erg['vorschlaege']) == 1 else 'Vorschläge'}]]")

    darf = darf_kategorien_bearbeiten()
    uebernommen = st.session_state.setdefault("lern_uebernommen", set())
    sicherheit = {"hoch": ("Sicherheit hoch", "green"), "mittel": ("Sicherheit mittel", "orange"),
                  "niedrig": ("Einzelfall", "gray")}
    for u, (farbe, erklaerung) in _URSACHE_ANZEIGE.items():
        faelle, vorschlaege = faelle_je_ursache[u], vorschlaege_je_ursache[u]
        if not faelle and not vorschlaege:
            continue
        anzahl = f"{len(faelle)} {'Fall' if len(faelle) == 1 else 'Fälle'}"
        st.markdown(f"**{URSACHEN[u]}** :{farbe}-badge[{anzahl}]  \n:small[:gray[{erklaerung}]]")
        for i, v in vorschlaege:
            with st.container(border=True):
                text, s_farbe = sicherheit[v["sicherheit"]]
                st.markdown(f"**{_kategorie_label(v['kategorie'])}** · {KAT_FELD_LABEL[v['feld']]}  "
                            f":{s_farbe}-badge[{text}]")
                st.markdown(f"> {v['text']}")
                st.caption(v["begruendung"] + (" · Fälle: " + ", ".join(datei(n) for n in v["faelle"])
                                               if v["faelle"] else ""))
                if i in uebernommen:
                    st.caption(":material/check: Im Tab „Kategorien“ vorbereitet – dort prüfen, testen, speichern.")
                elif darf and st.button("In Kategorie übernehmen", icon=":material/playlist_add:",
                                        key=f"lern_ueb_{i}"):
                    st.session_state.setdefault("kategorie_vorschlaege_naechste", []).append(
                        {"key": v["kategorie"], "feld": v["feld"], "text": v["text"]})
                    uebernommen.add(i)
                    st.toast("Vorschlag im Tab „Kategorien“ vorbereitet – dort prüfen, testen und speichern.",
                             icon=":material/playlist_add:")
                    st.rerun()
        # Fälle ohne Vorschlag direkt nennen (bei Lesefehlern, Widersprüchen usw. sind das alle)
        abgedeckt = {n for _i, v in vorschlaege for n in v["faelle"]}
        offen = [f for f in faelle if f["nr"] not in abgedeckt]
        if offen and vorschlaege:
            st.caption("Ohne Vorschlag:")
        for f in offen:
            _lernfall_karte(f, datei(f["nr"]), sha(f["nr"]), u)
        if not offen and u in ("regel", "nachfrage_zu_streng") and not vorschlaege:
            st.caption("Kein Vorschlag – die Fälle zeigen (noch) kein Muster.")

    if not erg["vorschlaege"]:
        st.info("Keine Vorschläge für die Kategorie-Beschreibungen – die Fälle zeigen (noch) kein Muster, "
                "das sich mit einer Regel beheben lässt.")
    if erg["rueckfragen"]:
        st.warning("**Rückfragen an die Buchhaltung**\n\n" + "\n".join(f"- {r}" for r in erg["rueckfragen"]),
                   icon=":material/help:")


# ---------------------------------------------------------------------------
# Belege: alle analysierten Belege durchsehen, prüfen und korrigieren – an einer Stelle
# ---------------------------------------------------------------------------

_MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
_BELEG_STATUS = {
    "offen": "Nachfrage offen",
    "ungeprueft": "Noch nicht geprüft",
    "fehlerfrei": "Geprüft – alles richtig",
    "korrigiert": "Geprüft – korrigiert",
    "erledigt_alt": "Erledigt (ohne Bewertung)",
}


def _letzte_entscheidungen(entscheidungen: list[dict]) -> dict[str, dict]:
    """Datei-Hash -> jüngste Entscheidung (erste Version des Nachfragen-Tabs, nur noch lesend)."""
    letzte = {}
    for e in sorted(entscheidungen, key=lambda e: e.get("zeitpunkt") or ""):
        letzte[e.get("datei_sha256")] = e
    return letzte


@st.cache_data(show_spinner="Lade Beleg …", max_entries=30)
def _vorschau(pfad: str) -> list[bytes]:
    endung = "." + pfad.rsplit(".", 1)[-1].lower()
    daten = beleg_laden(pfad)
    return dateien_zu_bildern([(pfad, daten, _MIME.get(endung, "image/jpeg"))])[0]


def _belegbilder(eintrag: dict, bereich: str) -> None:
    pfade = eintrag.get("beleg_pfade") or ([eintrag["beleg_pfad"]] if eintrag.get("beleg_pfad") else [])
    if not pfade:
        st.caption("Zu diesem Eintrag ist kein Original gespeichert.")
    bilder = []
    for pfad in pfade:
        try:
            bilder += _vorschau(pfad)
        except Exception as e:
            st.warning(f"{pfad} konnte nicht geladen werden: {e}")
    _beleg_vorschau(bilder, eintrag.get("dateiname") or ", ".join(pfade),
                    f"{bereich}_{eintrag.get('datei_sha256') or 'ohne_hash'}")


_LAUF_CACHE: dict = {}  # gilt nur für einen Durchlauf – App.py wird bei jeder Eingabe neu ausgeführt


def _alle_belege() -> list[dict]:
    """Alle Belege zusammengeführt – einmal pro Durchlauf berechnet (Tab-Beschriftung, Tab „Belege“,
    Auswertung und „Aus Korrekturen lernen“ brauchen dieselben Daten)."""
    if "belege" not in _LAUF_CACHE:
        _LAUF_CACHE["belege"] = _belege_zusammenfuehren()
    return _LAUF_CACHE["belege"]


def _belege_zusammenfuehren() -> list[dict]:
    """Analysen (neu), Nachfragen (alt), Bewertungen und alte Entscheidungen pro Datei-Hash zusammenführen.

    Ein Beleg: {sha, analyse_eintrag (jüngste Analyse/Nachfrage), bewertung (jüngste), entscheidung (alt),
    gruende (Nachfragegründe der KI), status, zeitpunkt}."""
    belege: dict[str, dict] = {}
    for quelle in sorted(nachfragen_laden() + analysen_laden(), key=lambda e: e.get("zeitpunkt") or ""):
        if quelle.get("datei_sha256"):
            belege.setdefault(quelle["datei_sha256"], {})["analyse_eintrag"] = quelle  # jüngste gewinnt
    for f in _juengste_bewertungen(feedback_laden()):
        if f.get("datei_sha256"):
            belege.setdefault(f["datei_sha256"], {})["bewertung"] = f
    for sha, ent in _letzte_entscheidungen(entscheidungen_laden()).items():
        if sha in belege:
            belege[sha]["entscheidung"] = ent

    for sha, b in belege.items():
        a, f, ent = b.get("analyse_eintrag"), b.get("bewertung"), b.get("entscheidung")
        b["sha"] = sha
        b["gruende"] = (a.get("gruende") if a else None) or (f.get("nachfrage_gruende") if f else None) or []
        if f:
            b["status"] = "fehlerfrei" if _fehlerfrei(f) else "korrigiert"
        elif ent and ent.get("status", "offen") != "offen":
            b["status"] = "erledigt_alt"
        else:
            b["status"] = "offen" if b["gruende"] else "ungeprueft"
        basis = f or a
        b["dateiname"] = basis.get("dateiname")
        b["zeitpunkt"] = max((x.get("zeitpunkt") or "") for x in (a, f) if x)
        b["ki_kategorie"] = (f["kategorie"]["modell"] if f else
                             (a.get("analyse") or {}).get("kategorie") or a.get("kategorie") or "sonstiger_beleg")
    return sorted(belege.values(), key=lambda b: b["zeitpunkt"], reverse=True)


def _offene_nachfragen() -> int | None:
    try:
        return sum(1 for b in _alle_belege() if b["status"] == "offen")
    except Exception:
        return None


def _vergleichstabelle(kategorie: dict, felder: dict) -> None:
    """KI-Lesung neben dem richtigen Wert – grün = stimmte, rot = korrigiert."""
    if kategorie["richtig"]:
        st.success(f"**Belegart richtig:** {_kategorie_label(kategorie['korrekt'])}", icon=":material/check_circle:")
    else:
        st.error(f"**Belegart korrigiert:** KI sagte „{_kategorie_label(kategorie['modell'])}“, richtig ist "
                 f"„{_kategorie_label(kategorie['korrekt'])}“", icon=":material/cancel:")
    _farbtabelle([{
        "Feld": label,
        "KI hat gelesen": anzeige(felder[key]["modell"]) or "–",
        "Richtig ist": anzeige(felder[key]["korrekt"]) or "–",
        "Status": "ok" if felder[key]["richtig"] else "korrigiert",
    } for key, label, _typ in FEEDBACK_FELDER if key in felder], ["Status"], ganze_zeile=True)


_QUELLE = {"nachfrage": "Korrektur einer Nachfrage", "pruefung": "Prüfung im Tab „Belege“"}
_QUELLE_ALT = "Feedback direkt nach der Analyse (frühere Version)"

# --- Suche und Filter im Tab „Belege“ -------------------------------------------------------------

_SUCH_FELDER = ("belegnummer", "restaurant_name", "adresse")  # + Dateiname, Kommentar, Belegart, Datum


def _beleg_werte(b: dict) -> dict:
    """Werte eines Belegs für Suche und Filter: geprüft -> die richtigen Werte, sonst die KI-Lesung."""
    f, a = b.get("bewertung"), b.get("analyse_eintrag") or {}
    werte = dict((f or a).get("analyse") or {})
    if f:
        for key, feld in (f.get("felder") or {}).items():
            werte[key] = feld.get("korrekt")
        werte["kategorie"] = f["kategorie"]["korrekt"]
    else:
        werte["kategorie"] = b["ki_kategorie"]
    return werte


def _beleg_suchtext(b: dict, werte: dict) -> str:
    teile = [b.get("dateiname"), _kategorie_label(werte.get("kategorie")), anzeige(werte.get("datum")),
             ((b.get("bewertung") or {}).get("kommentar"))]
    teile += [anzeige(werte.get(k)) for k in _SUCH_FELDER]
    teile += [anzeige(v) for v in (werte.get("zusatzfelder") or {}).values()]  # künftig: eigene Felder je Kategorie
    return " ".join(str(t) for t in teile if t).casefold()


def _belege_suchen(belege: list[dict]) -> list[dict]:
    """Suchleiste über der Belegliste: Suchbegriffe (alle müssen vorkommen), Belegart, Zeitraum (Belegdatum)."""
    ss = st.session_state
    if ss.pop("belege_suche_zuruecksetzen", False):  # Widgets dürfen erst vor dem Zeichnen geleert werden
        for k in ("belege_suche", "belege_arten", "belege_zeitraum"):
            ss.pop(k, None)
    werte = {b["sha"]: _beleg_werte(b) for b in belege}
    vorhandene = sorted({w.get("kategorie") for w in werte.values() if w.get("kategorie")}, key=_kategorie_label)

    spalte_suche, spalte_art, spalte_datum = st.columns([3, 2, 2], vertical_alignment="bottom")
    suche = spalte_suche.text_input(
        "Suchen", key="belege_suche", icon=":material/search:",
        placeholder="Name, Ort, Beleg-Nr., Aussteller, Datei … (Enter)",
        help="Durchsucht Dateiname, Belegnummer, Aussteller, Adresse, Belegart, Datum und Kommentar. Mehrere "
             "Wörter: alle müssen vorkommen. Bei geprüften Belegen zählen die korrigierten Werte.")
    arten = spalte_art.multiselect("Belegart", vorhandene, key="belege_arten", format_func=_kategorie_label,
                                   placeholder="Alle Belegarten")
    zeitraum = spalte_datum.date_input("Belegdatum von – bis", value=(), key="belege_zeitraum", format="DD.MM.YYYY")

    begriffe = suche.casefold().split()
    von = zeitraum[0] if len(zeitraum) >= 1 else None
    bis = zeitraum[1] if len(zeitraum) >= 2 else None

    def passt(b) -> bool:
        w = werte[b["sha"]]
        if arten and w.get("kategorie") not in arten:
            return False
        if von:
            datum = parse_datum(w.get("datum"))
            if not datum:
                return False
            tag = date.fromisoformat(datum)
            if tag < von or (bis and tag > bis):
                return False
        if begriffe:
            text = _beleg_suchtext(b, w)
            return all(begriff in text for begriff in begriffe)
        return True

    treffer = [b for b in belege if passt(b)]
    if begriffe or arten or von:
        info, knopf = st.columns([4, 1], vertical_alignment="center")
        info.caption(f":material/filter_alt: {len(treffer)} von {len(belege)} Belegen passen zur Suche.")
        if knopf.button("Filter zurücksetzen", icon=":material/close:", type="tertiary", key="belege_suche_weg"):
            ss["belege_suche_zuruecksetzen"] = True
            st.rerun()
    return treffer



def zeige_belege():
    ss = st.session_state
    st.caption(
        "Alle analysierten Belege an einer Stelle: durchsehen, prüfen und – falls die KI etwas falsch gelesen "
        "hat – korrigieren. Das geht auch bei Belegen, die schon als richtig abgehakt sind. Jede Prüfung wird "
        "gespeichert und fließt in die Auswertung und in die Verbesserungsvorschläge ein."
    )
    zuletzt = ss.pop("beleg_zuletzt", None)
    if zuletzt:  # Ergebnis der gerade gespeicherten Prüfung; darunter geht es mit dem nächsten Beleg weiter
        with st.container(border=True):
            st.success(f"„{zuletzt['dateiname']}“ gespeichert. So sieht die Prüfung aus:",
                       icon=":material/check_circle:")
            _vergleichstabelle(zuletzt["kategorie"], zuletzt["felder"])

    try:
        belege = _alle_belege()
    except Exception as e:
        st.error(f"Belege konnten nicht geladen werden: {e}")
        return
    if not belege:
        st.info("Noch keine Belege. Lade im Tab „Belege hochladen“ Belege hoch.")
        return
    belege = _belege_suchen(belege)
    if not belege:
        st.info("Keine Belege passen zur Suche.")
        return

    def mit_kommentar(b):
        return bool(((b.get("bewertung") or {}).get("kommentar") or "").strip())

    filter_ = {
        "offen": ("Nachfragen offen", lambda b: b["status"] == "offen"),
        "ungeprueft": ("Ungeprüft", lambda b: b["status"] == "ungeprueft"),  # ohne Nachfrage (die stehen unter „offen“)
        "korrigiert": ("Korrigiert", lambda b: b["status"] == "korrigiert"),
        "kommentar": ("Mit Kommentar", mit_kommentar),
        "alle": ("Alle", lambda b: True),
    }
    anzahl = {k: sum(1 for b in belege if f(b)) for k, (_l, f) in filter_.items()}
    naechster_filter = ss.pop("belege_filter_naechste", None)  # z. B. aus „Aus Korrekturen lernen“
    if naechster_filter in filter_:
        ss["belege_filter"] = naechster_filter
    if ss.get("belege_filter") not in filter_:  # Start (oder entfernter Filter): dort, wo es etwas zu tun gibt
        ss["belege_filter"] = next((k for k in ("offen", "ungeprueft") if anzahl[k]), "alle")
    def filter_beschriftung(k):
        # Offene Arbeit als farbige Zahl-Plakette (Farbe per CSS), sonst Zahl in Klammern
        if k in ("offen", "ungeprueft") and anzahl[k]:
            return f"{filter_[k][0]} :{'orange' if k == 'offen' else 'blue'}-badge[{anzahl[k]}]"
        return f"{filter_[k][0]} ({anzahl[k]})"

    wahl = st.segmented_control("Anzeigen", list(filter_), format_func=filter_beschriftung,
                                key="belege_filter", label_visibility="collapsed") or "alle"
    liste = [b for b in belege if filter_[wahl][1](b)]
    if not liste:
        st.info("Alles erledigt – in dieser Ansicht gibt es keine Belege." if wahl in ("offen", "ungeprueft")
                else "In dieser Ansicht gibt es keine Belege.")
        return

    shas = [b["sha"] for b in liste]
    nach_sha = {b["sha"]: b for b in liste}
    naechster = ss.pop("beleg_wahl_naechste", None)
    if naechster in shas:
        ss["beleg_wahl"] = naechster
    if ss.get("beleg_wahl") not in shas:
        ss["beleg_wahl"] = shas[0]

    def beschriftung(sha):
        b = nach_sha[sha]
        return (f"{zeitpunkt_de(b['zeitpunkt'])} · {b['dateiname']} · {_kategorie_label(b['ki_kategorie'])}"
                f" · {_BELEG_STATUS[b['status']]}")

    sha = st.selectbox(f"Beleg auswählen ({len(liste)})", shas, format_func=beschriftung, key="beleg_wahl")
    pos = shas.index(sha)
    # Blättern: schmale Leiste unter der Auswahl – „‹ Vorheriger · Beleg 3 von 11 · Nächster ›“
    with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center",
                      key="beleg_blaettern"):
        if st.button("Vorheriger", icon=":material/arrow_back:", type="tertiary", disabled=pos == 0,
                     key="beleg_zurueck"):
            ss["beleg_wahl_naechste"] = shas[pos - 1]
            st.rerun()
        st.markdown(f"Beleg **{pos + 1}** von {len(shas)}", width="content")
        if st.button("Nächster", icon=":material/arrow_forward:", icon_position="right", type="tertiary",
                     disabled=pos == len(shas) - 1, key="beleg_vor"):
            ss["beleg_wahl_naechste"] = shas[pos + 1]
            st.rerun()

    st.divider()
    _beleg_ansicht(nach_sha[sha], shas[pos + 1] if pos + 1 < len(shas) else None)


def _beleg_ansicht(b: dict, naechster: str | None) -> None:
    f, a = b.get("bewertung"), b.get("analyse_eintrag")
    if b["gruende"]:
        titel = "Warum die KI nachfragt" if b["status"] == "offen" else "Die KI hatte nachgefragt"
        (st.error if b["status"] == "offen" else st.warning)(
            f"**{titel}**\n\n" + "\n".join(f"- {g}" for g in b["gruende"]), icon=":material/help:")

    col_bild, col_daten = st.columns([2, 3], gap="large")
    with col_bild, st.container(key="belegspalte_belege"):  # so hoch wie die rechte Spalte (CSS)
        st.subheader("Beleg")
        _belegbilder(f or a, "belege")

    with col_daten:
        if f:
            st.subheader(_BELEG_STATUS[b["status"]])
            offen_key = f"beleg_korrigieren_{b['sha']}_{f.get('zeitpunkt')}"
            if st.session_state.get(offen_key):
                _beleg_formular(b, "korrigieren", naechster, offen_key)
            else:
                _vergleichstabelle(f["kategorie"], f.get("felder") or {})
                details = [f"Geprüft am {zeitpunkt_de(f.get('zeitpunkt'))} von "
                           f"{f.get('bearbeiter') or f.get('benutzer_email') or '–'}",
                           f"Quelle: {_QUELLE.get(f.get('quelle'), _QUELLE_ALT)}",
                           f"Modell: `{f.get('modell') or '–'}` · Prompt-Version: `{f.get('prompt_version') or '–'}`"]
                if f.get("korrektur_von"):
                    details.append(f"Ersetzt die Prüfung vom {zeitpunkt_de(f['korrektur_von'])}")
                st.caption("  \n".join(details))
                if f.get("kommentar"):
                    st.info(f"**Kommentar:** {f['kommentar']}", icon=":material/comment:")
                if st.button("Korrigieren", icon=":material/edit:", key=f"{offen_key}_auf"):
                    st.session_state[offen_key] = True
                    st.rerun()
        elif a and a.get("analyse"):
            if b["status"] == "erledigt_alt":
                ent = b["entscheidung"]
                st.info(f"In der ersten Version erledigt ({ent.get('status')}) am "
                        f"{zeitpunkt_de(ent.get('zeitpunkt'))} von {ent.get('bearbeiter') or '–'}"
                        + (f": {ent['kommentar']}" if ent.get("kommentar") else "")
                        + ". Bitte einmal prüfen.", icon=":material/history:")
            st.subheader("Prüfen und korrigieren" if b["status"] == "offen" else "Prüfen")
            _beleg_formular(b, "nachfrage" if b["gruende"] else "pruefen", naechster)
        else:
            st.warning("Zu diesem Beleg ist kein Analyseergebnis gespeichert.")


def _beleg_formular(b: dict, modus: str, naechster: str | None, offen_key: str | None = None) -> None:
    """modus: "nachfrage" (offene Nachfrage), "pruefen" (noch nicht geprüft), "korrigieren" (Prüfung ändern)."""
    f, a = b.get("bewertung"), b.get("analyse_eintrag")
    basis = f or a
    ki = BelegAnalyse.model_validate(basis.get("analyse") or {})
    ki_kat = b["ki_kategorie"]
    key = f"bf_{b['sha']}_{basis.get('zeitpunkt')}"

    if modus != "korrigieren":
        st.caption("Die Felder zeigen, was die KI gelesen hat. Bitte mit dem Beleg vergleichen und nur Falsches "
                   "korrigieren. Beträge wie 1.234,50 – Datum als TT.MM.JJJJ.")
        if a and a.get("kalender"):
            _zeige_kalender(a["kalender"])
        if ki.korrekturen:
            st.info("**Vom Code umgedeutet**\n\n" + "\n".join(f"- {k}" for k in ki.korrekturen),
                    icon=":material/calculate:")
    kat = f["kategorie"] if f else {}
    kat_korrekt = _belegart_frage(ki_kat, key, richtig=kat.get("richtig") if f else None, korrekt=kat.get("korrekt"))
    felder_alt = (f or {}).get("felder") or {}
    start = SimpleNamespace(**{  # Startwerte: bisher als richtig festgehaltene Werte, sonst die KI-Lesung
        k: (felder_alt[k]["korrekt"] if k in felder_alt else getattr(ki, k)) for k, _l, _t in FEEDBACK_FELDER})
    pflicht = modus != "pruefen"
    with st.form(key=f"{key}_form"):
        korrekturen = _felder_eingabe(start, key)
        begruendung = st.text_area(
            "Begründung (Pflicht)" if pflicht else "Begründung (Pflicht, wenn du etwas änderst)",
            help="Warum lag die KI falsch – oder warum war ihre Nachfrage unnötig? Aus diesen Begründungen werden "
                 "später die Anweisungen an die KI verbessert.",
            placeholder="z. B. Zimmerbuchung – ist eine Übernachtung, keine Bewirtung / Trinkgeld steht "
                        "handschriftlich unten",
        )
        links, mitte, _rest = st.columns([3, 2, 3])
        abgeschickt = links.form_submit_button(
            "Korrigieren" if modus != "pruefen" else "Prüfung speichern", type="primary", width="stretch")
        abbrechen = (mitte.form_submit_button("Abbrechen", icon=":material/close:", width="stretch")
                     if modus == "korrigieren" else False)
    if abbrechen:
        st.session_state[offen_key] = False
        st.rerun()
    if not abgeschickt:
        return
    if kat_korrekt is None:
        st.error("Bitte beantworten, ob die Belegart stimmt (und ggf. die richtige wählen).")
        return
    felder, ungueltig = _felder_auswerten(ki, korrekturen)  # verglichen wird immer mit der KI-Lesung
    if ungueltig:
        st.error("Bitte prüfe diese Eingaben, sie konnten nicht gelesen werden: " + ", ".join(ungueltig))
        return
    geaendert = kat_korrekt != ki_kat or any(not x["richtig"] for x in felder.values())
    if not begruendung.strip() and (pflicht or geaendert):
        st.error("Bitte kurz begründen." + ("" if pflicht else " Du hast etwas geändert – warum lag die KI falsch?"))
        return

    bearbeiter = aktueller_benutzer()
    if f:
        neu = {k: v for k, v in f.items() if k != "zeitpunkt"}
        neu.update({"korrektur_von": f.get("zeitpunkt"), "kommentar_vorher": f.get("kommentar")})
    else:
        neu = {k: a.get(k) for k in ("datei_sha256", "dateiname", "beleg_pfad", "beleg_pfade", "modell",
                                      "prompt_version", "analyse", "kalender", "schiedsrichter")}
        neu.update({"quelle": "nachfrage" if b["gruende"] else "pruefung", "nachfrage_gruende": b["gruende"]})
    neu.update({
        "datei_sha256": b["sha"],
        "kategorie": {"modell": ki_kat, "korrekt": kat_korrekt, "richtig": ki_kat == kat_korrekt},
        "felder": felder,
        "kommentar": begruendung.strip() or None,
        "bearbeiter": bearbeiter,
        "benutzer_email": bearbeiter,
    })
    try:
        feedback_speichern(neu)
    except Exception as ex:
        st.error(f"Speichern fehlgeschlagen – bitte erneut versuchen: {ex}")
        return
    if offen_key:
        st.session_state[offen_key] = False
    elif naechster:  # neu geprüft -> gleich weiter mit dem nächsten Beleg der Liste
        st.session_state["beleg_wahl_naechste"] = naechster
    st.session_state["beleg_zuletzt"] = {"dateiname": b["dateiname"], "kategorie": neu["kategorie"], "felder": felder}
    st.rerun()


# ---------------------------------------------------------------------------
# Kategorien: anlegen, bearbeiten, löschen – fließen in den Prompt ein
# ---------------------------------------------------------------------------

_KAT_STATUS = {"aktiv": "Aktiv (wird bei jeder Analyse verwendet)", "entwurf": "Entwurf (noch nicht aktiv)"}
_NEU = "__neu__"


def _kat_feld_init(praefix: str, k: dict) -> None:
    """Startwerte der Eingabefelder einmalig setzen (danach gehören sie dem Formular / dem Assistenten)."""
    werte = {
        "name": k.get("name", ""),
        "beschreibung": k.get("beschreibung", ""),
        "erkennungsmerkmale": k.get("erkennungsmerkmale", ""),
        "abgrenzung": k.get("abgrenzung", ""),
        "pflichtangaben": "\n".join(k.get("pflichtangaben") or []) if isinstance(k.get("pflichtangaben"), list)
        else (k.get("pflichtangaben") or ""),
        "nachfragen_wenn": k.get("nachfragen_wenn", ""),
        "status": k.get("status", "entwurf"),
        "skr04_konto": k.get("skr04_konto", ""),
        "skr04_bezeichnung": k.get("skr04_bezeichnung", ""),
        "konto_ausnahmen": [dict(a) for a in k.get("konto_ausnahmen") or []],
    }
    for feld, wert in werte.items():
        st.session_state.setdefault(f"{praefix}_{feld}", wert)


def zeige_kategorien():
    meldung = st.session_state.pop("kategorie_meldung", None)
    if meldung:  # als Einblendung, damit die Auswahl ganz oben bleibt
        st.toast(meldung, icon=":material/check_circle:")
    darf = darf_kategorien_bearbeiten()
    ss = st.session_state
    st.caption(
        "Hier legt ihr fest, welche Belegarten die KI kennt und woran sie sie erkennt. Aktive Kategorien und ihre "
        "Beschreibungen fließen bei jeder Analyse in die Anweisungen an die KI ein. Jede Änderung bekommt eine "
        f"neue Prompt-Version (aktuell `{PROMPT_VERSION}`), damit die Auswertung vorher und nachher vergleichen kann."
    )
    if not darf:
        st.caption(":material/lock: Nur ansehen – bearbeiten dürfen freigeschaltete Personen.")

    sichtbare = kat_sichtbar(KAT_STAND)
    optionen = list(sichtbare)
    # Vorschläge aus „Aus Korrekturen lernen“ (Tab Auswertung) als ungespeicherte Änderung einsetzen
    for v in ss.pop("kategorie_vorschlaege_naechste", []):
        if v["key"] not in sichtbare:
            continue
        px = f"kat_{v['key']}_{ss.setdefault('kategorie_generation', 0)}"
        _kat_feld_init(px, sichtbare[v["key"]])
        alt = (ss.get(f"{px}_{v['feld']}") or "").rstrip()
        if v["text"] not in alt:
            ss[f"{px}_{v['feld']}"] = f"{alt}\n{v['text']}" if alt else v["text"]
            ss.setdefault(f"{px}_lernvorschlag", []).append(f"{KAT_FELD_LABEL[v['feld']]}: {v['text']}")
        ss["kategorie_wahl_naechste"] = v["key"]
        ss.pop("kategorie_neu_modus", None)
    # Auswahl im Code ändern (nach Speichern/Löschen) geht nur vor dem Zeichnen der Auswahlliste
    if "kategorie_wahl_naechste" in ss:
        naechste = ss.pop("kategorie_wahl_naechste")
        if naechste in optionen:
            ss["kategorie_wahl"] = naechste
    if ss.get("kategorie_wahl") not in optionen:
        ss.pop("kategorie_wahl", None)

    spalte_liste, spalte_neu = st.columns([3, 1], vertical_alignment="bottom")
    auswahl = spalte_liste.selectbox(
        "Kategorie",
        optionen,
        format_func=lambda key: f"{sichtbare[key]['name']}"
        + ("" if sichtbare[key].get("status") == "aktiv" else " (Entwurf)"),
        key="kategorie_wahl",
        on_change=lambda: ss.pop("kategorie_neu_modus", None),  # Auswahl beendet "neu anlegen"
        label_visibility="collapsed",  # unsichtbar, bleibt aber für Screenreader als Name der Liste erhalten
    )
    if darf and spalte_neu.button("Neue Kategorie", icon=":material/add:", type="primary", width="stretch"):
        ss["kategorie_neu_modus"] = True
    wahl = _NEU if darf and ss.get("kategorie_neu_modus") else auswahl
    k = {} if wahl == _NEU else sichtbare[wahl]
    standard = bool(k.get("standard"))
    # Zähler im Schlüssel: nach dem Speichern frische Eingabefelder mit den gespeicherten Werten
    praefix = f"kat_{wahl}_{st.session_state.setdefault('kategorie_generation', 0)}"
    _kat_feld_init(praefix, k)

    st.divider()
    st.subheader("Neue Kategorie" if wahl == _NEU else k["name"])
    if ss.get(f"{praefix}_lernvorschlag"):
        st.info("**Aus Korrekturen übernommen – noch nicht gespeichert:**\n\n"
                + "\n".join(f"- {t}" for t in ss[f"{praefix}_lernvorschlag"])
                + "\n\nBitte prüfen, mit „Testen“ ausprobieren und dann „Speichern“.",
                icon=":material/playlist_add:")
    st.text_input("Name der Kategorie", key=f"{praefix}_name", disabled=standard or not darf,
                  help="Standard-Kategorien sind im Code verankert und behalten ihren Namen.")
    st.text_area(
        "Beschreibung der Buchhaltung (Freitext)",
        key=f"{praefix}_beschreibung", height=180, disabled=not darf,
        help="So, wie ihr es einem neuen Kollegen erklären würdet: Woran erkennt man den Beleg, was ist "
             "wichtig, was ist Pflicht, wann soll nachgefragt werden?",
    )

    # Assistent: Freitext -> klare Regeln + Rückfragen (Vorschlag, wird erst mit "Speichern" übernommen)
    _lauf_meldung("assistent")
    if darf and _lauf_knopf("Mit KI-Assistent in klare Regeln übersetzen", "assistent", icon=":material/auto_awesome:",
                            help=f"Modell: {MODEL_GROSS}. Füllt die Felder unten als Vorschlag aus."):
        freitext = st.session_state[f"{praefix}_beschreibung"].strip()
        if not freitext:
            st.session_state["meldung_assistent"] = "Bitte zuerst eine Beschreibung eingeben."
        else:
            andere = {key: v for key, v in kat_aktiv(KAT_STAND).items() if key != wahl}
            try:
                with st.spinner("Assistent arbeitet …"):
                    vorschlag = text_anfrage_json(
                        ASSISTENT_PROMPT,
                        assistent_nachricht(st.session_state[f"{praefix}_name"], freitext, andere),
                    )
            except Exception as e:
                st.session_state["meldung_assistent"] = f"Assistent nicht erreichbar: {e}"
            else:  # die Regel-Felder werden erst weiter unten gezeichnet -> Werte jetzt setzen geht
                for feld in ("erkennungsmerkmale", "abgrenzung", "nachfragen_wenn"):
                    if vorschlag.get(feld):
                        st.session_state[f"{praefix}_{feld}"] = str(vorschlag[feld])
                pflicht = vorschlag.get("pflichtangaben")
                if pflicht:
                    st.session_state[f"{praefix}_pflichtangaben"] = (
                        "\n".join(pflicht) if isinstance(pflicht, list) else str(pflicht))
                st.session_state[f"{praefix}_rueckfragen"] = [str(r) for r in vorschlag.get("rueckfragen") or []]
        st.rerun()

    rueckfragen = st.session_state.get(f"{praefix}_rueckfragen")
    if rueckfragen:
        st.warning("**Rückfragen des Assistenten** – bitte in der Beschreibung klären:\n\n"
                   + "\n".join(f"- {r}" for r in rueckfragen), icon=":material/help:")

    st.markdown("**Regeln für die KI** (aus der Beschreibung abgeleitet, frei änderbar)")
    st.text_area("Woran erkennt man die Kategorie?", key=f"{praefix}_erkennungsmerkmale", disabled=not darf)
    st.text_area("Abgrenzung zu anderen Kategorien", key=f"{praefix}_abgrenzung", disabled=not darf)
    st.text_area("Pflichtangaben auf dem Beleg (eine pro Zeile)", key=f"{praefix}_pflichtangaben",
                 disabled=not darf, help="Fehlt eine davon auf dem Beleg, geht er zur Nachfrage.")
    st.text_area("Wann muss nachgefragt werden?", key=f"{praefix}_nachfragen_wenn", disabled=not darf)
    _konto_eingabe(praefix, darf)
    if not standard:
        st.radio("Status", list(_KAT_STATUS), format_func=_KAT_STATUS.get, key=f"{praefix}_status",
                 horizontal=True, disabled=not darf)

    if darf:
        knoepfe = st.columns(4)
        if knoepfe[0].button("Speichern", type="primary", icon=":material/save:", width="stretch"):
            _kategorie_sichern(wahl, k, praefix)
        if knoepfe[1].button(
            "Testen", icon=":material/science:", width="stretch",
            help="Probelauf: Die KI liest eure Beispielbelege einmal mit der bisherigen und einmal mit der "
                 "neuen Beschreibung (so, wie sie gerade hier steht). So siehst du **vor dem Speichern**, ob "
                 "deine Änderung die Erkennung verbessert. Es wird dabei nichts gespeichert.",
        ):
            _probelauf_dialog(wahl, k, praefix)
        if wahl == _NEU:
            if knoepfe[2].button("Abbrechen", icon=":material/close:", width="stretch"):
                _kategorie_auswahl_setzen(None)
                st.rerun()
        elif not standard:
            with knoepfe[2].popover("Löschen", icon=":material/delete:", width="stretch"):
                st.write(f"„{k['name']}“ wirklich löschen? Sie wird nicht mehr verwendet. "
                         "Frühere Versionen bleiben im Verlauf erhalten.")
                if st.button("Ja, löschen", type="primary"):
                    _kategorie_sichern(wahl, k, praefix, loeschen=True)

    if wahl != _NEU:
        with st.expander("So sieht die KI diese Kategorie"):
            st.code(prompt_abschnitt({wahl: {**k, "status": "aktiv"}}), language=None)
        with st.expander("Versionsverlauf"):
            try:
                verlauf = [v for v in kategorien_laden() if v.get("schluessel") == wahl]
            except Exception as e:
                st.error(f"Verlauf nicht ladbar: {e}")
                verlauf = []
            if verlauf:
                _tabelle([{
                    "Version": v.get("version"), "Zeitpunkt": zeitpunkt_de(v.get("zeitpunkt")),
                    "Von": v.get("bearbeiter") or "–", "Status": v.get("status"),
                    "SKR04-Konto": konto_text(v) or "–",
                    "Beschreibung": (v.get("beschreibung") or "")[:120],
                } for v in reversed(verlauf)])
            else:
                st.caption("Noch nicht in der App geändert.")

    # Ergebnis eines Probelaufs bleibt nach dem Schließen des Fensters sichtbar
    ergebnis = ss.get(f"testlauf_{wahl}")
    if ergebnis:
        with st.expander("Letzter Probelauf", expanded=True):
            _zeige_testergebnis(ergebnis)

    with st.expander("Übersicht: SKR04-Konten aller Kategorien"):
        _tabelle([{"Kategorie": v["name"] + ("" if v.get("status") == "aktiv" else " (Entwurf)"),
                   "SKR04-Konto": konto_text(v) or "noch nicht festgelegt",
                   "Ausnahmen": "; ".join(f"{skr04.als_text(a['konto'], a['bezeichnung'])}, wenn {a['wenn']}"
                                          for a in konto_ausnahmen(v)) or "–"}
                  for v in sichtbare.values()])


def _konto_eingabe(praefix: str, darf: bool) -> None:
    """SKR04-Konto der Kategorie: aus der Vorlage übernehmen (füllt beide Felder vor) oder frei eintragen."""
    ss = st.session_state
    st.markdown("**Konto für die Buchung (SKR04)**")
    st.caption("Damit sevDesk den Beleg später richtig einordnet. Die Liste ist nur eine Vorlage – der "
               "Kontenrahmen ist viel größer und ändert sich jährlich. Nummer und Bezeichnung lassen sich "
               "frei ändern oder ganz eigen eintragen. Das Standardkonto setzt das Programm, die KI wählt nur bei Ausnahmen.")
    vorlage = skr04.sortiert()

    def uebernehmen():
        wahl = ss.get(f"{praefix}_konto_vorlage")
        if wahl is not None:
            ss[f"{praefix}_skr04_konto"], ss[f"{praefix}_skr04_bezeichnung"] = vorlage[wahl]
            ss[f"{praefix}_konto_vorlage"] = None  # Liste wieder leer, die Felder darunter zählen

    with st.container(key="kategorie_konto"):
        st.selectbox(
            "Aus der Vorlage übernehmen", range(len(vorlage)), index=None, key=f"{praefix}_konto_vorlage",
            format_func=lambda i: skr04.als_text(*vorlage[i]), on_change=uebernehmen, disabled=not darf,
            placeholder="Konto suchen, z. B. „Bewirtung“ oder „6640“ …", help=skr04.QUELLE,
        )
        spalte_nr, spalte_text = st.columns([1, 3])
        spalte_nr.text_input("Kontonummer", key=f"{praefix}_skr04_konto", disabled=not darf, max_chars=4,
                             placeholder="z. B. 6640")
        spalte_text.text_input("Bezeichnung (optional)", key=f"{praefix}_skr04_bezeichnung", disabled=not darf)
        fehler = skr04.nummer_pruefen(ss.get(f"{praefix}_skr04_konto", ""))
        if fehler:
            st.error(fehler)
        elif not (ss.get(f"{praefix}_skr04_konto") or "").strip():
            st.caption(":material/info: Noch kein Konto festgelegt – ohne Konto kann der Beleg später nicht "
                       "automatisch an sevDesk übergeben werden.")

    with st.container(key="kategorie_konto_ausnahmen"):
        st.markdown("**Ausnahmen** – wann gehört ein Beleg dieser Kategorie auf ein anderes Konto?")
        st.caption("Eine Zeile pro Ausnahme. Die KI wählt dann je Beleg zwischen Standardkonto und diesen "
                   "Ausnahmen und begründet es; deutet der Beleg auf eine Ausnahme hin, ist aber nicht eindeutig, "
                   "fragt sie nach.")
        st.info("**Die Bedingung muss auf dem Beleg zu sehen sein.** Die KI kennt nur den Beleg selbst – gut "
                "sind z. B. „nur ein Gedeck“, „Frühstück auf der Hotelrechnung“, „Shop-Artikel auf dem Tankbon“. "
                "Was nicht auf dem Beleg steht (wer am Tisch saß, wer gereist ist), kann sie nicht erkennen: Dann "
                "bleibt es beim Standardkonto, und ihr korrigiert es bei der Prüfung im Tab „Belege“.",
                icon=":material/visibility:")
        tabelle = st.data_editor(
            pd.DataFrame(ss.get(f"{praefix}_konto_ausnahmen") or [], columns=["wenn", "konto", "bezeichnung"]),
            key=f"{praefix}_konto_ausnahmen_tabelle", num_rows="dynamic", hide_index=True, width="stretch",
            disabled=not darf,
            column_config={
                "wenn": st.column_config.TextColumn("Wenn …", width="large",
                                                    help="Bedingung, z. B. „nur ein Gedeck / allein auf Reise“"),
                "konto": st.column_config.TextColumn("Kontonummer", validate=r"^\d{4}$", max_chars=4,
                                                     help="Vierstellige SKR04-Nummer"),
                "bezeichnung": st.column_config.TextColumn(
                    "Bezeichnung (optional)", help="Leer lassen = Bezeichnung aus der Vorlage, falls vorhanden"),
            },
        )
        ss[f"{praefix}_konto_ausnahmen_wert"] = tabelle.to_dict("records")
        fehler = ausnahmen_aus_tabelle(ss[f"{praefix}_konto_ausnahmen_wert"])[1]
        if fehler:
            st.error(fehler)



def _kategorie_auswahl_setzen(schluessel_neu: str | None) -> None:
    """Auswahl im Code ändern (nach Speichern/Löschen/Abbrechen); wird vor dem nächsten Zeichnen übernommen."""
    ss = st.session_state
    ss["kategorie_wahl_naechste"] = schluessel_neu
    ss.pop("kategorie_neu_modus", None)


@st.dialog("Probelauf: Hilft meine Änderung?", width="large")
def _probelauf_dialog(wahl: str, k: dict, praefix: str) -> None:
    _zeige_testlauf(wahl, k, praefix)


def _kategorie_aus_formular(schluessel: str, name: str, praefix: str) -> dict:
    ss = st.session_state
    return {
        "schluessel": schluessel,
        "name": name,
        "beschreibung": ss[f"{praefix}_beschreibung"].strip(),
        "erkennungsmerkmale": ss[f"{praefix}_erkennungsmerkmale"].strip(),
        "abgrenzung": ss[f"{praefix}_abgrenzung"].strip(),
        "pflichtangaben": [z.strip() for z in ss[f"{praefix}_pflichtangaben"].splitlines() if z.strip()],
        "nachfragen_wenn": ss[f"{praefix}_nachfragen_wenn"].strip(),
        "skr04_konto": (ss.get(f"{praefix}_skr04_konto") or "").strip(),
        "skr04_bezeichnung": (ss.get(f"{praefix}_skr04_bezeichnung") or "").strip(),
        "konto_ausnahmen": ausnahmen_aus_tabelle(ss.get(f"{praefix}_konto_ausnahmen_wert",
                                                         ss.get(f"{praefix}_konto_ausnahmen") or []))[0],
    }


def _standard_ordner(name: str, ordner: list[str]) -> int:
    """Index des Beispielordners, der am besten zum Kategorienamen passt (gleiches erstes Wort)."""
    wort = name.split(":")[-1].split()[0].lower() if name.strip() else ""
    for i, o in enumerate(ordner):
        if o.lower() == name.lower():
            return i
    for i, o in enumerate(ordner):
        if wort and wort[:6] in o.lower():
            return i
    return 0


def _zeige_testlauf(wahl: str, k: dict, praefix: str) -> None:
    st.markdown(
        "Die KI liest eure Beispielbelege zweimal – mit der **bisherigen** und mit der **neuen** Beschreibung "
        "(so, wie sie gerade im Formular steht). Danach siehst du, welche besser funktioniert.",
        help="Es wird dabei nichts gespeichert und nichts verändert. Dauer: etwa 2–4 Minuten. Kosten: "
             "insgesamt nur wenige Cent. Die Beispielbelege liegen in Google Drive im Ordner "
             "„Anlage KI Assistent“ und dort im passenden Unterordner.",
    )
    name = (k.get("name") or st.session_state.get(f"{praefix}_name", "")).strip()
    try:
        ordner = anlage_ordner()
    except Exception as e:
        st.error(f"Beispielordner nicht ladbar: {e}")
        return
    neuer = f"Neuer Ordner: {name}" if name and name not in ordner else None
    optionen = ordner + ([neuer] if neuer else [])
    if not optionen:
        st.info("Bitte zuerst einen Namen für die Kategorie eingeben.")
        return
    gewaehlt = st.selectbox("Welche Beispielbelege sollen genutzt werden? (Ordner in Google Drive)", optionen,
                            index=_standard_ordner(name, ordner) if ordner else 0, key=f"{praefix}_testordner")
    ordnername = name if gewaehlt == neuer else gewaehlt
    belege = beispielbelege(ordnername) if gewaehlt != neuer else []
    anzahl = "1 Beispielbeleg" if len(belege) == 1 else f"{len(belege)} Beispielbelege"
    st.markdown(
        f'<p style="font-size:1.15rem;margin:.25rem 0 .75rem">'
        f'<strong>{anzahl.split(" ")[0]}</strong> {anzahl.split(" ", 1)[1]} im Ordner „{html.escape(ordnername)}“'
        + (f" – getestet werden die ersten <strong>{MAX_TESTBELEGE}</strong>." if len(belege) > MAX_TESTBELEGE
           else ("." if belege else " – bitte zuerst Belege hinzufügen."))
        + "</p>",
        unsafe_allow_html=True,
    )

    upload_ok = st.session_state.pop(f"{praefix}_upload_ok", None)
    if upload_ok:
        st.success(upload_ok, icon=":material/check_circle:")

    _lauf_meldung("probelauf")
    spalte_start, spalte_upload = st.columns(2)
    starten = _lauf_knopf("Probelauf starten", "probelauf", ort=spalte_start, scope="fragment", type="primary",
                          icon=":material/science:", width="stretch", disabled=not belege)
    with spalte_upload.popover("Weitere Belege hinzufügen", icon=":material/upload:", width="stretch"):
        neue = st.file_uploader(f"Belege für „{ordnername}“ auswählen", type=["pdf", "jpg", "jpeg", "png"],
                                accept_multiple_files=True, key=f"{praefix}_testupload")
        if neue and st.button(f"{len(neue)} Datei(en) hochladen", type="primary", icon=":material/upload:"):
            try:
                for datei in neue:
                    beispielbeleg_hochladen(ordnername, datei.name, datei.getvalue(), datei.type)
            except Exception as e:
                st.error(f"Hochladen fehlgeschlagen: {e}")
            else:
                st.session_state[f"{praefix}_upload_ok"] = (
                    f"{len(neue)} Beleg(e) in „{ordnername}“ abgelegt.")
                st.rerun(scope="fragment")  # nur das Fenster neu aufbauen, nicht schließen

    if starten:
        schluessel = wahl if wahl != _NEU else kat_schluessel(name)
        entwurf = {**KAT_STAND, schluessel: {**KAT_STAND.get(schluessel, {}),
                                             **_kategorie_aus_formular(schluessel, name, praefix),
                                             "status": "aktiv", "standard": bool(k.get("standard"))}}
        nachher = system_prompt(prompt_abschnitt(entwurf))
        varianten = {"vorher": SYSTEM_PROMPT_AKTUELL, "nachher": nachher}
        if nachher == SYSTEM_PROMPT_AKTUELL:
            varianten = {"nachher": nachher}  # nichts geändert -> nur ein Durchlauf
        auswahl = belege[:MAX_TESTBELEGE]
        kategorien_registrieren({**labels(KAT_STAND), schluessel: name})  # neue Kategorie für den Test gültig
        # Konto-Regeln: jede Variante nach ihren eigenen (auch noch nicht gespeicherte Ausnahmen)
        konten = {"vorher": kat_konten(KAT_STAND), "nachher": kat_konten(entwurf)}
        konten_registrieren(konten_vereinigen(*konten.values()))
        balken = st.progress(0.0, text="Probelauf läuft …")
        try:
            daten = [(b["name"], beispielbeleg_laden(b["ref"]), b["mime"]) for b in auswahl]
            ergebnisse = testlauf_ausfuehren(
                daten, varianten,
                fortschritt=lambda f, g: balken.progress(f / g, text=f"Probelauf: {f} von {g} Lesungen fertig"),
                konten=konten,
            )
        except Exception as e:
            st.session_state["meldung_probelauf"] = f"Probelauf fehlgeschlagen: {e}"
        else:
            st.session_state[f"testlauf_{wahl}"] = {"ergebnisse": ergebnisse, "varianten": list(varianten),
                                                    "erwartet": erwartete_kategorien(schluessel), "name": name,
                                                    "schluessel": schluessel}
        finally:
            kategorien_registrieren(labels(KAT_STAND))
            konten_registrieren(kat_konten(KAT_STAND))
        st.rerun(scope="fragment")  # Knopf wieder normal, Ergebnis anzeigen – Fenster bleibt offen

    ergebnis = st.session_state.get(f"testlauf_{wahl}")
    if ergebnis:
        _zeige_testergebnis(ergebnis)


_VARIANTE_TITEL = {"vorher": "Bisherige Beschreibung", "nachher": "Neue Beschreibung"}


def _testlauf_fazit(vorher: dict, nachher: dict) -> tuple[str, str]:
    """-> (Art: success/warning/info, verständlicher Satz)."""
    d_erkannt = nachher["erkannt"] - vorher["erkannt"]
    d_nachfragen = nachher["nachfragen"] - vorher["nachfragen"]
    if d_erkannt == 0 and d_nachfragen == 0:
        return "info", "**Kein Unterschied.** Beide Beschreibungen liefern bei den Beispielbelegen dasselbe Ergebnis."

    def belege(n):
        return "1 Beleg" if n == 1 else f"{n} Belege"

    teile = []
    if d_erkannt:
        teile.append(f"{belege(abs(d_erkannt))} {'mehr' if d_erkannt > 0 else 'weniger'} richtig erkannt")
    if d_nachfragen:
        teile.append(f"{belege(abs(d_nachfragen))} {'mehr' if d_nachfragen > 0 else 'weniger'} müssten "
                     "nachgefragt werden")
    satz = "Mit der neuen Beschreibung: " + " und ".join(teile) + "."
    if abs(d_erkannt) + abs(d_nachfragen) <= 1:
        satz += (" Ein Unterschied von nur einem Beleg kann auch Zufall sein – im Zweifel den Probelauf "
                 "noch einmal starten.")
    # Richtig erkennen ist wichtiger als wenige Rückfragen
    besser = d_erkannt > 0 or (d_erkannt == 0 and d_nachfragen < 0)
    if besser:
        return "success", "**Die Änderung hilft.** " + satz
    return "warning", "**Eher nicht speichern.** " + satz


def _zeige_testergebnis(t: dict) -> None:
    ergebnisse, varianten, erwartet = t["ergebnisse"], t["varianten"], t["erwartet"]
    if varianten == ["nachher"]:
        st.info("Die Beschreibung oben ist unverändert – deshalb wurde nur einmal gelesen.",
                icon=":material/info:")
    zahlen = {v: testlauf_zusammenfassung(ergebnisse, v, erwartet) for v in varianten}
    for spalte, v in zip(st.columns(len(varianten)), varianten):
        z = zahlen[v]
        spalte.markdown(f"**{_VARIANTE_TITEL[v]}**")
        spalte.markdown(
            f"- Richtig als „{t['name']}“ erkannt: **{z['erkannt']} von {z['belege']}**\n"
            f"- Müssten nachgefragt werden: **{z['nachfragen']} von {z['belege']}**"
            + (f"\n- Konnten nicht gelesen werden: **{z['fehler']}**" if z["fehler"] else "")
            + ("\n- Konten: " + ", ".join(f"{_konto_label(nr, t.get('schluessel'))} ({n}×)"
                                         for nr, n in sorted(z["konten"].items())) if z.get("konten") else "")
        )
    if len(varianten) == 2:
        art, text = _testlauf_fazit(zahlen["vorher"], zahlen["nachher"])
        getattr(st, art)(text, icon={"success": ":material/thumb_up:", "warning": ":material/thumb_down:",
                                     "info": ":material/drag_handle:"}[art])
    st.caption("Grün = KI ist sicher, rot = müsste nachgefragt werden, grau = Datei nicht lesbar. "
               "✓ = als diese Kategorie erkannt, ✗ = als andere Kategorie erkannt. "
               "Konto mit „?“ = die KI ist beim Konto unsicher.")

    def zelle(e) -> str:
        if e is None:
            return "–"
        if e.fehler:
            return f"Fehler: {e.fehler[:60]}"
        treffer = "✓" if e.kategorie in erwartet else "✗"
        konto = f" · Konto {e.konto}{'?' if e.konto_unsicher else ''}" if getattr(e, "konto", None) else ""
        return (f"{treffer} {_kategorie_label(e.kategorie)} · {e.betrag}{konto} · "
                f"{'Nachfrage' if e.nachfrage else 'ok'}")

    zeilen = []
    for name, je_variante in ergebnisse.items():
        zeile = {"Beleg": name}
        for v in varianten:
            zeile[_VARIANTE_TITEL[v]] = zelle(je_variante.get(v))
        if len(varianten) == 2:
            a, b = je_variante.get("vorher"), je_variante.get("nachher")
            geaendert = a and b and (a.kategorie != b.kategorie or a.nachfrage != b.nachfrage
                                     or getattr(a, "konto", None) != getattr(b, "konto", None))
            zeile["Unterschied"] = "anders" if geaendert else "–"
        zeilen.append(zeile)
    _farbtabelle(zeilen, [_VARIANTE_TITEL[v] for v in varianten])
    with st.expander("Warum müsste nachgefragt werden? (Details)"):
        for name, je_variante in ergebnisse.items():
            for v, e in je_variante.items():
                if e.gruende:
                    st.markdown(f"**{name}** ({_VARIANTE_TITEL[v]}): " + "; ".join(e.gruende))


def _kategorie_sichern(wahl: str, k: dict, praefix: str, loeschen: bool = False) -> None:
    ss = st.session_state
    name = (k["name"] if k.get("standard") else ss[f"{praefix}_name"]).strip()
    if not name:
        st.error("Bitte einen Namen eingeben.")
        return
    konto_fehler = None if loeschen else (
        skr04.nummer_pruefen(ss.get(f"{praefix}_skr04_konto", ""))
        or ausnahmen_aus_tabelle(ss.get(f"{praefix}_konto_ausnahmen_wert", []))[1])
    if konto_fehler:
        st.error(f"Nicht gespeichert: {konto_fehler}")
        return
    schluessel = wahl
    if wahl == _NEU:
        schluessel = kat_schluessel(name)
        if schluessel in KAT_STAND and KAT_STAND[schluessel].get("status") != "geloescht":
            st.error(f"Eine Kategorie mit diesem Namen gibt es schon („{KAT_STAND[schluessel]['name']}“).")
            return
    eintrag = {
        **_kategorie_aus_formular(schluessel, name, praefix),
        "status": "geloescht" if loeschen else ("aktiv" if k.get("standard") else ss[f"{praefix}_status"]),
        "version": int(KAT_STAND.get(schluessel, {}).get("version") or 0) + 1,
        "bearbeiter": aktueller_benutzer(),
    }
    try:
        kategorie_speichern(eintrag)
    except Exception as e:
        st.error(f"Speichern fehlgeschlagen: {e}")
        return
    hinweis = ""
    try:  # lesbare Kopie im Drive – Fehler hier blockieren nicht
        kategorie_dokument_ablegen(name, kat_dokument({**eintrag, "zeitpunkt": None}))
    except Exception as e:
        hinweis = f" (Dokument im Drive konnte nicht aktualisiert werden: {e})"
    ss["kategorie_generation"] = ss.get("kategorie_generation", 0) + 1
    _kategorie_auswahl_setzen(None if loeschen else schluessel)
    aktion = "gelöscht" if loeschen else f"gespeichert (Version {eintrag['version']}, {eintrag['status']})"
    ss["kategorie_meldung"] = f"„{name}“ {aktion}.{hinweis}"
    st.rerun()


# ---------------------------------------------------------------------------
# Seitenaufbau
# ---------------------------------------------------------------------------

def _zustand_zuruecksetzen():
    for k in ("ergebnis", "fehler", "stapel"):
        st.session_state.pop(k, None)


# Tabs farbig absetzen (RE-ALIS-Farben): jede Ansicht hat ihre Farbe (Rand), der aktive Tab ist gefüllt.
# Alle Füllfarben mit weißer Schrift >= 4,5:1 (WCAG AA), als Rand auf hellem Grund >= 3:1.
# (Füllung aktiver Tab, Rand) je Tab: Analyse (Marken-Orange), Nachfragen (Marken-Blau), Kategorien
# (Schiefer aus der Firmenseite), Auswertung (Grün).
_TAB_FARBEN = [("#C25100", "#C25100"), ("#036BD3", "#036BD3"), ("#373A43", "#373A43"), ("#15803D", "#15803D")]
# Selektoren passend zu Streamlit 1.67 (react-aria-Tabs): role="tablist"/"tab", aktiv = [data-selected].
_TAB = '.stTabs [role="tab"]'
st.markdown(
    "<style>"
    # eigene Farben für helles und dunkles Design (data-thema setzt assets/thema.js)
    ':root {--akzent: #C25100; --akzent-flaeche: #FEF3EB; --leise: #5B6170; --rand: #D6D9E0;'
    ' --knopf-flaeche: #fff; --daumen-flaeche: #F3F4F6; --gesperrt: #C3C7CF;'
    # Lesequalität (Auswertung): unter 90 % kräftiger, unter 100 % leicht hervorgehoben
    ' --lq-stark: #FDE7D9; --lq-leicht: #FEF3EB; --lq-text: #7A2E00;'
    ' --status-ok-hg: #DCFCE7; --status-ok-text: #14532D; --status-nachfrage-hg: #FEE2E2;'
    ' --status-nachfrage-text: #7F1D1D; --status-fehler-hg: #E5E7EB; --status-fehler-text: #1F2937;'
    # Zahl-Plaketten an „Nachfragen offen“/„Ungeprüft“ (Tab „Belege“)
    ' --plakette-offen-hg: #C25100; --plakette-ungeprueft-hg: #4A5A7A; --plakette-text: #fff;}'
    'html[data-thema="dunkel"] {--akzent: #F07A2A; --akzent-flaeche: #3A2414; --leise: #A3A9B6; --rand: #3A3E48;'
    ' --knopf-flaeche: #22252D; --daumen-flaeche: #2A2D36; --gesperrt: #4B505C;'
    ' --lq-stark: #4A2B17; --lq-leicht: #2E2219; --lq-text: #FFC9A3;'
    ' --status-ok-hg: #163A26; --status-ok-text: #A7F3C4; --status-nachfrage-hg: #4A1D1D;'
    ' --status-nachfrage-text: #FFC4C4; --status-fehler-hg: #2F333C; --status-fehler-text: #E5E7EB;'
    ' --plakette-offen-hg: #F07A2A; --plakette-ungeprueft-hg: #A9B8D6; --plakette-text: #14151A;}'
    # Plaketten: kräftig statt Streamlits blasser Badge-Farben (Reihenfolge der Filter: offen, ungeprüft)
    '.st-key-belege_filter .stMarkdownBadge, .stTabs [role="tab"] .stMarkdownBadge'
    ' {color: var(--plakette-text) !important; font-weight: 700;'
    ' border-radius: 999px !important; padding: 0 .5em !important; min-width: 1.5em; text-align: center;}'
    '.st-key-belege_filter button:nth-of-type(1) .stMarkdownBadge, .stTabs [role="tab"] .stMarkdownBadge'
    ' {background-color: var(--plakette-offen-hg) !important;}'
    '.st-key-belege_filter button:nth-of-type(2) .stMarkdownBadge'
    ' {background-color: var(--plakette-ungeprueft-hg) !important;}'
    '[class*="st-key-belegbild_"] img {max-height: 560px; width: auto; max-width: 100%; object-fit: contain;'
    ' display: block; margin: 0 auto;}'
    '[class*="st-key-belegbild_"] {position: relative;}'
    + ''.join(f'[class*="st-key-belegbild_"] {x}, ' for x in (
        '[data-testid="stElementContainer"]', '[data-testid="stFullScreenFrame"]',
        '[data-testid="stFullScreenFrame"] > div', '[data-testid="stImage"]'))
    + '[class*="st-key-belegbild_"] [data-testid="stImageContainer"]'
    ' {width: 100% !important; align-items: center; justify-content: center;}'
    '[class*="st-key-belegbild_"] [data-testid="stElementToolbar"],'
    ' [class*="st-key-belegdaumen_"] [data-testid="stElementToolbar"] {display: none;}'
    # mehrere Seiten: anfangs nur Seite 1 sichtbar, das Skript blendet beim Blättern die gewählte ein
    '[class*="st-key-belegbild_"] > [data-testid="stElementContainer"]:not(:first-child) {display: none;}'
    # Blätterleiste ‹ Seite x von n ›
    '.belegnav {display: flex; align-items: center; justify-content: center; gap: .9rem; color: var(--leise);'
    ' font-size: .92rem; user-select: none;}'
    '.belegnav button {width: 34px; height: 34px; border-radius: 50%; border: 1px solid var(--rand);'
    ' background: var(--knopf-flaeche);'
    ' color: var(--akzent); font-size: 1.3rem; line-height: 1; cursor: pointer; display: inline-flex;'
    ' align-items: center; justify-content: center; padding: 0 0 2px;}'
    '.belegnav button:hover:not(:disabled) {border-color: var(--akzent); background: var(--akzent-flaeche);}'
    '.belegnav button:disabled {color: var(--gesperrt); cursor: default;}'
    '.belegnav button:focus-visible {outline: 3px solid var(--akzent); outline-offset: 2px;}'
    # Mini-Vorschauen aller Seiten, aktuelle orange umrandet
    '[class*="st-key-belegdaumen_"] {flex-wrap: nowrap !important; overflow-x: auto; padding: 2px 0 4px;}'
    '[class*="st-key-belegdaumen_"] img {height: 52px !important; width: auto !important; max-width: 64px;'
    ' object-fit: contain; background: var(--daumen-flaeche); border: 2px solid transparent; border-radius: 4px;'
    ' cursor: pointer; opacity: .65; transition: opacity .12s, border-color .12s;}'
    '[class*="st-key-belegdaumen_"] img:hover {opacity: 1;}'
    '[class*="st-key-belegdaumen_"] img[data-aktiv="1"] {border-color: var(--akzent); opacity: 1;}'
    # Analyse-Knopf: während der Analyse nur ein drehender Spinner (Text bleibt für Screenreader erhalten)
    "@keyframes beleg-dreh {to {transform: rotate(360deg);}}"
    '[class*="st-key-laufknopf_"] button:disabled [data-testid="stIconMaterial"]'
    ' {animation: beleg-dreh 1s linear infinite;}'
    '[class*="st-key-laufknopf_"] button:disabled [data-testid="stMarkdownContainer"] {position: absolute; width: 1px;'
    ' height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap;}'
    '[class*="st-key-laufknopf_"] button {min-width: 12rem;}'
    # kleinere Karten für Lern-Fälle ohne Vorschlag; Knopf als Link in der Akzentfarbe
    '[class*="st-key-lernfall_"] {padding: .55rem .9rem !important; gap: .25rem;}'
    '[class*="st-key-lernfall_"] p {font-size: .92rem;}'
    '[class*="st-key-lernfall_"] button:not(:disabled), [class*="st-key-lernfall_"] button:not(:disabled) p'
    ' {color: var(--akzent); font-weight: 600;}'
    # Ladebalken oben über die ganze Breite, solange Streamlit rechnet (Filter, Blättern, Speichern, …)
    "@keyframes lade-balken {from {background-position: -40% 0;} to {background-position: 140% 0;}}"
    'body:has([data-testid="stStatusWidgetRunningIcon"], [data-testid="stStatusWidgetRunningManIcon"])::before'
    ' {content: ""; position: fixed; top: 0; left: 0; right: 0; height: 3px; z-index: 1000001;'
    ' pointer-events: none; background: linear-gradient(90deg, transparent, #C25100, transparent) no-repeat;'
    ' background-size: 40% 100%; animation: lade-balken 1.1s ease-in-out infinite;}'
    "@media (prefers-reduced-motion: reduce) {body::before {animation: none !important;"
    " background: #C25100 !important;}}"
    # Blätterleiste im Tab „Belege“: als Links in der Akzentfarbe erkennbar, dicht unter der Auswahl
    '.st-key-beleg_blaettern {margin-top: -.6rem; justify-content: center !important; gap: 1.5rem !important;}'
    '.st-key-beleg_blaettern button:not(:disabled), .st-key-beleg_blaettern button:not(:disabled) p'
    ' {color: var(--akzent); font-weight: 600;}'
    '.st-key-beleg_blaettern button:not(:disabled):hover p {text-decoration: underline;}'
    '.st-key-beleg_blaettern [data-testid="stMarkdownContainer"] p {color: var(--leise); font-size: .9rem;}'
    # solange der Knopf gesperrt ist (Analyse läuft), sind die anderen Tabs gesperrt
    '.stApp:has([class*="st-key-laufknopf_"] button:disabled) .stTabs [role="tab"]:not([data-selected])'
    ' {pointer-events: none; opacity: .4;}'
    # Belegspalte (Tab „Belege“) genau so hoch wie die rechte Spalte: Inhalt absolut im Spaltenrahmen, die
    # aktuelle Seite füllt den Platz zwischen Überschrift und Blätterleiste. Nur nebeneinander (ab 640 px).
    "@media (min-width: 640px) {"
    '[data-testid="stColumn"]:has([class*="st-key-belegspalte_"]) {position: relative; min-height: 360px;}'
    '[class*="st-key-belegspalte_"] {position: absolute; inset: 0; flex-wrap: nowrap;}'
    '[class*="st-key-belegspalte_"] > :has([class*="st-key-belegbild_"]) {flex: 1 1 0; min-height: 0;}'
    '[class*="st-key-belegspalte_"] [class*="st-key-belegbild_"],'
    ' [class*="st-key-belegspalte_"] [class*="st-key-belegbild_"] div {height: 100%; min-height: 0;}'
    '[class*="st-key-belegspalte_"] [class*="st-key-belegbild_"] img {height: 100%; max-height: none;'
    ' width: 100%; object-fit: contain; object-position: center top;}'
    "}"
    '.stTabs [role="tablist"] {gap: .5rem; padding: .4rem; border-radius: .75rem; flex-wrap: wrap;'
    " background: rgba(128,128,128,.14);}"
    '.stTabs [role="tablist"]::after {display: none;}'  # graue Grundlinie ausblenden
    f"{_TAB} {{padding: .5rem 1.1rem; border-radius: .55rem; height: auto; border: 2px solid transparent;"
    " font-weight: 600; color: inherit;}"
    f"{_TAB} p {{font-size: 1rem;}}"
    f"{_TAB} .react-aria-SelectionIndicator {{display: none;}}"  # Unterstrich ersetzt durch Füllung
    + "".join(
        f"{_TAB}:nth-child({i}) {{border-color: {rand};}}"
        f"{_TAB}:nth-child({i})[data-hovered]:not([data-selected]) {{background: {fuellung}55; color: inherit;}}"
        f"{_TAB}:nth-child({i})[data-selected] {{background: {fuellung}; color: #fff;}}"
        f"{_TAB}:nth-child({i})[data-selected] p {{color: #fff;}}"
        for i, (fuellung, rand) in enumerate(_TAB_FARBEN, start=1)
    )
    # dunkles Design: Schiefer-Tab (Kategorien) heller, sonst verschwindet er im dunklen Hintergrund
    + f'html[data-thema="dunkel"] {_TAB}:nth-child(3) {{border-color: #8A90A0;}}'
    f'html[data-thema="dunkel"] {_TAB}:nth-child(3)[data-selected] {{background: #5B6170;}}'
    + "</style>",
    unsafe_allow_html=True,
)


kopfzeile()
_offen = _offene_nachfragen()
tab_analyse, tab_belege, tab_kategorien, tab_auswertung = st.tabs([
    ":material/upload_file: Belege hochladen",
    ":material/receipt_long: Belege" + (f" :orange-badge[{_offen} offen]" if _offen else ""),  # Plakette, Farbe per CSS
    ":material/category: Kategorien",
    ":material/monitoring: Auswertung",
])

with tab_analyse:
    st.caption(
        "Lade einen oder mehrere Belege hoch. Die KI ordnet sie ein (Bewirtung, Tanken, Übernachtung, ...), "
        "liest die Daten ab, der Code rechnet nach. Jeder Beleg landet danach im Tab „Belege“ – dort lässt er "
        "sich prüfen und korrigieren; Belege mit Nachfrage der KI sind dort eigens gefiltert."
    )
    uploads = st.file_uploader(
        "Belege hochladen (JPG, PNG, PDF)",
        type=["jpg", "jpeg", "png", "pdf"],
        accept_multiple_files=True,
        help=f"Mehrere Dateien auf einmal möglich (bis {MAX_STAPEL}). Mehrseitige PDFs werden vollständig "
             f"gelesen (bis {MAX_SEITEN} Seiten).",
    )

    stapel_modus = False
    if uploads and len(uploads) > 1:
        modus = st.radio(
            "Wie sollen die Dateien gelesen werden?",
            ["stapel", "ein_beleg"],
            format_func={
                "stapel": f"Jede Datei ist ein eigener Beleg (Stapel, {len(uploads)} Belege)",
                "ein_beleg": "Alle Dateien gehören zu EINEM Beleg (z. B. Rechnung + EC-Beleg, mehrere Fotos)",
            }.get,
            key="upload_modus",
        )
        stapel_modus = modus == "stapel"
        if stapel_modus and len(uploads) > MAX_STAPEL:
            st.warning(f"Es werden die ersten {MAX_STAPEL} von {len(uploads)} Dateien analysiert.")

    if not uploads:
        _zustand_zuruecksetzen()  # Dateien entfernt -> alten Zustand verwerfen
    else:
        # andere Dateien oder anderer Modus -> alte Ergebnisse passen nicht mehr
        kennung = (stapel_modus, beleg_hash(_dateien(uploads)))
        if st.session_state.get("upload_kennung") != kennung:
            _zustand_zuruecksetzen()
            st.session_state["upload_kennung"] = kennung

        knopf = f"{min(len(uploads), MAX_STAPEL)} Belege analysieren" if stapel_modus else "Beleg analysieren"
        if _lauf_knopf(knopf, "analyse", type="primary"):
            st.caption("Analyse läuft – bitte warten. Die anderen Tabs sind so lange gesperrt.")
            if stapel_modus:
                stapel_starten(uploads)
            else:
                analyse_starten(uploads)  # zeigt den Fortschritt selbst an (st.status)
            st.rerun()

    if "fehler" in st.session_state:
        meldung, raw = st.session_state["fehler"]
        st.error(meldung)
        if raw:
            st.code(raw)

    if "stapel" in st.session_state:
        zeige_stapel(st.session_state["stapel"])
    elif "ergebnis" in st.session_state:
        zeige_ergebnis(st.session_state["ergebnis"])

with tab_belege:
    zeige_belege()

with tab_kategorien:
    zeige_kategorien()

with tab_auswertung:
    zeige_auswertung()

st.divider()
st.caption(
    f"Proof of Concept · Modell `{MODEL}` (liest doppelt) · Schiedsrichter `{MODEL_GROSS}` · "
    f"Prompt-Version `{PROMPT_VERSION}`"
)
einfuehrung_ausfuehren()  # Autostart-Prüfung bzw. direkt nach Klick auf „Einführung starten“
belegansicht_einbetten()  # große Belegansicht ohne Wartezeit

