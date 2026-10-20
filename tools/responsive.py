#!/usr/bin/env python3
"""Responsive audit: real browser (Playwright + system Chrome) at 15 widths, one screenshot per page and width.

Flags what tools/layout.py does not: text squeezed into a narrow column, sibling cards of unequal height or with
dead space at the bottom, text cut by an ellipsis. Read every screenshot as well: passing this is not a design review.

  python3 tools/responsive.py http://127.0.0.1:8765 ~/scratch/resp /,/models/glm-5.3-flash,/lanes
"""
import sys, json
from playwright.sync_api import sync_playwright
base, out = sys.argv[1], sys.argv[2]
paths = sys.argv[3].split(",")
WIDTHS = [320, 360, 390, 480, 560, 640, 700, 768, 820, 900, 1000, 1100, 1280, 1440, 1920]
JS = r"""() => {
  const W = document.documentElement.clientWidth, P = [];
  if (document.documentElement.scrollWidth > W + 1) P.push('page scrolls sideways ' + document.documentElement.scrollWidth);
  // squeezed text: a name/heading line box narrower than 9em that wraps to 3+ lines
  document.querySelectorAll('.who, .name, h1, h2, h3, .tile h3, .ch-h, .stamp > span, td .ent > span').forEach(e => {
    const r = e.getBoundingClientRect(); if (!r.width || !e.offsetParent) return;
    const lh = parseFloat(getComputedStyle(e).lineHeight) || parseFloat(getComputedStyle(e).fontSize) * 1.4;
    const fs = parseFloat(getComputedStyle(e).fontSize);
    if (r.height > lh * 3.2 && r.width < fs * 14) P.push('squeezed ' + (e.className || e.tagName) + ' w=' + Math.round(r.width) + ' h=' + Math.round(r.height) + ' "' + e.textContent.trim().slice(0, 30) + '"');
  });
  // sibling cards in one row with different heights or big empty bottoms
  const rows = {}; document.querySelectorAll('#answers > .tile, .stats > .stat, .chcards > .chcard').forEach(t => { const r = t.getBoundingClientRect(); (rows[Math.round(r.top)] ||= []).push(t); });
  Object.values(rows).forEach(ts => { if (ts.length < 2) return;
    const hs = ts.map(t => Math.round(t.getBoundingClientRect().height)); if (Math.max(...hs) - Math.min(...hs) > 2) P.push('unequal cards ' + hs.join('/'));
    ts.forEach(t => { const last = [...t.children].pop(); if (!last) return; const gap = t.getBoundingClientRect().bottom - last.getBoundingClientRect().bottom; if (gap > 70) P.push('dead space ' + Math.round(gap) + 'px in ' + (t.querySelector('h3, .k') || t).textContent.trim().slice(0, 24)); });
  });
  // icon alone on a line / text clipped by ellipsis
  document.querySelectorAll('.sub').forEach(e => { if (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).textOverflow === 'ellipsis') P.push('ellipsis "' + e.textContent.trim().slice(0, 30) + '"'); });
  return [...new Set(P)];
}"""
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome")
    for path in paths:
        for w in WIDTHS:
            pg = b.new_page(viewport={"width": w, "height": 900}); pg.goto(base + path, wait_until="networkidle")
            res = pg.evaluate(JS)
            name = (path.strip("/").replace("/", "_") or "home")
            pg.screenshot(path=f"{out}/r-{name}-{w}.png")
            print(path, w, "OK" if not res else res[:6])
            pg.close()
    b.close()
