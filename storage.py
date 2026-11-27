"""Ablage von Belegen und Feedback – in EINEM gemeinsamen Ordner für alle Benutzer.

Google Drive (Streamlit Cloud): aktiv, sobald in den Secrets [google_drive] mit `ordner_id` und
`refresh_token` steht. Die App schreibt mit dem Konto des Ordner-Besitzers, nicht mit dem des Benutzers.

    <ordner>/belege/<sha256[:16]>.<ext>        Originalbelege (Duplikate werden nicht doppelt abgelegt)
    <ordner>/feedback/<zeitpunkt>_<sha16>.json  eine Datei pro Bewertung (Drive kann nicht anhängen)
    <ordner>/nachfragen/<zeitpunkt>_<sha16>.json  unsichere/unstimmige Belege, die ein Mensch klären muss

Lokal (ohne [google_drive]): <Projekt>/data bzw. BELEG_DATENORDNER, mit Rechten 0700/0600.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

# Rechte, die drive_token_holen.py beim Token anfragt (Drive schreiben, Kalender nur lesen)
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/drive", "https://www.googleapis.com/auth/calendar.readonly"]
DRIVE_SCOPES = GOOGLE_SCOPES  # alter Name, bleibt für Kompatibilität
_ORDNER_MIME = "application/vnd.google-apps.folder"
_MIME_NACH_ENDUNG = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
# Funktioniert für "Meine Ablage" und für geteilte Ablagen (Shared Drives)
_ALLE_ABLAGEN = {"supportsAllDrives": True}
_ALLE_ABLAGEN_LISTE = {"supportsAllDrives": True, "includeItemsFromAllDrives": True}


class AblageFehler(RuntimeError):
    pass


def _secrets_abschnitt(name: str) -> dict:
    try:
        return dict(st.secrets.get(name, {}))
    except FileNotFoundError:  # keine secrets.toml vorhanden
        return {}


def datei_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def _beleg_dateiname(dateiname: str, sha: str) -> str:
    endung = Path(dateiname).suffix.lower() or ".bin"
    return f"{sha[:16]}{endung}"


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

def _drive_config() -> dict | None:
    cfg = _secrets_abschnitt("google_drive")
    if not cfg:
        return None
    auth = _secrets_abschnitt("auth")
    # Client-Daten dürfen fehlen, dann wird der OAuth-Client aus [auth] mitbenutzt
    cfg.setdefault("client_id", auth.get("client_id"))
    cfg.setdefault("client_secret", auth.get("client_secret"))
    fehlend = [k for k in ("ordner_id", "refresh_token", "client_id", "client_secret") if not cfg.get(k)]
    if fehlend:
        # Halb konfiguriert -> lieber Fehler als still lokal speichern (Daten wären auf Cloud weg)
        raise AblageFehler(f"[google_drive] unvollständig, es fehlt: {', '.join(fehlend)}")
    return cfg


def ablage_beschreibung() -> str:
    try:
        return "Google Drive" if _drive_config() else "lokal"
    except AblageFehler:
        return "falsch konfiguriert"


def ablage_link() -> str | None:
    """Link zum Drive-Ordner (öffnet nur für Personen, die Zugriff auf den Ordner haben)."""
    try:
        cfg = _drive_config()
    except AblageFehler:
        return None
    return f"https://drive.google.com/drive/folders/{cfg['ordner_id']}" if cfg else None


def ablage_pruefen() -> None:
    """Beim Start aufrufen: wirft AblageFehler, wenn Drive konfiguriert, aber nicht erreichbar ist."""
    if _drive_config():
        _drive_ordner_pruefen()


# ---------------------------------------------------------------------------
# Google Drive
# ---------------------------------------------------------------------------

@st.cache_resource
def _drive_credentials(refresh_token: str, client_id: str, client_secret: str):
    """Pro Token-Kombination gecacht -> ein neuer refresh_token in den Secrets greift ohne Neustart."""
    from google.oauth2.credentials import Credentials

    return Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=None,  # beim Erneuern keine Rechte fordern -> alte Tokens (nur Drive) laufen weiter
    )


def _drive():
    # Pro Aufruf neu bauen: der HTTP-Client ist nicht thread-sicher, Streamlit-Sessions laufen parallel.
    from googleapiclient.discovery import build

    cfg = _drive_config()
    creds = _drive_credentials(cfg["refresh_token"], cfg["client_id"], cfg["client_secret"])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


@st.cache_data(ttl=3600, show_spinner=False)
def _drive_ordner_pruefen() -> None:
    from googleapiclient.errors import HttpError

    ordner_id = _drive_config()["ordner_id"]
    try:
        meta = _drive().files().get(fileId=ordner_id, fields="mimeType, trashed", **_ALLE_ABLAGEN).execute()
    except HttpError as e:
        raise AblageFehler(f"Drive-Ordner nicht erreichbar (ordner_id / Rechte prüfen): {e.reason}") from e
    except Exception as e:  # z. B. invalid_grant = Refresh-Token abgelaufen/widerrufen
        raise AblageFehler(f"Anmeldung bei Google Drive fehlgeschlagen (refresh_token erneuern): {e}") from e
    if meta.get("mimeType") != _ORDNER_MIME or meta.get("trashed"):
        raise AblageFehler("ordner_id zeigt nicht auf einen (nicht gelöschten) Ordner.")


@st.cache_data(ttl=3600, show_spinner=False)
def _unterordner_id(name: str) -> str:
    """ID des Unterordners im konfigurierten Drive-Ordner; wird bei Bedarf angelegt."""
    eltern = _drive_config()["ordner_id"]
    svc = _drive()
    q = f"'{eltern}' in parents and name = '{name}' and mimeType = '{_ORDNER_MIME}' and trashed = false"
    treffer = svc.files().list(q=q, fields="files(id)", pageSize=1, **_ALLE_ABLAGEN_LISTE).execute().get("files", [])
    if treffer:
        return treffer[0]["id"]
    neu = svc.files().create(
        body={"name": name, "mimeType": _ORDNER_MIME, "parents": [eltern]}, fields="id", **_ALLE_ABLAGEN
    ).execute()
    return neu["id"]


def _drive_hochladen(ordner_id: str, name: str, inhalt: bytes, mime: str) -> None:
    from googleapiclient.http import MediaInMemoryUpload

    _drive().files().create(
        body={"name": name, "parents": [ordner_id]},
        media_body=MediaInMemoryUpload(inhalt, mimetype=mime),
        fields="id",
        **_ALLE_ABLAGEN,
    ).execute()


def _drive_beleg_speichern(file_bytes: bytes, name: str) -> str:
    ordner = _unterordner_id("belege")
    q = f"'{ordner}' in parents and name = '{name}' and trashed = false"
    vorhanden = _drive().files().list(q=q, fields="files(id)", pageSize=1, **_ALLE_ABLAGEN_LISTE).execute()
    if not vorhanden.get("files"):
        mime = _MIME_NACH_ENDUNG.get(Path(name).suffix, "application/octet-stream")
        _drive_hochladen(ordner, name, file_bytes, mime)
    return f"belege/{name}"


# Einträge (feedback/, analysen/ …) werden nie geändert, nur neue angehängt -> pro Datei-ID dauerhaft im
# Speicher (für alle Sitzungen des Servers). Nur Dateien, die hier noch fehlen, werden geladen – parallel.
_JSON_CACHE: dict[str, dict | None] = {}
DRIVE_PARALLEL = 8     # gleichzeitige Downloads (Drive erlaubt deutlich mehr; mehr bringt kaum noch etwas)
DRIVE_WIEDERHOLUNGEN = 3  # bei 429/5xx automatisch erneut (googleapiclient wartet dazwischen exponentiell)


def _drive_dienst_bauen(creds):
    """Eigene Verbindung – der HTTP-Client von googleapiclient ist nicht thread-sicher."""
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _drive_jsons_holen(file_ids: list[str]) -> None:
    """Fehlende Einträge parallel laden und in _JSON_CACHE legen (jeder Thread mit eigener Verbindung)."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    fehlend = list(dict.fromkeys(i for i in file_ids if i not in _JSON_CACHE))
    if not fehlend:
        return
    cfg = _drive_config()
    creds = _drive_credentials(cfg["refresh_token"], cfg["client_id"], cfg["client_secret"])
    lokal = threading.local()

    def holen(file_id: str) -> tuple[str, dict | None]:
        if not hasattr(lokal, "dienst"):
            lokal.dienst = _drive_dienst_bauen(creds)
        roh = lokal.dienst.files().get_media(fileId=file_id, **_ALLE_ABLAGEN).execute(
            num_retries=DRIVE_WIEDERHOLUNGEN)
        try:
            return file_id, json.loads(roh)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return file_id, None  # defekte Datei überspringen statt alles zu blockieren

    with ThreadPoolExecutor(max_workers=min(DRIVE_PARALLEL, len(fehlend))) as pool:
        for file_id, daten in pool.map(holen, fehlend):  # Ergebnisse im aufrufenden Thread einsortieren
            _JSON_CACHE[file_id] = daten


