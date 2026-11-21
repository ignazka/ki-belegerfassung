// Helles/dunkles Design (eingebettet über marke.thema_einbetten).
// 1. Erkennt am Hintergrund der App, welches Design gerade gilt, und setzt <html data-thema="hell|dunkel">.
//    Daran hängen die eigenen Farben (CSS-Variablen in App.py, Logo in marke.py).
// 2. Knopf mit Mond/Sonne (.st-key-thema_wechsel, oben rechts neben dem Menü): schreibt die Wahl in Streamlits eigenen Merker im
//    localStorage (derselbe wie im Einstellungsmenü, Streamlit 1.67) und lädt die Seite neu – Streamlit liest
//    das Design nur beim Laden. Der Klick erreicht Streamlit nicht (kein unnötiger Server-Durchlauf).
(function () {
  const doc = window.document;
  const MERKER = "stActiveTheme-" + window.location.pathname + "-v2";

  function istDunkel() {
    const app = doc.querySelector(".stApp") || doc.body;
    const m = (getComputedStyle(app).backgroundColor || "").match(/[\d.]+/g);
    if (!m || m.length < 3) return false;
    const [r, g, b] = m.map(Number);
    return 0.299 * r + 0.587 * g + 0.114 * b < 128;
  }

  function aktualisieren() {
    const dunkel = istDunkel();
    const wert = dunkel ? "dunkel" : "hell";
    if (doc.documentElement.dataset.thema !== wert) doc.documentElement.dataset.thema = wert;
    // Streamlit zeichnet den Knopf auf Touch-Geräten zweimal (mit/ohne Tooltip, einer unsichtbar) -> alle
    const soll = dunkel ? "Helles Design" : "Dunkles Design";  // Knopf hat keinen Text -> für Screenreader
    const sollSymbol = dunkel ? "light_mode" : "dark_mode";
    for (const knopf of doc.querySelectorAll(".st-key-thema_wechsel button")) {
      if (knopf.getAttribute("aria-label") !== soll) knopf.setAttribute("aria-label", soll);
      const symbol = knopf.querySelector('[data-testid="stIconMaterial"]');
      if (symbol && symbol.textContent !== sollSymbol) symbol.textContent = sollSymbol;
    }
  }

  // Knopf links neben die Symbole der Kopfleiste setzen (Ladeanzeige, falls sichtbar, sonst Menü mit drei
  // Punkten) und senkrecht mittig zum Menü. Die Ladeanzeige erscheint und verschwindet -> laufend nachführen.
  function ausrichten() {
    const huelle = doc.querySelector(".st-key-thema_wechsel");
    const knopf = huelle && [...huelle.querySelectorAll("button")].find((b) => b.getBoundingClientRect().height);
    const menue = doc.querySelector('[data-testid="stMainMenu"]');
    if (!knopf || !menue) return;
    const m = menue.getBoundingClientRect();
    if (!m.width) return;
    let links = m.left;
    // nur Ladeanzeige (samt „Stop“) und Aktionen rechts – nicht z. B. den Seitenleisten-Pfeil links
    const auswahl = '[data-testid="stStatusWidget"], [data-testid="stStatusWidget"] *, [data-testid="stToolbarActions"] *';
    for (const e of doc.querySelectorAll(auswahl)) {
      if (e === menue || menue.contains(e) || huelle.contains(e)) continue;
      const r = e.getBoundingClientRect();
      if (r.width && r.height && r.right <= m.left + 1 && r.left < links) links = r.left;
    }
    const k = knopf.getBoundingClientRect();
    const rechts = Math.round(window.innerWidth - links + 4) + "px";
    const oben = Math.round(m.top + m.height / 2 - k.height / 2) + "px";
    if (huelle.style.right !== rechts) huelle.style.right = rechts;
    if (huelle.style.top !== oben) huelle.style.top = oben;
    if (huelle.style.visibility !== "visible") huelle.style.visibility = "visible";
  }

  if (!window.__praktikantThema) {
    window.__praktikantThema = true;
    setInterval(aktualisieren, 400);
    setInterval(ausrichten, 100);
    doc.addEventListener("click", function (e) {
      if (!e.target.closest || !e.target.closest(".st-key-thema_wechsel button")) return;
      e.preventDefault();
      e.stopPropagation();
      try {
        window.localStorage.setItem(MERKER, JSON.stringify(istDunkel() ? "Light" : "Dark"));
      } catch (fehler) { /* localStorage gesperrt: dann bleibt das Design */ }
      window.location.reload();
    }, true);
  }
  aktualisieren();
  ausrichten();
})();
