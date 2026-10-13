// Prerender freetokens pages without a browser (ADR-026): run each page's own JavaScript in happy-dom and keep the rendered HTML.
// happy-dom runs every classic <script> in its own function scope, so a page's scripts (data.js, the inline boot, common.js,
// the page script) would not see each other's top-level names. We hold them, run them once as one script in page order,
// then restore the original <script> tags, so the written page is the page we built plus its rendered content.
import { Window } from "happy-dom";
import { readFileSync, writeFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
// usage: node tools/prerender.mjs DIST   (called by build.py --dist; overwrites the pages in DIST)
const [dist, outDir] = process.argv.slice(2);
const SITE = "https://freetokens.fyi";
const walk = (d) => readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : [p]; });
const pages = walk(dist).filter((p) => p.endsWith(".html") && !/(^|\/)(404|methodology)\.html$/.test(relative(dist, p)));
const HOLD = "text/x-ft-hold";
let n = 0; const t0 = Date.now();
for (const p of pages) {
  const src = readFileSync(p, "utf8");
  const rel = relative(dist, p).replace(/\.html$/, "").replace(/^index$/, "");
  const window = new Window({ url: `${SITE}/${rel}`, width: 1280, height: 900, settings: {
    enableJavaScriptEvaluation: true, suppressInsecureJavaScriptEnvironmentWarning: true,
    disableCSSFileLoading: true, disableJavaScriptFileLoading: true, handleDisabledFileLoadingAsSuccess: true } });
  Object.defineProperty(window.navigator, "webdriver", { get: () => true });  // pages skip analytics and the count request
  // classic scripts (no type) are held; JSON-LD and other typed scripts are left alone
  window.document.write(src.replace(/<script(?![^>]*\btype=)/g, `<script type="${HOLD}"`));
  const held = [...window.document.querySelectorAll(`script[type="${HOLD}"]`)];
  const code = held.map((s) => { const u = s.getAttribute("src");
    return u ? (u.startsWith("/") ? readFileSync(join(dist, u.split("?")[0]), "utf8") : "") : s.textContent; }).join("\n;\n");
  const run = window.document.createElement("script"); run.textContent = code; window.document.body.appendChild(run);
  await window.happyDOM.waitUntilComplete();
  run.remove();
  for (const s of held) s.removeAttribute("type");
  const errors = window.happyDOM.virtualConsolePrinter.readAsString().split("\n").filter((l) => /^\w*Error/.test(l));
  const html = "<!doctype html>\n" + window.document.documentElement.outerHTML + "\n";
  await window.happyDOM.close();
  if (errors.length || !/class="wrap[ "]/.test(html)) { console.error(`✗ prerender failed for ${p}: ${errors[0] || "no content"}`); process.exit(1); }
  writeFileSync(outDir ? join(outDir, relative(dist, p).replaceAll("/", "__")) : p, html); n++;
}
console.log(`✓ prerendered ${n} pages with happy-dom in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