@st.cache_data(ttl=300, show_spinner="Lade Daten aus Google Drive...")
def _drive_jsons_laden(ordnername: str) -> list[dict]:
    return _drive_jsons_lesen(ordnername)


def _drive_jsons_lesen(ordnername: str) -> list[dict]:
    """Alle Einträge eines Unterordners in Namens- (= Zeit-)Reihenfolge."""
    ordner = _unterordner_id(ordnername)
    svc = _drive()
    dateien, token = [], None
    while True:
        res = svc.files().list(
            q=f"'{ordner}' in parents and trashed = false",
            fields="nextPageToken, files(id, name)",
            orderBy="name",
            pageSize=1000,
            pageToken=token,
            **_ALLE_ABLAGEN_LISTE,
        ).execute()
        dateien += res.get("files", [])
        token = res.get("nextPageToken")
        if not token:
            break
    _drive_jsons_holen([d["id"] for d in dateien])
    eintraege = [_JSON_CACHE.get(d["id"]) for d in dateien]
    return [e for e in eintraege if e is not None]


# ---------------------------------------------------------------------------
# Lokal
# ---------------------------------------------------------------------------

def _lokaler_ordner() -> Path:
    pfad = os.getenv("BELEG_DATENORDNER")  # Secrets auf oberster Ebene landen bei Streamlit auch in os.environ
    return Path(pfad).expanduser().resolve() if pfad else Path(__file__).parent.resolve() / "data"


