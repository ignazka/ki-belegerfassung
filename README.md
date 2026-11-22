# BelegAssistent – KI-Belegerfassung

**Belege fotografieren oder hochladen – die KI ordnet sie ein, liest die Daten ab und sagt, wann ein Mensch
nachschauen muss.**

Interner Proof of Concept der RE-ALIS GmbH: ein „KI-Kollege“ für die Buchhaltung. Getestet wird, wie
zuverlässig ein Vision-Sprachmodell Belege wie Bewirtung, Tanken oder Übernachtung erkennt und ausliest.
Später sollen daraus direkt Buchungsentwürfe in **sevDesk** entstehen.

## Was die App macht

1. **Hochladen:** Foto oder PDF, auch mehrseitig oder als Stapel.
2. **Einordnen und ablesen:** Belegart, Datum, Beträge, Steuersätze, Lieferant und SKR04-Konto.
3. **Nachrechnen im Code:** MwSt., Netto und Trinkgeld rechnet der Code, nicht die KI. Passt etwas nicht
   oder ist die KI unsicher, entsteht eine **Nachfrage** an einen Menschen.
4. **Prüfen:** Ein Mensch bestätigt oder korrigiert. Jede Prüfung wird gespeichert.
5. **Lernen:** Aus den Korrekturen schlägt die App bessere Regeln für die Belegarten vor. Ein Mensch testet
   sie und übernimmt sie. Die Trefferquote zeigt, ob es besser wird.

## Wie es funktioniert

- **Modelle:** Qwen3-VL (offene Gewichte) über OpenRouter. Jeder Beleg wird doppelt gelesen, bei
  Abweichungen entscheidet ein größeres Modell. Ziel: später lokal betreiben.
- **Oberfläche:** Python + Streamlit, Login über Google, Ablage in einem Google-Drive-Ordner.
- **Belegarten** lassen sich in der App selbst anlegen und mit eigenen Regeln versehen.

## Stand

Stufe 1 als Testumgebung, im internen Einsatz. Geplant: Bewirtungsbelege vorausfüllen, Entwürfe in
sevDesk anlegen, Kontierung aus früheren Buchungen (RAG).

## Starten

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
# .env anlegen mit: OPENROUTER_API_KEY=sk-or-...  und  LOGIN_DEAKTIVIERT=1
streamlit run App.py

pip install -r requirements-dev.txt
python -m pytest       # Tests ohne API, Drive und Secrets (ca. 10 s)
```

## Mehr erfahren

- [docs/TECHNIK.md](docs/TECHNIK.md): technischer Ablauf, Dateien, Ablage, Einrichtung, Entscheidungen
- [PRUEFABLAUF.md](PRUEFABLAUF.md): wie gelesen, gerechnet und geprüft wird
- [docs/KONZEPT_PLATTFORM.md](docs/KONZEPT_PLATTFORM.md): Ausbau zur Plattform für mehrere Firmen


<img width="958" height="455" alt="Screenshot 2026-11-22 124835" src="https://github.com/user-attachments/assets/9ca5696d-b480-4d00-8538-3091caee4bdd" />
<img width="959" height="454" alt="Screenshot 2026-11-22 124857" src="https://github.com/user-attachments/assets/464ae4cc-006c-49fd-a62c-17b4d73ab21c" />
<img width="958" height="380" alt="Screenshot 2026-11-22 124911" src="https://github.com/user-attachments/assets/5b5b3384-94ee-43b8-bdef-8cb6ea7a0d06" />
<img width="950" height="128" alt="Screenshot 2026-11-22 124918" src="https://github.com/user-attachments/assets/335848ca-785f-4f76-b077-733996260e59" />
<img width="957" height="376" alt="Screenshot 2026-11-22 124925" src="https://github.com/user-attachments/assets/e61deb46-4255-401b-b354-ea3fc1ae64d5" />
<img width="958" height="455" alt="Screenshot 2026-11-22 124820" src="https://github.com/user-attachments/assets/e516a3bb-e726-40e2-b60d-71881da4d125" />
