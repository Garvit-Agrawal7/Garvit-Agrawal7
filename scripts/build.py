#!/usr/bin/env python3
"""Builds the animated profile SVGs from live GitHub data.

Writes:
  assets/profile.svg          hero (typewriter) + stack marquee + live activity
  assets/cards/<repo>.svg     one card per featured repository

Needs GH_TOKEN (the workflow passes one) and GH_USER. Standard library only.
"""
import datetime as dt
import json
import os
import random
import sys
import urllib.request
from html import escape
from pathlib import Path

# --------------------------------------------------------------------- config
USER = os.environ.get("GH_USER", "Garvit-Agrawal7")
ACCENT = "#d2a8ff"
GREEN = "#3fb950"

INTRO = "hi, i\u2019m garvit agrawal"
PHRASES = ["design APIs.", "ship services.", "scale backends."]
STATUS = "currently exploring OS dev  \u00b7  IST (UTC+5:30)"

STACK_MAIN = ["Python", "FastAPI", "Flask", "Node.js", "Express", "Redis", "PostgreSQL", "MySQL", "MongoDB"]
STACK_MORE = ["C", "x86", "JavaScript", "Java", "SQLite", "Selenium", "React", "Next.js", "AWS", "Azure", "Linux"]

FEATURED = ["GameLog", "GameLog-Backend", "database_backup", "pipemix", "Flight-Deals", "movie-recom"]

# ------------------------------------------------------------------- palette
BG, PANEL, BORDER, RULE = "#0d1117", "#151b23", "#262c36", "#21262d"
TEXT, MUTED = "#f0f6fc", "#9198a1"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
STYLE = f"<style>.m{{font-family:{MONO}}}.s{{font-family:{SANS}}}</style>"

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"

# --------------------------------------------------------------------- fetch
QUERY = """
query($login:String!, $from:DateTime!, $to:DateTime!) {
  user(login:$login) {
    pullRequests { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, first: 100) {
      nodes { name description stargazerCount primaryLanguage { name } }
    }
    year: contributionsCollection(from:$from, to:$to) {
      contributionCalendar { totalContributions }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount contributionLevel weekday date } }
      }
    }
  }
}"""


def fetch():
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN is not set")
    now = dt.datetime.now(dt.timezone.utc)
    start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    body = json.dumps({"query": QUERY, "variables": {
        "login": USER, "from": start.isoformat(), "to": now.isoformat()}}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": f"bearer {token}", "Content-Type": "application/json",
        "User-Agent": "profile-builder"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if payload.get("errors"):
        sys.exit(f"GraphQL errors: {payload['errors']}")
    u = payload["data"]["user"]
    cal = u["contributionsCollection"]["contributionCalendar"]
    repos = u["repositories"]["nodes"]
    return {
        "year": now.year,
        "year_total": u["year"]["contributionCalendar"]["totalContributions"],
        "prs": u["pullRequests"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "total": cal["totalContributions"],
        "weeks": [[(d["weekday"], d["contributionLevel"], d["contributionCount"], d["date"])
                   for d in w["contributionDays"]] for w in cal["weeks"]],
        "repos": {r["name"]: r for r in repos},
    }


# --------------------------------------------------------------------- gitea
# Optional: add activity from your organisation's Gitea. Only daily contribution counts
# and the number of pull requests you opened are read (no repo names or code). Set
# GITEA_URL, GITEA_USER and GITEA_TOKEN (token scopes: user Read, issue Read), or, if
# Gitea isn't reachable from GitHub, drop exports at data/gitea-heatmap.json and
# data/gitea-prs.json (a bare number).
LOCAL_TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))  # IST: Gitea buckets are grouped by local day
GITEA_FILE = ROOT / "data" / "gitea-heatmap.json"
GITEA_PRS_FILE = ROOT / "data" / "gitea-prs.json"


