// Interaktive Einführung („Tour“) für den BelegAssistent – läuft im Browser mit driver.js.
// Jeder Schritt: tab (Nummer des Tabs, der dafür offen sein muss), ziel (Funktion -> Element oder null = Popup in der
// Mitte), titel, text. Die Tour wechselt die Tabs selbst. Texte bewusst ohne Fachsprache.
(function () {
  const $ = (sel) => document.querySelector(sel);
  // sichtbar = im Layout und horizontal im Bild (die zugeklappte Seitenleiste am Handy liegt außerhalb)
  const sichtbar = (el) => {
    if (!el || el.offsetParent === null) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 24 && r.height > 0 && r.left >= 0 && r.right <= innerWidth;
  };
  const ersterSichtbarer = (sel) => [...document.querySelectorAll(sel)].find(sichtbar) || null;
  const knopfMitText = (text) =>
    [...document.querySelectorAll("button")].find((b) => sichtbar(b) && b.innerText.trim().includes(text)) || null;

  const SCHRITTE = [
    { tab: 0, ziel: null, titel: "Willkommen beim BelegAssistent",
      text: "Diese kurze Einführung zeigt dir die wichtigsten Stellen der App. Mit „Weiter“ geht es voran, " +
            "mit Esc oder dem × kannst du jederzeit abbrechen." },
    { tab: 0, ziel: () => $('.stTabs [role="tablist"]'), titel: "Vier Bereiche",
      text: "Der Ablauf von links nach rechts: <b>Belege hochladen</b> → <b>Belege</b> prüfen → " +
            "<b>Kategorien</b> pflegen → <b>Auswertung</b> ansehen. Hier oben wechselst du zwischen den Bereichen." },
    { tab: 0, ziel: () => ersterSichtbarer('[data-testid="stFileUploader"]'), titel: "Belege hochladen",
      text: "Fotos oder PDFs hierher ziehen oder auswählen. Bei mehreren Dateien fragt die App, ob jede Datei ein " +
            "eigener Beleg ist oder ob alle zusammen <i>einen</i> Beleg bilden (z. B. Rechnung + EC-Beleg). " +
            "Danach auf „Analysieren“: Die KI liest jeden Beleg zweimal, der Code rechnet alle Beträge nach." },
    { tab: 1, ziel: () => ersterSichtbarer(".st-key-belege_filter"), titel: "Alle Belege an einer Stelle",
      text: "Jeder analysierte Beleg landet hier. <b>Nachfragen offen</b>: Die KI war unsicher und braucht dich. " +
            "<b>Ungeprüft</b>: Die KI war sicher, aber noch niemand hat draufgeschaut – zur Kontrolle. " +
            "Die farbige Zahl zeigt, wie viele es sind. " +
            "Darüber kannst du nach Name, Ort oder Nummer suchen und nach Belegart oder Belegdatum filtern." },
    { tab: 1, ziel: () => ersterSichtbarer(".st-key-beleg_blaettern"), titel: "Durchblättern",
      text: "Mit „Vorheriger“ und „Nächster“ gehst du die Liste Beleg für Beleg durch. Darüber kannst du einen " +
            "Beleg auch gezielt auswählen." },
    { tab: 1, ziel: () => ersterSichtbarer(".st-key-belegspalte_belege"), titel: "Das Original",
      text: "Links siehst du den Beleg groß neben dem Formular – so kannst du jedes Feld direkt vergleichen. " +
            "Bei mehreren Seiten blätterst du unten mit ‹ › oder klickst auf eine der kleinen Vorschauen." },
    { tab: 1,
      ziel: () => { const s = ersterSichtbarer(".st-key-belegspalte_belege");
                    const zeile = s && s.closest('[data-testid="stHorizontalBlock"]');
                    return zeile ? zeile.children[1] : null; },
      titel: "Prüfen und korrigieren",
      text: "Stimmt die Belegart? Dann „Ja“, sonst die richtige auswählen. Falsch gelesene Werte einfach " +
            "überschreiben und kurz begründen – aus diesen Begründungen lernt die KI. Dazu gehört auch das " +
            "Konto (SKR04): Stimmt es nicht, die richtige Nummer eintragen. Auch schon geprüfte Belege " +
            "lassen sich jederzeit über „Korrigieren“ ändern." },
    { tab: 2, ziel: () => ersterSichtbarer(".st-key-kategorie_wahl"), titel: "Belegarten",
      text: "Hier legt ihr fest, welche Belegarten die KI kennt und woran sie sie erkennt. Oben eine Kategorie " +
            "auswählen, daneben über „Neue Kategorie“ eine neue anlegen. Beschreibt sie so, wie ihr es einem neuen " +
            "Kollegen erklären würdet." },
    { tab: 2, ziel: () => ersterSichtbarer(".st-key-kategorie_konto"), titel: "Konto für sevDesk",
      text: "Jede Kategorie bekommt ein SKR04-Konto, damit sevDesk den Beleg später richtig bucht. In der Liste " +
            "nach Nummer oder Stichwort suchen – das füllt Nummer und Bezeichnung aus. Beides lässt sich ändern " +
            "oder ganz selbst eintragen, denn der Kontenrahmen ist viel größer als die Vorlage." },
    { tab: 2, ziel: () => ersterSichtbarer(".st-key-kategorie_konto_ausnahmen"), titel: "Ausnahmen beim Konto",
      text: "Gehören manche Belege dieser Kategorie auf ein anderes Konto, tragt hier eine Zeile ein, z. B. " +
            "„Wenn nur ein Gedeck → 6664“. Die KI wählt dann je Beleg zwischen Standardkonto und Ausnahmen und " +
            "fragt im Zweifel nach. Wichtig: Die Bedingung muss <b>auf dem Beleg zu sehen</b> sein – sonst bleibt " +
            "es beim Standardkonto und ihr korrigiert es bei der Prüfung." },
    { tab: 2, ziel: () => knopfMitText("Testen"), titel: "Erst testen, dann speichern",
      text: "Der Probelauf liest Beispielbelege einmal mit der alten und einmal mit der neuen Beschreibung. So " +
            "siehst du <i>vor</i> dem Speichern, ob deine Änderung die Erkennung verbessert – auch, welches " +
            "Konto jeder Beleg bekommt. So prüft ihr neue Konto-Ausnahmen an echten Belegen. Die Beispielbelege " +
            "liegen in Google Drive im Ordner „Anlage KI Assistent“ – je Ausnahme ein paar passende dazulegen." },
    { tab: 3,
      ziel: () => { const m = ersterSichtbarer('[data-testid="stMetric"]');
                    return m ? m.closest('[data-testid="stHorizontalBlock"]') : null; },
      titel: "Wie gut ist die KI?",
      text: "Die Auswertung zählt alle geprüften Belege: Wie oft war die Belegart richtig, wie oft alle Werte, " +
            "wie viele Nachfragen waren unnötig. So seht ihr, ob Änderungen wirklich helfen." },
    { tab: 3, ziel: () => knopfMitText("Verbesserungsvorschläge"), titel: "Aus Korrekturen lernen",
      text: "Sind genug Korrekturen gesammelt, sucht die KI hier nach Mustern und schlägt Ergänzungen für die " +
            "Kategorien vor. Übernommen wird nur, was ihr prüft und speichert." },
    { tab: 0, ziel: () => ersterSichtbarer(".st-key-einfuehrung_start"), titel: "Jederzeit wiederholen",
      text: "Über „Einführung starten“ in der Seitenleiste (am Handy: Menü oben links) startest du die " +
            "Einführung jederzeit erneut. Oben rechts neben dem Menü (drei Punkte) wechselst du mit dem Mond-/Sonnen-Symbol zwischen hellem und dunklem Design. Viel Erfolg!" },
  ];

  // Tabs sind react-aria-Elemente: ein einfaches .click() reicht nicht, es braucht Zeiger-Ereignisse.
  // Tabs über ihre Position wählen (0 = Belege hochladen, 1 = Belege, 2 = Kategorien, 3 = Auswertung) –
  // die Namen ändern sich (Zahl offener Nachfragen) und „Belege“ steckt auch in „Belege hochladen“.
  function tabOeffnen(nr) {
    const tab = document.querySelectorAll('.stTabs [role="tab"]')[nr];
    if (!tab || tab.getAttribute("aria-selected") === "true") return false;
    const opt = { bubbles: true, cancelable: true, pointerId: 1, pointerType: "mouse", isPrimary: true, button: 0 };
    tab.dispatchEvent(new PointerEvent("pointerdown", opt));
    tab.dispatchEvent(new MouseEvent("mousedown", opt));
    tab.dispatchEvent(new PointerEvent("pointerup", opt));
    tab.dispatchEvent(new MouseEvent("mouseup", opt));
    tab.dispatchEvent(new MouseEvent("click", opt));
    return true;
  }

  // Schritte selbst verwalten und je Schritt highlight() aufrufen: Das Ziel wird erst bestimmt, wenn der
  // passende Tab offen ist (Inhalte anderer Tabs sind unsichtbar). Fehlt ein Element (z. B. noch keine
  // Belege), steht das Popup einfach in der Mitte.
  function starten() {
    let navigiert = false;  // true, solange die Tour selbst umschaltet (dann nicht als „beendet“ werten)
    const n = SCHRITTE.length;
    const tour = window.driver.js.driver({
      overlayOpacity: 0.55,
      stagePadding: 8,
      stageRadius: 10,
      popoverClass: "praktikant-tour",
      smoothScroll: true,
      onDestroyed: () => { if (!navigiert) tabOeffnen(0); },
    });
    function zeige(i) {
      const s = SCHRITTE[i];
      navigiert = true;
      tour.highlight({
        element: (s.ziel && s.ziel()) || undefined,
        popover: {
          title: s.titel,
          description: s.text + `<div class="tour-fortschritt">${i + 1} von ${n}</div>`,
          showButtons: i === 0 ? ["next", "close"] : ["next", "previous", "close"],
          nextBtnText: i === n - 1 ? "Fertig" : "Weiter",
          prevBtnText: "Zurück",
          onNextClick: () => gehe(i + 1),
          onPrevClick: () => gehe(i - 1),
          onCloseClick: () => tour.destroy(),
        },
      });
      navigiert = false;
    }
    function gehe(i) {
      if (i >= n) { tour.destroy(); return; }
      if (i < 0) return;
      const gewechselt = tabOeffnen(SCHRITTE[i].tab);
      setTimeout(() => zeige(i), gewechselt ? 400 : 0);  // Tab-Inhalt erst zeichnen lassen
    }
    window.__praktikantTour = tour;
    gehe(0);
  }

  // Automatischer Start nur beim allerersten Öffnen in diesem Browser (Merker im localStorage);
  // über den Knopf startet die Tour immer. TOUR_AUTO setzt einfuehrung.py davor.
  const MERKER = "praktikantai_tour_gesehen";
  let gesehen = false;
  try { gesehen = !!localStorage.getItem(MERKER); } catch (e) { /* privates Fenster o. ä. */ }
  if (window.TOUR_AUTO && gesehen) return;

  const auto = !!window.TOUR_AUTO;  // jetzt merken – das nächste Skript setzt den Wert ggf. um
  const laeuft = () => !!(window.__praktikantTour && window.__praktikantTour.isActive());
  function laden() {
    // Autostart unterbricht nie eine laufende Tour und startet nicht, wenn inzwischen eine lief
    if (auto) {
      let schonGesehen = false;
      try { schonGesehen = !!localStorage.getItem(MERKER); } catch (e) { /* egal */ }
      if (laeuft() || schonGesehen) return;
    }
    try { localStorage.setItem(MERKER, new Date().toISOString()); } catch (e) { /* egal */ }
    if (laeuft()) window.__praktikantTour.destroy();
    if (window.driver && window.driver.js) { starten(); return; }
    const s = document.createElement("script");
    s.src = "https://cdn.jsdelivr.net/npm/driver.js@1.3.1/dist/driver.js.iife.js";
    s.onload = starten;
    document.head.appendChild(s);
  }
  // Warten, bis die Tabs gezeichnet sind und die App nicht mehr rechnet (erstes Laden holt die Daten aus
  // Drive und kann dauern). Höchstens 2 Minuten, danach beim nächsten Öffnen erneut versuchen.
  const bereit = () => document.querySelectorAll('.stTabs [role="tab"]').length >= 4 &&
    !document.querySelector('[data-testid="stStatusWidget"] [data-testid="stStatusWidgetRunningIcon"], .stStatusWidget-running');
  let versuche = 0;
  (function warten() {
    if (bereit()) setTimeout(laden, 800);
    else if (versuche++ < 480) setTimeout(warten, 250);
  })();
})();