def _ordner_anlegen(ordner: Path) -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(ordner, 0o700)  # unter Windows wirkungslos, auf Linux wirksam
    except OSError:
        pass


def _rechte_setzen(datei: Path) -> None:
    try:
        os.chmod(datei, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Öffentliche Funktionen (Backend wird automatisch gewählt)
# ---------------------------------------------------------------------------

def beleg_speichern(file_bytes: bytes, dateiname: str, sha: str) -> str:
    """Speichert die Originaldatei unter ihrem Hash (Duplikate werden nicht doppelt abgelegt)."""
    name = _beleg_dateiname(dateiname, sha)
    if _drive_config():
        return _drive_beleg_speichern(file_bytes, name)

    beleg_dir = _lokaler_ordner() / "belege"
    _ordner_anlegen(beleg_dir.parent)
    _ordner_anlegen(beleg_dir)
    ziel = beleg_dir / name
    if not ziel.exists():
        ziel.write_bytes(file_bytes)
        _rechte_setzen(ziel)
    return f"belege/{name}"


def _eintrag_speichern(art: str, eintrag: dict) -> None:
    """art = "feedback" | "nachfragen". Drive: eine JSON-Datei pro Eintrag, lokal: <art>.jsonl."""
    eintrag = {"zeitpunkt": datetime.now().isoformat(timespec="seconds"), **eintrag}
    zeile = json.dumps(eintrag, ensure_ascii=False)

    if _drive_config():
        sha16 = (eintrag.get("datei_sha256") or "unbekannt")[:16]
        name = f"{eintrag['zeitpunkt'].replace(':', '-')}_{sha16}.json"
        _drive_hochladen(_unterordner_id(art), name, zeile.encode("utf-8"), "application/json")
        _drive_jsons_laden.clear()  # Anzeige soll den neuen Eintrag sofort sehen
        return

    ordner = _lokaler_ordner()
    _ordner_anlegen(ordner)
    datei = ordner / f"{art}.jsonl"
    neu = not datei.exists()
    with datei.open("a", encoding="utf-8") as f:
        f.write(zeile + "\n")
    if neu:
        _rechte_setzen(datei)


def _eintraege_laden(art: str) -> list[dict]:
    if _drive_config():
        return _drive_jsons_laden(art)

    datei = _lokaler_ordner() / f"{art}.jsonl"
    if not datei.exists():
        return []
    eintraege = []
    with datei.open(encoding="utf-8") as f:
        for zeile in f:
            zeile = zeile.strip()
            if zeile:
                try:
                    eintraege.append(json.loads(zeile))
                except json.JSONDecodeError:
                    continue  # defekte Zeile überspringen statt alles zu blockieren
    return eintraege


def feedback_speichern(eintrag: dict) -> None:
    _eintrag_speichern("feedback", eintrag)


def feedback_laden() -> list[dict]:
    return _eintraege_laden("feedback")


def schon_bewertet(sha: str) -> bool:
    return any(e.get("datei_sha256") == sha for e in feedback_laden())


def nachfrage_speichern(eintrag: dict) -> bool:
    """Legt einen Beleg zur Nachfrage ab. False, wenn derselbe Beleg (Hash) dort schon liegt."""
    sha = eintrag.get("datei_sha256")
    if sha and any(e.get("datei_sha256") == sha for e in nachfragen_laden()):
        return False
    _eintrag_speichern("nachfragen", eintrag)
    return True


def nachfragen_laden() -> list[dict]:
    return _eintraege_laden("nachfragen")


# Jede Analyse (auch ohne Nachfrage) – damit im Tab „Belege“ alle Belege durchgesehen und korrigiert werden
# können. Nur anhängen; wird derselbe Beleg erneut analysiert, gilt die jüngste Analyse.

def analyse_speichern(eintrag: dict) -> None:
    _eintrag_speichern("analysen", eintrag)


def analysen_laden() -> list[dict]:
    return _eintraege_laden("analysen")


# „Aus Korrekturen lernen“: jede Runde (Fälle, Ursachen, Vorschläge) – damit sie nach dem Neuladen noch da ist
# und sich später nachvollziehen lässt, welcher Vorschlag übernommen wurde und was er bewirkt hat.

def lernrunde_speichern(eintrag: dict) -> None:
    _eintrag_speichern("lernrunden", eintrag)


def lernrunden_laden() -> list[dict]:
    return _eintraege_laden("lernrunden")


# ---------------------------------------------------------------------------
# Beleg entfernen (z. B. falsch hochgeladen): in den Papierkorb statt endgültig löschen
# ---------------------------------------------------------------------------

EINTRAG_ARTEN = ("analysen", "nachfragen", "feedback", "entscheidungen")  # alles, was zu einem Datei-Hash gehört


def beleg_in_papierkorb(sha: str, beleg_pfade: list[str]) -> int:
    """Alle Einträge zum Beleg (Analyse, Prüfungen, alte Nachfragen/Entscheidungen) und die übergebenen
    Originaldateien in den Papierkorb. Drive: 30 Tage im Drive-Papierkorb wiederherstellbar. Lokal: nach
    data/papierkorb/. beleg_pfade: nur Originale, die kein anderer Beleg mehr nutzt (prüft der Aufrufer).
    -> Anzahl verschobener Dateien bzw. Einträge."""
    if _drive_config():
        return _drive_in_papierkorb(sha, beleg_pfade)
    return _lokal_in_papierkorb(sha, beleg_pfade)


def _drive_in_papierkorb(sha: str, beleg_pfade: list[str]) -> int:
    svc = _drive()
    ziele = []
    endung = f"_{sha[:16]}.json"  # Einträge heißen <zeitpunkt>_<sha16>.json (siehe _eintrag_speichern)
    for art in EINTRAG_ARTEN:
        # nach Namen im Code filtern: „name contains“ findet bei Drive nur Wortanfänge
        ziele += [d["id"] for d in _drive_dateien(svc, _unterordner_id(art)) if d["name"].endswith(endung)]
    namen = {pfad.split("/")[-1] for pfad in beleg_pfade}
    if namen:
        ziele += [d["id"] for d in _drive_dateien(svc, _unterordner_id("belege")) if d["name"] in namen]
    ziele = list(dict.fromkeys(ziele))
    for datei_id in ziele:
        svc.files().update(fileId=datei_id, body={"trashed": True}, **_ALLE_ABLAGEN).execute()
    _drive_jsons_laden.clear()  # Listen neu laden – Papierkorb-Dateien sind dort ausgeschlossen
    _drive_beleg_laden.clear()
    return len(ziele)


def _drive_dateien(svc, ordner: str) -> list[dict]:
    """Alle (nicht gelöschten) Dateien eines Ordners: [{id, name}]."""
    dateien, token = [], None
    while True:
        res = svc.files().list(q=f"'{ordner}' in parents and trashed = false", fields="nextPageToken, files(id, name)",
                               pageSize=1000, pageToken=token, **_ALLE_ABLAGEN_LISTE).execute()
        dateien += res.get("files", [])
        token = res.get("nextPageToken")
        if not token:
            return dateien


def _lokal_in_papierkorb(sha: str, beleg_pfade: list[str]) -> int:
    ordner = _lokaler_ordner()
    papierkorb = ordner / "papierkorb"
    _ordner_anlegen(papierkorb)
    anzahl = 0
    for art in EINTRAG_ARTEN:
        datei = ordner / f"{art}.jsonl"
        if not datei.exists():
            continue
        behalten, weg = [], []
        for zeile in datei.read_text(encoding="utf-8").splitlines():
            try:
                (weg if json.loads(zeile).get("datei_sha256") == sha else behalten).append(zeile)
            except json.JSONDecodeError:
                behalten.append(zeile)
        if weg:
            with (papierkorb / f"{art}.jsonl").open("a", encoding="utf-8") as f:
                f.write("".join(z + "\n" for z in weg))
            datei.write_text("".join(z + "\n" for z in behalten), encoding="utf-8")
            anzahl += len(weg)
    for pfad in beleg_pfade:
        quelle = ordner / "belege" / pfad.split("/")[-1]
        if quelle.exists():
            quelle.replace(papierkorb / quelle.name)
            anzahl += 1
    return anzahl


# Entscheidungen zu Nachfragen (erste Version, nur noch lesend): nur anhängen, nie überschreiben (Protokoll: wer hat wann was entschieden).
# Der aktuelle Status einer Nachfrage ist die jüngste Entscheidung zu ihrem Datei-Hash.

def entscheidung_speichern(eintrag: dict) -> None:
    _eintrag_speichern("entscheidungen", eintrag)


def entscheidungen_laden() -> list[dict]:
    return _eintraege_laden("entscheidungen")


# Kategorien: jede Änderung ist eine neue Version (nur anhängen). Lesbare Kopie als Google-Doc
# in "Anlage KI Assistent/<Kategorie>/" – dort, wo die Buchhaltung ihre Unterlagen bisher ablegt.

ANLAGE_ORDNER = "Anlage KI Assistent"
KATEGORIE_DOKUMENT = "Kategorie-Beschreibung (aus der App)"


def kategorie_speichern(version: dict) -> None:
    _eintrag_speichern("kategorien", version)


def kategorien_laden() -> list[dict]:
    return _eintraege_laden("kategorien")


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _drive_ordner(eltern: str, name: str) -> str:
    svc = _drive()
    q = f"'{eltern}' in parents and name = '{_q(name)}' and mimeType = '{_ORDNER_MIME}' and trashed = false"
    treffer = svc.files().list(q=q, fields="files(id)", pageSize=1, **_ALLE_ABLAGEN_LISTE).execute().get("files")
    if treffer:
        return treffer[0]["id"]
    return svc.files().create(body={"name": name, "mimeType": _ORDNER_MIME, "parents": [eltern]},
                              fields="id", **_ALLE_ABLAGEN).execute()["id"]


def kategorie_dokument_ablegen(kategorie_name: str, text: str) -> str:
    """Legt/aktualisiert das lesbare Dokument der Kategorie. Gibt einen Link bzw. Pfad zurück."""
    if _drive_config():
        from googleapiclient.http import MediaInMemoryUpload

        ordner = _drive_ordner(_drive_ordner(_drive_config()["ordner_id"], ANLAGE_ORDNER), kategorie_name)
        svc = _drive()
        q = f"'{ordner}' in parents and name = '{_q(KATEGORIE_DOKUMENT)}' and trashed = false"
        treffer = svc.files().list(q=q, fields="files(id)", pageSize=1, **_ALLE_ABLAGEN_LISTE).execute().get("files")
        inhalt = MediaInMemoryUpload(text.encode("utf-8"), mimetype="text/plain")
        if treffer:
            datei = svc.files().update(fileId=treffer[0]["id"], media_body=inhalt, fields="id, webViewLink",
                                       **_ALLE_ABLAGEN).execute()
        else:  # text/plain -> wird von Drive in ein Google-Doc umgewandelt
            datei = svc.files().create(
                body={"name": KATEGORIE_DOKUMENT, "mimeType": "application/vnd.google-apps.document",
                      "parents": [ordner]},
                media_body=inhalt, fields="id, webViewLink", **_ALLE_ABLAGEN,
            ).execute()
        return datei.get("webViewLink", "")

    ordner = _lokaler_ordner() / "kategorien"
    _ordner_anlegen(ordner)
    ziel = ordner / f"{kategorie_name}.txt"
    ziel.write_text(text, encoding="utf-8")
    _rechte_setzen(ziel)
    return str(ziel)


# Beispielbelege pro Kategorie: Unterordner von "Anlage KI Assistent" (wie bisher von der Buchhaltung gepflegt)

_BEISPIEL_MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _drive_ordner_finden(eltern: str, name: str) -> str | None:
    q = f"'{eltern}' in parents and name = '{_q(name)}' and mimeType = '{_ORDNER_MIME}' and trashed = false"
    treffer = _drive().files().list(q=q, fields="files(id)", pageSize=1, **_ALLE_ABLAGEN_LISTE).execute()
    return (treffer.get("files") or [{}])[0].get("id")


@st.cache_data(ttl=300, show_spinner=False)
def anlage_ordner() -> list[str]:
    """Namen der Unterordner von 'Anlage KI Assistent' (= Beispielordner der Kategorien)."""
    if _drive_config():
        anlage = _drive_ordner_finden(_drive_config()["ordner_id"], ANLAGE_ORDNER)
        if not anlage:
            return []
        res = _drive().files().list(q=f"'{anlage}' in parents and mimeType = '{_ORDNER_MIME}' and trashed = false",
                                    fields="files(name)", pageSize=200, **_ALLE_ABLAGEN_LISTE).execute()
        return sorted(f["name"] for f in res.get("files", []))
    basis = _lokaler_ordner() / "anlage"
    return sorted(p.name for p in basis.iterdir() if p.is_dir()) if basis.exists() else []


@st.cache_data(ttl=300, show_spinner=False)
def beispielbelege(ordner_name: str) -> list[dict]:
    """[{name, mime, ref}] aller PDFs/Bilder im Beispielordner. ref = Drive-ID bzw. lokaler Pfad."""
    if _drive_config():
        anlage = _drive_ordner_finden(_drive_config()["ordner_id"], ANLAGE_ORDNER)
        ordner = _drive_ordner_finden(anlage, ordner_name) if anlage else None
        if not ordner:
            return []
        res = _drive().files().list(q=f"'{ordner}' in parents and trashed = false",
                                    fields="files(id, name, mimeType)", orderBy="name", pageSize=500,
                                    **_ALLE_ABLAGEN_LISTE).execute()
        return [{"name": f["name"], "mime": f["mimeType"], "ref": f["id"]} for f in res.get("files", [])
                if f["mimeType"] in _BEISPIEL_MIME.values()]
    ordner = _lokaler_ordner() / "anlage" / ordner_name
    if not ordner.exists():
        return []
    return [{"name": p.name, "mime": _BEISPIEL_MIME[p.suffix.lower()], "ref": str(p)}
            for p in sorted(ordner.iterdir()) if p.suffix.lower() in _BEISPIEL_MIME]


@st.cache_data(show_spinner=False, max_entries=100)
def beispielbeleg_laden(ref: str) -> bytes:
    if _drive_config():
        return _drive().files().get_media(fileId=ref, **_ALLE_ABLAGEN).execute()
    return Path(ref).read_bytes()


def beispielbeleg_hochladen(ordner_name: str, name: str, inhalt: bytes, mime: str) -> None:
    if _drive_config():
        anlage = _drive_ordner(_drive_config()["ordner_id"], ANLAGE_ORDNER)
        _drive_hochladen(_drive_ordner(anlage, ordner_name), name, inhalt, mime)
    else:
        ordner = _lokaler_ordner() / "anlage" / ordner_name
        _ordner_anlegen(ordner.parent)
        _ordner_anlegen(ordner)
        (ordner / name).write_bytes(inhalt)
        _rechte_setzen(ordner / name)
    anlage_ordner.clear()
    beispielbelege.clear()


def beleg_laden(pfad: str) -> bytes:
    """Originaldatei zu einem gespeicherten Pfad 'belege/<name>' laden."""
    name = pfad.split("/")[-1]
    if _drive_config():
        return _drive_beleg_laden(name)
    return (_lokaler_ordner() / "belege" / name).read_bytes()


@st.cache_data(show_spinner=False, max_entries=50)
def _drive_beleg_laden(name: str) -> bytes:
    ordner = _unterordner_id("belege")
    treffer = _drive().files().list(
        q=f"'{ordner}' in parents and name = '{name}' and trashed = false",
        fields="files(id)", pageSize=1, **_ALLE_ABLAGEN_LISTE,
    ).execute().get("files", [])
    if not treffer:
        raise FileNotFoundError(f"Beleg {name} nicht im Ordner „belege“ gefunden.")
    return _drive().files().get_media(fileId=treffer[0]["id"], **_ALLE_ABLAGEN).execute()


# ---------------------------------------------------------------------------
# Google-Kalender (nur lesen) – Abgleich Beleg <-> Termin, siehe kalender.py
#
# Zwei Wege zum Kalender (der erste hat Vorrang):
# 1. In der App verbunden (Seitenleiste „Kalender verbinden“, kalender_verbindung.py): Zugang verschlüsselt in
#    kalender_zugang/ (nur anhängen, jüngster Eintrag gilt), Kalender-Auswahl dort mit abgelegt.
# 2. Secrets: [kalender].kalender_id + [kalender].refresh_token bzw. der Drive-Zugang.
# ---------------------------------------------------------------------------

def _login_client() -> tuple[str, str] | None:
    auth = _secrets_abschnitt("auth")
    return (auth["client_id"], auth["client_secret"]) if auth.get("client_id") and auth.get("client_secret") else None


def _verbindungs_geheimnis() -> str | None:
    return _secrets_abschnitt("auth").get("cookie_secret") or None


def kalender_verbinden_moeglich() -> bool:
    """Knopf „Kalender verbinden“ geht nur mit Google-Login-Client und Login-Geheimnis in den Secrets."""
    return bool(_login_client() and _verbindungs_geheimnis() and _secrets_abschnitt("auth").get("redirect_uri"))


def kalender_anmelde_url(benutzer: str | None) -> str:
    import kalender_verbindung as kv

    client_id, _ = _login_client()
    state = kv.state_erzeugen(_verbindungs_geheimnis(), benutzer)
    return kv.anmelde_url(client_id, kv.ruecksprung_url(_secrets_abschnitt("auth")["redirect_uri"]), state)


def kalender_ruecksprung(code: str, state: str, benutzer: str | None, bearbeiter: str | None) -> dict | None:
    """Rücksprung von Google verarbeiten und Zugang ablegen -> neue Verbindung (ohne Token)."""
    import kalender_verbindung as kv

    geheimnis = _verbindungs_geheimnis()
    kv.state_pruefen(geheimnis, state, benutzer)
    client_id, client_secret = _login_client()
    zugang = kv.code_einloesen(code, client_id, client_secret,
                               kv.ruecksprung_url(_secrets_abschnitt("auth")["redirect_uri"]))
    vorher = kalender_verbindung() or {}
    _eintrag_speichern("kalender_zugang", {
        "verbunden": True, "konto": zugang["konto"], "bearbeiter": bearbeiter,
        "token_verschluesselt": kv.verschluesseln(geheimnis, zugang["refresh_token"]),
        # gleiches Konto erneut verbunden -> Auswahl behalten, sonst neu wählen
        "kalender": vorher.get("kalender", []) if vorher.get("konto") == zugang["konto"] else [],
    })
    _kalender_termine.clear()
    return kalender_verbindung()


def _letzter_kalender_eintrag() -> dict | None:
    eintraege = sorted(_eintraege_laden("kalender_zugang"), key=lambda e: e.get("zeitpunkt", ""))
    return eintraege[-1] if eintraege and eintraege[-1].get("verbunden") else None


def _verbindungs_token(eintrag: dict | None) -> str | None:
    import kalender_verbindung as kv

    geheimnis = _verbindungs_geheimnis()
    if not eintrag or not geheimnis or not eintrag.get("token_verschluesselt"):
        return None
    return kv.entschluesseln(geheimnis, eintrag["token_verschluesselt"])


def kalender_verbindung() -> dict | None:
    """Aktuelle Verbindung aus der App: {"konto", "kalender": [{"id", "name"}], "zeitpunkt", "bearbeiter",
    "token_ok"} – None, wenn nie verbunden oder getrennt. Der Zugang selbst bleibt in storage."""
    e = _letzter_kalender_eintrag()
    if not e:
        return None
    return {"konto": e.get("konto"), "kalender": e.get("kalender") or [], "zeitpunkt": e.get("zeitpunkt"),
            "bearbeiter": e.get("bearbeiter"), "token_ok": _verbindungs_token(e) is not None}


def kalender_auswahl_speichern(kalender: list[dict], bearbeiter: str | None) -> None:
    """Gewählte Kalender ([{"id", "name"}]) als neuen Eintrag ablegen (Zugang bleibt derselbe)."""
    letzter = _letzter_kalender_eintrag()
    if not letzter:
        raise AblageFehler("Kein Kalender verbunden.")
    _eintrag_speichern("kalender_zugang", {
        "verbunden": True, "konto": letzter.get("konto"), "bearbeiter": bearbeiter,
        "token_verschluesselt": letzter.get("token_verschluesselt"),
        "kalender": [{"id": k["id"], "name": k.get("name") or k["id"]} for k in kalender],
    })
    _kalender_termine.clear()


def kalender_trennen(bearbeiter: str | None) -> None:
    _eintrag_speichern("kalender_zugang", {"verbunden": False, "bearbeiter": bearbeiter})
    _kalender_termine.clear()


def _calendar_service(token: str, client_id: str, client_secret: str):
    from googleapiclient.discovery import build

    creds = _drive_credentials(token, client_id, client_secret)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def kalender_liste() -> list[dict]:
    """Alle Kalender, die das verbundene Konto sehen darf: [{"id", "name", "haupt"}]."""
    token, client = _verbindungs_token(_letzter_kalender_eintrag()), _login_client()
    if not token or not client:
        raise AblageFehler("Kein gültiger Kalender-Zugang – bitte neu verbinden.")
    service = _calendar_service(token, *client)
    liste, seite = [], None
    while True:
        res = service.calendarList().list(minAccessRole="reader", pageToken=seite).execute()
        liste += [{"id": k["id"], "name": k.get("summaryOverride") or k.get("summary") or k["id"],
                   "haupt": bool(k.get("primary"))} for k in res.get("items", [])]
        seite = res.get("nextPageToken")
        if not seite:
            return sorted(liste, key=lambda k: (not k["haupt"], k["name"].lower()))


def kalender_id() -> str | None:
    return (_secrets_abschnitt("kalender").get("kalender_id") or "").strip() or None


def _kalender_zugriff() -> tuple[str, str, str, list[str], str] | None:
    """(token, client_id, client_secret, kalender_ids, quelle) – oder None, wenn nicht eingerichtet."""
    e = _letzter_kalender_eintrag()
    if e:  # in der App verbunden -> gilt allein (auch wenn noch kein Kalender gewählt ist)
        token, client = _verbindungs_token(e), _login_client()
        if token and client and e.get("kalender"):
            return token, *client, [k["id"] for k in e["kalender"]], "app"
        return None
    kid = kalender_id()
    try:
        cfg = _drive_config()
    except AblageFehler:
        cfg = None
    if not kid or not cfg:
        return None
    # Eigener Kalender-Zugang (z. B. von Annika, nur Kalender lesen) hat Vorrang vor dem Drive-Zugang
    token = _secrets_abschnitt("kalender").get("refresh_token") or cfg["refresh_token"]
    return token, cfg["client_id"], cfg["client_secret"], [kid], "secrets"


def kalender_status() -> str:
    """Kurzer Text für die Seitenleiste."""
    v = kalender_verbindung()
    if v:
        if not v["token_ok"]:
            return "Verbindung ungültig, bitte neu verbinden"
        n = len(v["kalender"])
        return f"verbunden ({n} Kalender)" if n else "verbunden, noch kein Kalender gewählt"
    return "über Secrets eingerichtet" if _kalender_zugriff() else "nicht verbunden"


@st.cache_data(ttl=300, show_spinner=False)
def _kalender_termine(kid: str, von_iso: str, bis_iso: str, token: str, client_id: str, client_secret: str):
    from datetime import datetime

    from kalender import termine_laden

    service = _calendar_service(token, client_id, client_secret)
    return termine_laden(service, kid, datetime.fromisoformat(von_iso), datetime.fromisoformat(bis_iso))


def kalender_abgleichen(analyse):
    """Beleg mit dem Firmenkalender (bzw. allen gewählten Kalendern) abgleichen -> kalender.Abgleich."""
    from googleapiclient.errors import HttpError

    from kalender import KALENDER_KATEGORIEN, Abgleich, abgleichen, zeitraum

    if analyse.kategorie not in KALENDER_KATEGORIEN:
        return Abgleich("nicht_noetig")
    zugriff = _kalender_zugriff()
    if not zugriff:
        return Abgleich("nicht_eingerichtet", "Kalenderabgleich ist noch nicht eingerichtet.")
    token, client_id, client_secret, ids, quelle = zugriff
    bereich = zeitraum(analyse)
    if bereich is None:
        return abgleichen(analyse, [])
    neu_einrichten = ("Kalender in der Seitenleiste neu verbinden." if quelle == "app" else
                      "In der Seitenleiste neben „Kalender“ auf „Verbinden“ klicken.")
    termine, gesehen = [], set()
    for kid in ids:
        try:
            gefunden = _kalender_termine(kid, bereich[0].isoformat(), bereich[1].isoformat(),
                                         token, client_id, client_secret)
        except HttpError as e:
            if e.resp.status in (401, 403):
                return Abgleich("fehler", f"kein Zugriff auf den Kalender. {neu_einrichten}")
            if e.resp.status == 404:
                return Abgleich("fehler", f"Kalender „{kid}“ nicht gefunden. "
                                          + ("Kalenderauswahl in der Seitenleiste prüfen." if quelle == "app"
                                             else "kalender_id in den Secrets prüfen."))
            return Abgleich("fehler", f"Kalender nicht erreichbar ({e.resp.status}).")
        except Exception as e:
            if "invalid_grant" in str(e):  # Zugang widerrufen oder abgelaufen
                return Abgleich("fehler", f"Kalender-Zugang ist nicht mehr gültig. {neu_einrichten}")
            return Abgleich("fehler", f"Kalender nicht erreichbar: {e}")
        for t in gefunden:  # derselbe Termin kann in mehreren Kalendern stehen
            schluessel = (t.titel, t.start, t.ende)
            if schluessel not in gesehen:
                gesehen.add(schluessel)
                termine.append(t)
    termine.sort(key=lambda t: t.start)
    return abgleichen(analyse, termine)
