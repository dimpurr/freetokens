#!/usr/bin/env python3
"""Layout check for the built site: real browser (Playwright + system Chrome), four widths.

Fails on: sideways page scroll, images wider than their column, empty headings / bylines / captions,
leftover template slots (__X__). Run against a local dist before deploy, or the live site after.

  python3 tools/layout.py http://127.0.0.1:8765            # check (exit 1 on problems)
  python3 tools/layout.py https://freetokens.fyi --shots ~/scratch/shots   # also save full-page screenshots
  python3 tools/layout.py <base> --pages /blog /zh/blog --dark
  python3 tools/layout.py --dist dist                       # serve a built dist on a free local port (deploy.sh gate)

Pages default to every blog page in the sitemap-free set below plus the home page.
"""
import argparse
import json
import sys
from pathlib import Path

WIDTHS = (360, 390, 768, 1440)
PAGES = ("/", "/blog", "/zh/blog", "/blog/space-bunny-alpha", "/zh/blog/space-bunny-alpha", "/about", "/methodology")

PROBE = r"""() => {
  const W = document.documentElement.clientWidth, out = [];
  if (document.documentElement.scrollWidth > W + 1) {
    const wide = [...document.querySelectorAll('body *')].filter(e => {
      const r = e.getBoundingClientRect(); if (r.right <= W + 1) return false;
      for (let p = e.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return false; }
      return true; });
    out.push('page scrolls sideways (' + document.documentElement.scrollWidth + 'px > ' + W + 'px): ' +
             wide.slice(0, 3).map(e => e.tagName.toLowerCase() + (e.className ? '.' + String(e.className).split(' ')[0] : '')).join(', '));
  }
  document.querySelectorAll('img').forEach(i => { const c = i.closest('figure, .article, .wrap') || document.body;
    if (i.getBoundingClientRect().width > c.getBoundingClientRect().width + 1) out.push('image wider than its column: ' + i.getAttribute('src')); });
  document.querySelectorAll('h1, h2, h3, figcaption, .byline, .standfirst').forEach(e => {
    if (!e.textContent.replace(/[\s·]/g, '')) out.push('empty ' + e.tagName.toLowerCase() + (e.className ? '.' + e.className : '') + (e.id ? '#' + e.id : '')); });
  const slot = document.body.innerHTML.match(/__[A-Z_]{3,}__/); if (slot) out.push('template slot left: ' + slot[0]);
  return out;
}"""


def serve(root):
    """Background static server for a dist: /x serves x.html, as nginx does. Returns its base URL."""
    import http.server, os, threading

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(root), **k)

        def translate_path(self, path):
            p = super().translate_path(path)
            if not os.path.isfile(p) and os.path.isfile(p.rstrip("/") + ".html"):
                return p.rstrip("/") + ".html"
            return p

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("base", nargs="?")
    ap.add_argument("--dist", help="serve this built directory locally (extensionless URLs like nginx) and check it")
    ap.add_argument("--pages", nargs="*", default=list(PAGES))
    ap.add_argument("--shots", help="directory for full-page screenshots")
    ap.add_argument("--dark", action="store_true", help="also check dark mode")
    a = ap.parse_args(argv)
    if a.dist:
        a.base = serve(Path(a.dist))
        if a.pages == list(PAGES):  # every published article, both languages, not just the ones named above
            for f in sorted(Path(a.dist).glob("blog/*.html")) + sorted(Path(a.dist).glob("zh/blog/*.html")):
                u = "/" + str(f.relative_to(a.dist))[:-5]
                if u not in a.pages:
                    a.pages.append(u)
    if not a.base:
        ap.error("give a base URL or --dist")
    from playwright.sync_api import sync_playwright
    problems = []
    shots = Path(a.shots).expanduser() if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome")
        for scheme in (("light", "dark") if a.dark else ("light",)):
            for w in WIDTHS:
                ctx = b.new_context(viewport={"width": w, "height": 900}, color_scheme=scheme)
                for path in a.pages:
                    pg = ctx.new_page()
                    r = pg.goto(a.base.rstrip("/") + path, wait_until="networkidle")
                    if not r or r.status != 200:
                        problems.append(f"{path} @{w}: HTTP {r.status if r else 'none'}")
                        pg.close(); continue
                    pg.evaluate("document.querySelectorAll('img[loading=lazy]').forEach(i => i.loading = 'eager')")
                    pg.wait_for_load_state("networkidle")
                    problems += [f"{path} @{w}{' dark' if scheme == 'dark' else ''}: {x}" for x in pg.evaluate(PROBE)]
                    if shots:
                        name = (path.strip("/").replace("/", "_") or "home") + f"-{w}" + ("-dark" if scheme == "dark" else "") + ".png"
                        pg.screenshot(path=str(shots / name), full_page=True)
                    pg.close()
                ctx.close()
        b.close()
    print(json.dumps({"problems": problems}, ensure_ascii=False, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