def gitea_get(path):
    """GET from the Gitea API; returns (json, headers) or (None, None) if not configured or failing."""
    url = os.environ.get("GITEA_URL", "").rstrip("/")
    token = os.environ.get("GITEA_TOKEN", "")
    if not (url and token):
        return None, None
    req = urllib.request.Request(f"{url}/api/v1{path}", headers={
        "Authorization": f"token {token}", "User-Agent": "profile-builder"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r), r.headers
    except Exception as exc:  # unreachable, bad token or missing scope: carry on without it
        print(f"warning: Gitea request {path.split('?')[0]} failed ({exc})", file=sys.stderr)
        return None, None


def fetch_gitea_days():
    user = os.environ.get("GITEA_USER", "")
    raw = gitea_get(f"/users/{user}/heatmap")[0] if user else None
    if raw is None and GITEA_FILE.exists():
        raw = json.loads(GITEA_FILE.read_text())
    days = {}
    for entry in raw or []:
        day = dt.datetime.fromtimestamp(entry["timestamp"], LOCAL_TZ).date().isoformat()
        days[day] = days.get(day, 0) + entry["contributions"]
    return days


def fetch_gitea_prs():
    """Pull requests you opened on Gitea, all time and any state (needs issue Read)."""
    query = "/repos/issues/search?type=pulls&created=true&state=all&limit=50&page={}"
    first, headers = gitea_get(query.format(1))
    if first is not None:
        total = headers.get("X-Total-Count") if headers else None
        if total is not None:
            return int(total)
        count, page, batch = 0, 1, first
        while batch:  # older Gitea without the total header: count page by page
            count += len(batch)
            page += 1
            batch = gitea_get(query.format(page))[0] if len(batch) == 50 else []
        return count
    if GITEA_PRS_FILE.exists():
        return int(json.loads(GITEA_PRS_FILE.read_text()))
    return 0


def fetch_gitea():
    missing = [k for k in ("GITEA_URL", "GITEA_USER", "GITEA_TOKEN") if not os.environ.get(k)]
    if missing and len(missing) < 3:
        print(f"warning: Gitea skipped, secret(s) not set: {', '.join(missing)}", file=sys.stderr)
    elif missing:
        print("Gitea: not configured")
    days, prs = fetch_gitea_days(), fetch_gitea_prs()
    print(f"Gitea: {sum(days.values())} contributions on {len(days)} days, {prs} pull requests")
    return {"days": days, "prs": prs}


def relevel(weeks):
    """Recompute GitHub-style quartile levels after counts have changed."""
    counts = sorted(c for w in weeks for _, _, c, _ in w if c)
    if not counts:
        return weeks
    q = [counts[int(len(counts) * f) - 1] if int(len(counts) * f) else counts[0] for f in (.25, .5, .75)]

    def level(c):
        if not c:
            return "NONE"
        return ("FIRST_QUARTILE" if c <= q[0] else "SECOND_QUARTILE" if c <= q[1]
                else "THIRD_QUARTILE" if c <= q[2] else "FOURTH_QUARTILE")
    return [[(wd, level(c), c, day) for wd, _, c, day in w] for w in weeks]


def merge_gitea(d, gitea):
    days, prs = gitea.get("days") or {}, gitea.get("prs") or 0
    d["prs"] += prs
    if days:
        weeks = [[(wd, lvl, c + days.get(day, 0), day) for wd, lvl, c, day in w] for w in d["weeks"]]
        d["weeks"] = relevel(weeks)
        d["total"] = sum(c for w in weeks for _, _, c, _ in w)
        d["year_total"] += sum(v for day, v in days.items() if day.startswith(f"{d['year']}-"))
    d["work"] = bool(days or prs)
    return d


def longest_streak(weeks):
    best = run = 0
    for w in weeks:
        for _, _, count, _ in w:
            run = run + 1 if count else 0
            best = max(best, run)
    return best


# -------------------------------------------------------------------- helpers
def t(x, y, s, size, fill, cls="m", anchor=None, extra=""):
    a = f' text-anchor="{anchor}"' if anchor else ""
    return (f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}"'
            f'{a} xml:space="preserve"{extra}>{s}</text>')


def fmt(n):
    return f"{n:,}"


