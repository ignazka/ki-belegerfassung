"""Bild-Aufbereitung, Modell-Aufruf und robustes JSON-Parsing."""

import base64
import io
import json
import os
import re

import pymupdf
from dotenv import load_dotenv
from openai import BadRequestError, OpenAI, UnprocessableEntityError
from PIL import Image, ImageFilter, ImageOps
from pydantic import ValidationError

from beleg_schema import BelegAnalyse
from prompts import SYSTEM_PROMPT, USER_PROMPT

load_dotenv()

# Modelle (Open Weights – später lokal nutzbar)
MODEL = "qwen/qwen3-vl-30b-a3b-instruct"          # Standard: liest jeden Beleg doppelt
# Schiedsrichter bei Abweichung/Nachfrage. Cloud: großes Modell. Lokal (RTX 3090, 24 GB) passt nur eins ->
# dort SCHIEDSRICHTER_MODELL = MODEL setzen; der Schiedsrichter liest ohnehin in höherer Auflösung.
MODEL_GROSS = os.getenv("SCHIEDSRICHTER_MODELL") or "qwen/qwen3-vl-235b-a22b-instruct"
SCHIEDSRICHTER_KANTE_PX = 2800
SCHIEDSRICHTER_DPI = 220
MAX_SEITEN = 20  # Seiten/Bilder pro Beleg insgesamt (alle Dateien zusammen); mehr -> Nachfrage
MAX_KANTE_PX = 2000  # größere Fotos werden verkleinert (spart Tokens, kaum Qualitätsverlust)
MAX_KANTE_PX_VIELE_SEITEN = 1600  # ab 6 Seiten etwas kleiner, damit die Anfrage nicht zu groß wird

_client = None


def get_client():
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY fehlt in der .env-Datei.")
        _client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key, timeout=240)
    return _client


class AnalyseFehler(Exception):
    """Fehler mit angehängter Rohantwort für die Anzeige."""

    def __init__(self, message, raw=None):
        super().__init__(message)
        self.raw = raw


def _bild_normalisieren(img: Image.Image, max_kante: int = MAX_KANTE_PX) -> bytes:
    """EXIF-Drehung anwenden, nach RGB, auf max_kante verkleinern, als JPEG kodieren."""
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((max_kante, max_kante))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def seiten_zaehlen(file_bytes: bytes, mime: str) -> int:
    if mime == "application/pdf":
        with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
            return len(doc)
    return 1


def datei_zu_bildern(file_bytes: bytes, mime: str, max_seiten: int = MAX_SEITEN, max_kante: int = MAX_KANTE_PX,
                     dpi: int = 150):
    """Liefert (liste_von_jpeg_bytes, seitenanzahl_der_datei). Liest höchstens max_seiten Seiten."""
    if mime == "application/pdf":
        with pymupdf.open(stream=file_bytes, filetype="pdf") as doc:
            seiten = len(doc)
            bilder = []
            for i in range(min(seiten, max_seiten)):
                pix = doc[i].get_pixmap(dpi=dpi)
                bilder.append(_bild_normalisieren(Image.open(io.BytesIO(pix.tobytes("png"))), max_kante))
        return bilder, seiten
    return [_bild_normalisieren(Image.open(io.BytesIO(file_bytes)), max_kante)], 1


def dateien_zu_bildern(dateien: list[tuple[str, bytes, str]], hochaufloesend: bool = False):
    """Mehrere Dateien (name, bytes, mime) -> (bilder, seiten_gesamt, seiten_gelesen).

    Alle Seiten aller Dateien werden als EIN Beleg behandelt (z. B. mehrseitige Rechnung + EC-Beleg).
    """
    seiten_gesamt = sum(seiten_zaehlen(b, m) for _, b, m in dateien)
    max_kante = MAX_KANTE_PX if seiten_gesamt <= 5 else MAX_KANTE_PX_VIELE_SEITEN
    dpi = 150
    if hochaufloesend:  # für den Schiedsrichter: kleine Schrift besser lesbar
        max_kante, dpi = (SCHIEDSRICHTER_KANTE_PX if seiten_gesamt <= 5 else MAX_KANTE_PX), SCHIEDSRICHTER_DPI
    bilder = []
    for _, b, m in dateien:
        rest = MAX_SEITEN - len(bilder)
        if rest <= 0:
            break
        neue, _ = datei_zu_bildern(b, m, max_seiten=rest, max_kante=max_kante, dpi=dpi)
        bilder += neue
    return bilder, seiten_gesamt, len(bilder)


