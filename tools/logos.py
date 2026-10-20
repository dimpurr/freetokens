#!/usr/bin/env python3
"""Find a logo for every maker, channel and program provider; write templates/logos/ + templates/logos/index.json.

Sources, best first (the first hit wins; an entry already in index.json is kept unless --refresh):
  1. LobeHub icons   (@lobehub/icons-static-svg, MIT)   AI makers and platforms; colour mark if it reads on white, else mono
  2. Simple Icons    (simple-icons, CC0)                 3k+ brands (Xiaomi, Xiaohongshu, OVH, Hetzner …); mono
  3. The Hugging Face organisation avatar, when the maker links to huggingface.co/<org> (most open-weight labs do)
  4. The official site's own icon (SVG icon or apple-touch-icon from the maker / channel link), saved with its URL
Anything still missing is listed at the end; the page then draws a generated tile (common.js logo()), never a blank.

  python3 tools/logos.py                 # fill gaps (downloads the two icon packages once into ~/.cache/freetokens-logos)
  python3 tools/logos.py --refresh KEY   # look one key up again
  python3 tools/logos.py --report        # list keys and their source, write nothing

Aliases for names no library spells the same way live in ALIASES below (e.g. Dots Studio is Xiaohongshu's lab).
"""
import argparse, json, re, subprocess, sys, tarfile, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "templates" / "logos"
INDEX = OUT / "index.json"
CACHE = Path.home() / ".cache" / "freetokens-logos"
PKGS = {"lobehub": "@lobehub/icons-static-svg", "simple": "simple-icons"}

# key (maker id or slug of a channel / provider name) -> library names to try, in order
ALIASES = {
    "google": ["google"], "google-ai-studio": ["aistudio", "googlegemini"], "zai": ["zai"], "zhipu-bigmodel": ["zhipu"],
    "xiaomi": ["xiaomi"], "moonshot": ["kimi", "moonshot"], "moonshot-ai": ["kimi", "moonshot"], "meituan": ["longcat", "meituan"],
    "tencent": ["hunyuan", "tencent"], "inclusionai": ["ling", "antgroup"], "ant-ling": ["ling", "antgroup"],
    "dots-studio": ["xiaohongshu"], "opencode-zen": ["opencode"], "opencode-go": ["opencode"], "kilo-code": ["kilocode"],
    "siliconflow": ["siliconcloud"], "nvidia-build": ["nvidia"], "cloudflare-workers-ai": ["workersai", "cloudflare"],
    "vercel-ai-gateway": ["vercel"], "ovhcloud-ai-endpoints": ["ovh"], "hetzner-experiments": ["hetzner"],
    "huawei-cloud": ["huawei"], "aws": ["aws", "bedrock"], "alibaba": ["alibabacloud", "alibaba"], "alibaba-cloud": ["alibabacloud", "alibaba"],
    "qwencloud": ["qwen"], "bytedance": ["bytedance", "doubao"], "volcengine": ["volcengine"], "cursor": ["cursor"],
    "buddy-ai": ["codebuddy", "tencent"], "iflow": ["iflow"], "zed-industries": ["zed"], "hugging-face": ["huggingface"],
    "fireworks-ai": ["fireworks"], "novita-ai": ["novita"], "github": ["github", "githubcopilot"], "jetbrains": ["jetbrains"],
    "gitee": ["gitee"], "nebius": ["nebius"], "cerebras": ["cerebras"], "puter": ["puter"],
}
# official sites for entities our data links only to a model hub (or not at all)
SITES = {"reflection": "https://reflection.ai", "iflow": "https://iflow.cn"}
# library colour marks that are not the brand's own: use the mono mark
PREFER_MONO = {"openrouter"}
# CJK-only provider names -> key
CJK = {"腾讯云": "tencent", "阿里云": "alibaba-cloud", "千问ai平台": "qwencloud"}


