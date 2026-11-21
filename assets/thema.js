// Helles/dunkles Design (eingebettet über marke.thema_einbetten).
// 1. Erkennt am Hintergrund der App, welches Design gerade gilt, und setzt <html data-thema="hell|dunkel">.
//    Daran hängen die eigenen Farben (CSS-Variablen in App.py, Logo in marke.py).
// 2. Knopf „Dunkles/Helles Design“ (.st-key-thema_wechsel): schreibt die Wahl in Streamlits eigenen Merker im
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
    const knopf = doc.querySelector(".st-key-thema_wechsel button");
    if (!knopf) return;
    const text = knopf.querySelector('[data-testid="stMarkdownContainer"] p');
    const symbol = knopf.querySelector('[data-testid="stIconMaterial"]');
    const soll = dunkel ? "Helles Design" : "Dunkles Design";
    if (text && text.textContent !== soll) text.textContent = soll;
    const sollSymbol = dunkel ? "light_mode" : "dark_mode";
    if (symbol && symbol.textContent !== sollSymbol) symbol.textContent = sollSymbol;
  }

  if (!window.__praktikantThema) {
    window.__praktikantThema = true;
    setInterval(aktualisieren, 400);
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
})();