def _json_extrahieren(raw: str) -> dict:
    """Erst direkt parsen, dann Codeblock, dann erstes {...}-Objekt."""
    text = raw.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if block:
        try:
            return json.loads(block.group(1))
        except json.JSONDecodeError:
            pass
    start, ende = text.find("{"), text.rfind("}")
    if start != -1 and ende > start:
        return json.loads(text[start:ende + 1])
    raise json.JSONDecodeError("Kein JSON-Objekt gefunden", text, 0)


def kontrast_variante(jpeg: bytes) -> bytes:
    """Zweite Bildversion fürs Doppelt-Lesen: Graustufen + Autokontrast + leicht geschärft.
    Andere Pixel -> Lesefehler der beiden Durchläufe sind unabhängiger als bei identischem Bild."""
    img = Image.open(io.BytesIO(jpeg)).convert("L")
    img = ImageOps.autocontrast(img, cutoff=1).filter(ImageFilter.SHARPEN)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _modell_aufrufen(content, modell: str, system: str = SYSTEM_PROMPT):
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": content},
    ]
    kwargs = dict(
        model=modell,
        messages=messages,
        temperature=0.1,
        max_tokens=1500,
        # Keine Anbieter, die Daten speichern/zum Training nutzen (Belege enthalten Kartendaten)
        extra_body={"provider": {"data_collection": "deny"}},
    )
    client = get_client()
    try:
        return client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except (BadRequestError, UnprocessableEntityError):
        # Nur wenn der Anbieter die Anfrage ablehnt (z. B. json_object nicht unterstützt): ohne Vorgabe erneut.
        # Zeitüberschreitung/Netz/Überlastung nicht – die wiederholt der Client schon selbst (max_retries),
        # ein zweiter Durchlauf würde die Wartezeit nur verdoppeln.
        return client.chat.completions.create(**kwargs)


def analysieren(bilder: list[bytes], modell: str = MODEL, system: str = SYSTEM_PROMPT):
    """Ruft das Modell auf. Gibt (BelegAnalyse, rohantwort, usage_dict) zurück."""
    hinweis = (
        f"Der Beleg besteht aus {len(bilder)} Bildern/Seiten in Reihenfolge. Sie gehören ALLE zu EINEM Vorgang "
        "(z. B. mehrseitige Rechnung, Rechnung + EC-Beleg). Werte über alle Seiten hinweg ablesen; "
        "Gesamtbetrag und MwSt.-Aufstellung stehen oft auf der letzten Rechnungsseite. "
        if len(bilder) > 1 else ""
    )
    content = [{"type": "text", "text": hinweis + USER_PROMPT}]
    for b in bilder:
        b64 = base64.b64encode(b).decode("utf-8")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    response = _modell_aufrufen(content, modell, system)
    raw = (response.choices[0].message.content or "").strip()
    try:
        daten = _json_extrahieren(raw)
        analyse = BelegAnalyse.model_validate(daten)
    except (json.JSONDecodeError, ValidationError) as e:
        raise AnalyseFehler(f"Antwort des Modells konnte nicht gelesen werden: {e}", raw) from e

    usage = response.usage.model_dump() if response.usage else {}
    return analyse, raw, usage


def text_anfrage_json(system: str, nachricht: str, modell: str = MODEL_GROSS) -> dict:
    """Reine Textanfrage (ohne Bild) mit JSON-Antwort – z. B. für den Kategorie-Assistenten."""
    response = _modell_aufrufen(nachricht, modell, system)
    raw = (response.choices[0].message.content or "").strip()
    try:
        return _json_extrahieren(raw)
    except json.JSONDecodeError as e:
        raise AnalyseFehler(f"Antwort des Assistenten konnte nicht gelesen werden: {e}", raw) from e