# ------------------------------------------------------------------ typewriter
def typewriter(x0, base, size):
    cw = size * 0.6
    period = 3.0
    total = period * len(PHRASES)
    events = []  # (time, phrase, chars shown)
    for i, p in enumerate(PHRASES):
        s, n = i * period, len(p)
        events.append((s, i, 0))
        for k in range(1, n + 1):
            events.append((s + 0.2 + k * 0.075, i, k))
        hold = s + 2.35
        for j, k in enumerate(range(n - 1, -1, -1), start=1):
            events.append((hold + j * 0.035, i, k))
    kt = ";".join(f"{e[0] / total:.4f}" for e in events)
    out = []
    for i, p in enumerate(PHRASES):
        widths = ";".join(f"{(e[2] * cw if e[1] == i else 0):.1f}" for e in events)
        out.append(
            f'<clipPath id="tw{i}"><rect x="{x0:.1f}" y="{base - size}" height="{size * 1.4:.0f}" width="0">'
            f'<animate attributeName="width" dur="{total}s" repeatCount="indefinite" calcMode="discrete" '
            f'values="{widths}" keyTimes="{kt}"/></rect></clipPath>')
        out.append(
            f'<text class="m" clip-path="url(#tw{i})" x="{x0:.1f}" y="{base}" font-size="{size}" '
            f'font-weight="500" fill="{ACCENT}" textLength="{len(p) * cw:.1f}" lengthAdjust="spacing" '
            f'xml:space="preserve">{escape(p)}</text>')
    xs = ";".join(f"{x0 + e[2] * cw:.1f}" for e in events)
    out.append(
        f'<rect x="{x0:.1f}" y="{base - size * 0.82:.1f}" width="3" height="{size * 0.98:.1f}" fill="{ACCENT}">'
        f'<animate attributeName="x" dur="{total}s" repeatCount="indefinite" calcMode="discrete" '
        f'values="{xs}" keyTimes="{kt}"/>'
        f'<animate attributeName="opacity" dur="0.9s" repeatCount="indefinite" calcMode="discrete" '
        f'values="1;0" keyTimes="0;0.5"/></rect>')
    return "".join(out)


# --------------------------------------------------------------------- marquee
def marquee_row(items, base, size, fill, squares, reverse, speed):
    cw = size * 0.6
    gap = 40
    widths = [(15 if squares else 0) + len(it) * cw for it in items]
    seq = sum(w + gap for w in widths)
    parts = []
    for rep in range(3):
        x = rep * seq
        for it, w in zip(items, widths):
            tx = x
            if squares:
                parts.append(f'<rect x="{x:.1f}" y="{base - 9:.1f}" width="5" height="5" fill="{ACCENT}"/>')
                tx = x + 15
            parts.append(f'<text class="m" x="{tx:.1f}" y="{base}" font-size="{size}" fill="{fill}" '
                         f'textLength="{len(it) * cw:.1f}" lengthAdjust="spacing">{escape(it)}</text>')
            x += w + gap
    frm, to = (f"{-seq:.1f} 0", "0 0") if reverse else ("0 0", f"{-seq:.1f} 0")
    return (f'<g transform="translate(48 0)"><g>{"".join(parts)}'
            f'<animateTransform attributeName="transform" type="translate" from="{frm}" to="{to}" '
            f'dur="{seq / speed:.1f}s" repeatCount="indefinite"/></g></g>')


GLYPHS = "0123456789#%&$@"


def decrypt(value, x, y, size, start, seed, frame=0.09, per_char=0.38):
    """One-shot scramble: random glyphs that lock into the real value, left to right."""
    rnd = random.Random(seed)
    cw = size * 0.6
    width = len(value) * cw
    locks = [start + k * per_char for k in range(len(value))]
    end = locks[-1]
    common = (f'class="m" x="{x}" y="{y}" font-size="{size}" font-weight="500" '
              f'textLength="{width:.1f}" lengthAdjust="spacing"')
    o = []
    tt = 0.0
    while tt < end:
        chars = "".join(ch if tt >= lk else rnd.choice(GLYPHS) for ch, lk in zip(value, locks))
        o.append(f'<text {common} fill="{ACCENT}" fill-opacity=".75" opacity="0">{escape(chars)}'
                 f'<set attributeName="opacity" to="1" begin="{tt:.2f}s" dur="{frame}s"/></text>')
        tt += frame
    # visible by default, so viewers without animation support still see the number
    o.append(f'<text {common} fill="{TEXT}">{escape(value)}'
             f'<set attributeName="opacity" to="0" begin="0s" dur="{end:.2f}s"/>'
             f'<animate attributeName="fill" from="{ACCENT}" to="{TEXT}" begin="{end:.2f}s" dur="0.8s" '
             f'fill="freeze"/></text>')
    return "".join(o)


def snake_path(targets, cols):
    """Greedy route: from the left edge, always head for the nearest cell with contributions."""
    path = [(-5, 3), (-4, 3), (-3, 3), (-2, 3), (-1, 3)]
    left = set(targets)
    while left:
        hc, hr = path[-1]
        tc, tr = min(left, key=lambda cell: (abs(cell[0] - hc) + abs(cell[1] - hr), cell[0], cell[1]))
        while (hc, hr) != (tc, tr):
            if hr != tr:
                hr += 1 if tr > hr else -1
            else:
                hc += 1 if tc > hc else -1
            path.append((hc, hr))
            left.discard((hc, hr))
    hc, hr = path[-1]
    while hc < cols + 5:
        hc += 1
        path.append((hc, hr))
    return path


