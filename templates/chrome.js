/* page chrome, inline on every page (build.py full_doc), after the page script: the top bar's More menu, the section row
   under the top bar (detail pages), and stats grids whose last row is short. Pages with common.js call window.fitTopbar
   after a view change. Nothing here reads the data. */
(() => {
  const root = document.documentElement.style;
  const bar = document.querySelector(".topbar .in");
  const nav = bar && bar.querySelector(":scope > nav");
  const more = bar && bar.querySelector(":scope > .gmore");
  const btn = more && more.querySelector(".gmore-btn");
  const menu = more && more.querySelector(".gmore-menu");
  const gap = (el) => parseFloat(getComputedStyle(el).columnGap) || 0;
  const setOpen = (open) => { btn.setAttribute("aria-expanded", String(open)); menu.hidden = !open; };

  /* links that do not fit the bar move into More; a link is never shown cut off */
  function fitNav() {
    if (!nav) return;
    const links = [...nav.children];
    more.hidden = true;
    links.forEach((a) => (a.hidden = false));
    const g = gap(nav), w = (a) => a.getBoundingClientRect().width;
    const total = links.reduce((s, a) => s + w(a), 0) + g * (links.length - 1);
    let hidden = [];
    if (total > nav.clientWidth + 0.5) {
      more.hidden = false;
      const avail = nav.clientWidth;
      let used = 0, k = 0;
      for (; k < links.length; k++) { const x = w(links[k]) + (k ? g : 0); if (used + x > avail) break; used += x; }
      links.forEach((a, i) => (a.hidden = i >= k));
      hidden = links.slice(k);
    }
    menu.replaceChildren(...hidden.map((a) => { const c = a.cloneNode(true); c.hidden = false; return c; }));
    if (!hidden.length) setOpen(false);
  }

  /* the bar's height and the section row's height set the sticky offsets and the anchor offset (style.css) */
  function syncBars() {
    const t = document.querySelector(".topbar"), s = document.querySelector(".subnav");
    if (t) root.setProperty("--topbar-h", t.offsetHeight + "px");
    root.setProperty("--subnav-h", (s ? s.offsetHeight : 0) + "px");
    if (s) s.classList.toggle("more", s.scrollWidth > s.clientWidth + 1);
  }

  /* stats grids: when the last row is short, its last cell takes the free columns, so there is no empty slot */
  function fitStats() {
    document.querySelectorAll(".stats").forEach((g) => {
      const kids = [...g.children].filter((c) => getComputedStyle(c).display !== "none");
      kids.forEach((c) => (c.style.gridColumn = ""));
      const cols = getComputedStyle(g).gridTemplateColumns.split(" ").filter(Boolean).length;
      if (!kids.length || !cols) return;
      const gg = gap(g), cw = (g.clientWidth - gg * (cols - 1)) / cols;
      const top = (c) => Math.round(c.getBoundingClientRect().top);
      const lastTop = Math.max(...kids.map(top));
      const row = kids.filter((c) => top(c) === lastTop);
      const span = (c) => Math.max(1, Math.round((c.getBoundingClientRect().width + gg) / (cw + gg)));
      const used = row.reduce((s, c) => s + span(c), 0);
      if (used < cols) row[row.length - 1].style.gridColumn = `span ${span(row[row.length - 1]) + cols - used}`;
    });
  }

  function fitTopbar() { fitNav(); syncBars(); fitStats(); }
  window.fitTopbar = fitTopbar;

  if (btn) {
    btn.addEventListener("click", () => {
      const open = btn.getAttribute("aria-expanded") !== "true";
      setOpen(open);
      if (open) { const first = menu.querySelector("a"); if (first) first.focus(); }
    });
    menu.addEventListener("keydown", (ev) => {
      const items = [...menu.querySelectorAll("a")], i = items.indexOf(document.activeElement);
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") { items[(i + (ev.key === "ArrowDown" ? 1 : items.length - 1) + items.length) % items.length].focus(); ev.preventDefault(); }
      else if (ev.key === "Escape") { setOpen(false); btn.focus(); }
      else if (ev.key === "Tab") setOpen(false);
    });
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && btn.getAttribute("aria-expanded") === "true") { setOpen(false); btn.focus(); } });
    document.addEventListener("click", (ev) => { if (!more.contains(ev.target)) setOpen(false); });
  }
  addEventListener("resize", fitTopbar);
  addEventListener("load", fitTopbar);
  if (document.fonts) document.fonts.ready.then(fitTopbar);
  fitTopbar();
})();