def slug(s):
    s = re.sub(r"\s*\(.*\)$", "", s).strip()
    return CJK.get(s.lower(), re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-"))


def fetch_pkg(name):
    d = CACHE / name
    if not d.exists():
        d.mkdir(parents=True)
        tgz = subprocess.run(["npm", "pack", PKGS[name], "--silent", "--pack-destination", str(CACHE)], capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
        with tarfile.open(CACHE / tgz) as t:
            t.extractall(d, filter="data")
    return d / "package" / "icons"


def white_on_white(svg):
    """A colour mark drawn partly in white disappears on our white tile: use the mono version instead."""
    return bool(re.search(r'fill="(#fff|#ffffff|white)"', svg, re.I))


def from_libs(cands, lob, sim):
    for c in cands:
        c = c.replace("-", "")
        p = lob / f"{c}-color.svg"
        if p.exists() and c not in PREFER_MONO and not white_on_white(p.read_text()):
            return p, "lobehub", False
        if (lob / f"{c}.svg").exists():
            return lob / f"{c}.svg", "lobehub", True
        if (sim / f"{c}.svg").exists():
            return sim / f"{c}.svg", "simple-icons", True
    return None


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (freetokens logo finder)"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read(2_000_000)
    return data if binary else data.decode("utf-8", "replace")


def from_site(url):
    """The site's own icon: an SVG icon if offered, else the largest apple-touch-icon / PNG icon (≥ 64 px)."""
    try:
        page = get(url)
    except Exception:
        return None
    links = re.findall(r"<link\b[^>]*>", page, re.I)
    found = []
    for l in links:
        rel = re.search(r'rel="([^"]*)"', l, re.I); href = re.search(r'href="([^"]+)"', l, re.I)
        if not rel or not href or "icon" not in rel.group(1).lower():
            continue
        h = urllib.parse.urljoin(url, href.group(1)); sz = re.search(r'sizes="(\d+)', l)
        kind = "svg" if h.split("?")[0].endswith(".svg") or "svg" in l.lower() else "png"
        found.append((kind == "svg", int(sz.group(1)) if sz else (180 if "apple" in rel.group(1).lower() else 32), h, kind))
    for is_svg, size, h, kind in sorted(found, reverse=True):
        if not is_svg and size < 64:
            continue
        try:
            return get(h, binary=True), kind, h
        except Exception:
            continue
    return None


def from_hf(url):
    m = re.match(r"https?://huggingface\.co/([^/?#]+)/?$", url or "")
    if not m:
        return None
    for kind in ("organizations", "users"):
        try:
            av = json.loads(get(f"https://huggingface.co/api/{kind}/{m.group(1)}/avatar"))["avatarUrl"]
            if av.startswith("/"):
                av = "https://huggingface.co" + av
            data = get(av, binary=True)
            ext = "svg" if data.lstrip()[:5] in (b"<?xml", b"<svg ") else ("png" if data[:4] == b"\x89PNG" else "jpg")
            return data, ext, av
        except Exception:
            continue
    return None


def entities():
    load = lambda n: (lambda d: d if isinstance(d, list) else d[n])(json.loads((ROOT / f"data/{n}.json").read_text()))
    out = {}
    for m in load("makers"):
        out[m["id"]] = (m["name"], list((m.get("links") or {}).values()))
    for c in load("channels"):
        out[slug(c["name"])] = (c["name"], [c.get("links", {}).get("site")] if c.get("links") else [])
    for o in load("offers"):
        n = o.get("channel") or o.get("provider")
        src = o.get("source") if isinstance(o.get("source"), dict) else {}
        out.setdefault(slug(n), (n, [src.get("url")] if src.get("url") else []))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", nargs="*", default=[])
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    idx = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    ents = entities()
    if a.report:
        for k in sorted(ents):
            print(f"{k:32} {idx.get(k, {}).get('src', 'MISSING')}")
        return
    lob, sim = fetch_pkg("lobehub"), fetch_pkg("simple")
    missing = []
    for k, (name, urls) in sorted(ents.items()):
        if k in idx and k not in a.refresh:
            continue
        cands = ALIASES.get(k, []) + [k, slug(name).split("-")[0]]
        urls = urls + ([SITES[k]] if k in SITES else [])
        hit = from_libs(cands, lob, sim)
        if hit:
            p, src, mono = hit
            f = (f"si-{p.name}" if src == "simple-icons" else p.name)
            (OUT / f).write_text(p.read_text())
            idx[k] = {"file": f, "src": src, "mono": mono}
            continue
        for fn, src in ((from_hf, "huggingface"), (from_site, "site")):
            got = next((r for u in urls if u for r in [fn(u)] if r), None)
            if got:
                data, kind, u = got
                f = f"{src[:4]}-{k}.{kind}"
                (OUT / f).write_bytes(data)
                idx[k] = {"file": f, "src": src, "url": u, "mono": False}
                break
        else:
            missing.append(f"{k} ({name})")
    INDEX.write_text(json.dumps(dict(sorted(idx.items())), ensure_ascii=False, indent=1) + "\n")
    used = {v["file"] for v in idx.values()}
    for f in OUT.iterdir():  # drop files nothing points at
        if f.suffix in (".svg", ".png", ".jpg") and f.name not in used:
            f.unlink()
    print(f"✓ {len(idx)} logos in index.json; {len(missing)} still missing (the page draws a generated tile):")
    for m in missing:
        print("  ·", m)


if __name__ == "__main__":
    sys.exit(main())