def snake_grid(weeks, x0, y0, pitch, step=0.08, pause=1.5, length=6):
    cells = {(c, wd): LEVELS.get(level, 0.1) for c, week in enumerate(weeks) for wd, level, *_ in week}
    targets = [cell for cell, lv in cells.items() if lv > 0.1]
    path = snake_path(targets, len(weeks))
    total = len(path) * step + pause
    eaten = {}
    for i, cell in enumerate(path):
        if cell in cells and cell not in eaten:
            eaten[cell] = i * step / total
    o = [f'<clipPath id="grid"><rect x="{x0 - 2}" y="{y0 - 2}" width="{len(weeks) * pitch + 2:.1f}" '
         f'height="{7 * pitch + 2:.1f}"/></clipPath>']
    for (c, r), lv in cells.items():
        x, y = x0 + c * pitch, y0 + r * pitch
        anim = ""
        if lv > 0.1:
            anim = (f'<animate attributeName="opacity" values="{lv};0.1" keyTimes="0;{eaten[(c, r)]:.4f}" '
                    f'calcMode="discrete" dur="{total:.2f}s" repeatCount="indefinite"/>')
        o.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="10" height="10" rx="2" fill="{ACCENT}" '
                 f'opacity="{lv}">{anim}</rect>')
    kt = ";".join(f"{i * step / total:.4f}" for i in range(len(path))) + ";1"
    o.append('<g clip-path="url(#grid)">')
    for k in range(length - 1, -1, -1):
        pts = [path[max(0, i - k)] for i in range(len(path))] + [path[-1]]
        vals = ";".join(f"{x0 + c * pitch:.1f} {y0 + r * pitch:.1f}" for c, r in pts)
        size = 10 if k == 0 else 10 - k * 0.6
        off = (10 - size) / 2
        colour = "#ffffff" if k == 0 else ACCENT
        o.append(f'<rect x="{off:.1f}" y="{off:.1f}" width="{size:.1f}" height="{size:.1f}" rx="3" '
                 f'fill="{colour}" opacity="{1 - k * 0.1:.2f}"><animateTransform attributeName="transform" '
                 f'type="translate" values="{vals}" keyTimes="{kt}" dur="{total:.2f}s" '
                 f'repeatCount="indefinite"/></rect>')
    o.append("</g>")
    return "".join(o)


# ----------------------------------------------------------------- profile svg
def section_label(num, name, y):
    return (f'<text class="m" x="48" y="{y}" font-size="11" letter-spacing="1.5" fill="{MUTED}" '
            f'xml:space="preserve"><tspan fill="{ACCENT}">{num}</tspan>  \u2014  {name}</text>')


LEVELS = {"NONE": 0.1, "FIRST_QUARTILE": 0.35, "SECOND_QUARTILE": 0.55,
          "THIRD_QUARTILE": 0.78, "FOURTH_QUARTILE": 1.0}


