// Manueller Browser-Test der Einführung (nicht Teil von pytest; braucht Chrome + Node 22+).
// 1) App lokal starten:  LOGIN_DEAKTIVIERT=1 streamlit run App.py --server.address 127.0.0.1 --server.port 8503
// 2) node tests/browser/tour_durchklicken.mjs http://127.0.0.1:8503 <bild-praefix> [breite] [hoehe]
// Klickt „Einführung starten“ und alle Schritte durch; meldet je Schritt Tab, Ziel-Element, ob das Popup im
// Bild ist, und JS-Fehler. Screenshots: <bild-praefix>_<schritt>.png
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [url, praefix, breite = "1280", hoehe = "900"] = process.argv.slice(2);
const PORT = 9225;
const chrome = spawn(process.env.CHROME || "C:/Program Files/Google/Chrome/Application/chrome.exe", [
  "--headless=new", "--disable-gpu", "--no-first-run", `--user-data-dir=${mkdtempSync(join(tmpdir(), "chrome-tour-"))}`,
  `--remote-debugging-port=${PORT}`, `--window-size=${breite},${hoehe}`, "about:blank"], { stdio: "ignore" });
const warte = (ms) => new Promise((r) => setTimeout(r, ms));
try {
  let ziel;
  for (let i = 0; i < 50 && !ziel; i++) {
    try { ziel = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); }
    catch { await warte(200); }
  }
  const ws = new WebSocket(ziel.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0; const offen = new Map(); const konsole = [];
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === "Runtime.exceptionThrown") konsole.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.id && offen.has(m.id)) { offen.get(m.id)(m); offen.delete(m.id); }
  });
  const cdp = (method, params = {}) => new Promise((r) => { const n = ++id; offen.set(n, r); ws.send(JSON.stringify({ id: n, method, params })); });
  const js = async (expr) => (await cdp("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result?.result?.value;
  await cdp("Runtime.enable");
  await cdp("Page.enable");
  // Autostart beim ersten Besuch unterdrücken – sonst laufen Autostart-Tour und die per Knopf gestartete
  // übereinander, und jeder „Weiter“-Klick bedient abwechselnd eine von beiden (Schritte doppelt gezählt).
  await cdp("Page.addScriptToEvaluateOnNewDocument", { source: "try { localStorage.setItem('praktikantai_tour_gesehen', '1') } catch (e) {}" });
  await cdp("Emulation.setDeviceMetricsOverride", { width: +breite, height: +hoehe, deviceScaleFactor: 1, mobile: +breite < 700 });
  await cdp("Page.navigate", { url });
  for (let i = 0; i < 80 && !(await js("!!document.querySelector('.st-key-einfuehrung_start button')")); i++) await warte(500);
  await warte(2500);
  await js("document.querySelector('.st-key-einfuehrung_start button').click()");
  for (let i = 0; i < 80 && !(await js("!!document.querySelector('.driver-popover')")); i++) await warte(500);
  console.log('stHtml:', await js("document.querySelectorAll('[data-testid=stHtml]').length"), 'driver:', await js('!!window.driver'));
  const messen = `(() => {
    const p = document.querySelector('.driver-popover'); if (!p) return null;
    const aktiv = document.querySelector('.driver-active-element');
    const tab = document.querySelector('.stTabs [role=tab][aria-selected=true]');
    const r = aktiv && aktiv.getBoundingClientRect(); const pr = p.getBoundingClientRect();
    return {titel: p.querySelector('.driver-popover-title')?.innerText, fortschritt: p.querySelector('.tour-fortschritt')?.innerText,
      tab: tab && tab.innerText.split('\\n').pop(), element: aktiv ? (aktiv.className.toString().slice(0, 50) || aktiv.dataset.testid || aktiv.tagName) : null,
      groesse: r ? [Math.round(r.width), Math.round(r.height)] : null,
      popoverImBild: pr.top >= 0 && pr.bottom <= innerHeight && pr.left >= 0 && pr.right <= innerWidth};
  })()`;
  const protokoll = [];
  for (let schritt = 0; schritt < 20; schritt++) {
    await warte(900);
    // Tab-Wechsel mit echten Daten (z. B. Kategorien) kann länger dauern – kurz fehlendes Popup abwarten
    let m = await js(messen);
    for (let n = 0; n < 15 && !m; n++) { await warte(700); m = await js(messen); }
    if (!m) break;
    protokoll.push(m);
    if ([0, 3, 6, 8, 9].includes(schritt)) {
      const bild = await cdp("Page.captureScreenshot", { format: "png" });
      writeFileSync(`${praefix}_${schritt + 1}.png`, Buffer.from(bild.result.data, "base64"));
    }
    const weiter = await js("(() => { const b = document.querySelector('.driver-popover-next-btn'); if (!b) return false; b.click(); return true; })()");
    if (!weiter) break;
  }
  await warte(1000);
  const ende = await js("({popover: !!document.querySelector('.driver-popover'), tab: document.querySelector('.stTabs [role=tab][aria-selected=true]')?.innerText.split('\\n').pop()})");
  console.log(JSON.stringify({ protokoll, ende, fehler: konsole }, null, 1));
  ws.close();
} finally { chrome.kill(); }