def profile_svg(d):
    W, H = 840, 784
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'role="img" aria-label="Garvit Agrawal">', STYLE]
    o.append('<defs><linearGradient id="fg"><stop offset="0" stop-color="#000"/>'
             '<stop offset=".12" stop-color="#fff"/><stop offset=".88" stop-color="#fff"/>'
             '<stop offset="1" stop-color="#000"/></linearGradient>'
             '<mask id="fade"><rect x="48" y="272" width="744" height="84" fill="url(#fg)"/></mask></defs>')
    o.append(f'<rect width="{W}" height="{H}" rx="12" fill="{BG}"/>')

    # hero
    o.append(t(48, 72, escape(INTRO), 14, MUTED))
    o.append(f'<text class="m" x="48" y="140" font-size="44" font-weight="500" fill="{TEXT}" '
             f'textLength="26.4" lengthAdjust="spacing">I</text>')
    o.append(typewriter(48 + 2 * 26.4, 140, 44))
    o.append(f'<circle cx="52" cy="179.5" r="3.5" fill="{GREEN}"><animate attributeName="opacity" '
             f'values="1;.3;1" dur="2s" repeatCount="indefinite"/></circle>')
    o.append(t(64, 184, escape(STATUS), 13, MUTED))

    # 01 stack
    o.append(section_label("01", "STACK", 252))
    o.append(f'<path d="M48 272.5H792M48 355.5H792" stroke="{RULE}"/>')
    o.append('<g mask="url(#fade)">')
    o.append(marquee_row(STACK_MAIN, 304, 15, "#d1d7e0", True, False, 26))
    o.append(marquee_row(STACK_MORE, 336, 14, MUTED, False, True, 21))
    o.append('</g>')

    # 02 activity
    o.append(section_label("02", "ACTIVITY", 412))
    live = "live"
    o.append(t(792, 412, live, 12, MUTED, anchor="end",
               extra=f' textLength="{len(live) * 7.2:.1f}" lengthAdjust="spacing"'))
    o.append(f'<circle cx="{792 - len(live) * 7.2 - 11:.1f}" cy="408" r="3" fill="{ACCENT}">'
             f'<animate attributeName="opacity" values="1;.3;1" dur="2s" repeatCount="indefinite"/></circle>')

    tiles = [(f"CONTRIBUTIONS \u00b7 {d['year']}", fmt(d["year_total"]), ""),
             ("PULL REQUESTS", fmt(d["prs"]), ""),
             ("STARS EARNED", fmt(d["stars"]), ""),
             ("LONGEST STREAK", str(longest_streak(d["weeks"])), " days")]
    # tiles: the numbers decrypt once when the README opens, then stay put
    for i, (label, value, unit) in enumerate(tiles):
        x = 48 + i * 189
        o.append(f'<rect x="{x + .5}" y="432.5" width="176" height="95" rx="10" fill="{PANEL}" stroke="{BORDER}"/>')
        o.append(t(x + 18, 464, label, 11, MUTED, extra=' letter-spacing="0.8"'))
        o.append(decrypt(value, x + 18, 508, 30, start=0.9 + i * 0.45, seed=i))
        if unit:
            o.append(f'<text class="m" x="{x + 18 + len(value) * 18}" y="508" font-size="16" fill="{MUTED}" '
                     f'xml:space="preserve">{unit}</text>')

    # contribution grid with a snake that eats it
    o.append(f'<rect x="48.5" y="544.5" width="743" height="163" rx="10" fill="{PANEL}" stroke="{BORDER}"/>')
    o.append(snake_grid(d["weeks"][-53:], 68, 564, 13.2))
    o.append(t(68, 690, "contributions \u00b7 last 12 months", 12, MUTED))
    o.append(t(772, 690, f"{fmt(d['total'])} total", 12, MUTED, anchor="end"))

    # 03 label (the cards follow as separate, clickable images)
    o.append(section_label("03", "SELECTED WORK", 764))
    o.append("</svg>")
    return "".join(o)


# ----------------------------------------------------------------------- cards
def wrap(text, width=50, lines=2):
    words = (text or "").split()
    out, cur, used = [], "", 0
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) <= width:
            cur = f"{cur} {w}".strip()
            used += 1
        else:
            out.append(cur)
            if len(out) == lines:
                break
            cur, used = w, used + 1
    else:
        if cur:
            out.append(cur)
    if used < len(words) and out:
        out[-1] = out[-1][: width - 1].rstrip(" ,.") + "\u2026"
    return out[:lines]


def card_svg(repo):
    W, H = 414, 132
    name = repo["name"]
    lang = (repo.get("primaryLanguage") or {}).get("name", "")
    stars = repo.get("stargazerCount", 0)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'role="img" aria-label="{escape(name)}">', STYLE]
    o.append(f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="10" fill="{PANEL}" stroke="{BORDER}"/>')
    o.append(t(20, 36, escape(name), 15, TEXT))
    o.append(t(394, 36, "\u2197", 15, ACCENT, anchor="end"))
    for i, line in enumerate(wrap(repo.get("description") or "")):
        o.append(t(20, 64 + i * 20, escape(line), 14, MUTED, cls="s"))
    x = 20
    if lang:
        o.append(f'<circle cx="{x + 4}" cy="110" r="4" fill="{ACCENT}"/>')
        o.append(t(x + 14, 114, escape(lang), 12, MUTED, cls="s"))
        x += 14 + len(lang) * 7 + 18
    if stars:
        o.append(t(x, 114, f"\u2605 {stars}", 12, MUTED, cls="s"))
    o.append("</svg>")
    return "".join(o)


# ------------------------------------------------------------------------ main
def build(d):
    (OUT / "cards").mkdir(parents=True, exist_ok=True)
    (OUT / "profile.svg").write_text(profile_svg(d), encoding="utf-8")
    for name in FEATURED:
        repo = d["repos"].get(name)
        if repo is None:
            print(f"warning: {name} not found, skipping card", file=sys.stderr)
            continue
        (OUT / "cards" / f"{name}.svg").write_text(card_svg(repo), encoding="utf-8")


if __name__ == "__main__":
    build(merge_gitea(fetch(), fetch_gitea()))
    print("profile assets written to", OUT)
