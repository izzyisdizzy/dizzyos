#!/usr/bin/env python3
"""Cafe menu feed-contract test — no hardware, no network, runs in CI.

The cafe_menu app renders izzybennett.com's /izzys-cafe.json. That shape is a
contract between the two repos (the site gates its deploy on the same rules in
scripts/check-menu-feed.mjs). This checks the sign's half: malformed feeds are
rejected, the last good menu keeps showing, and render() never raises on
whatever the feed turned into. Exits non-zero on the first failure.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.cafe_menu.app import FALLBACK_MENU, CafeMenuApp, menu_problem
from kernel.render import FontBook
from kernel.services import Services

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = FontBook(os.path.join(ROOT, "fonts"))

passed = 0


def check(name, cond):
    global passed
    if not cond:
        sys.exit(f"FAIL: {name}")
    passed += 1
    print(f"  ok: {name}")


# A feed shaped exactly like the live one (item text differs on purpose — only the
# shape is contractual).
GOOD = {
    "title": "Izzy's Cafe",
    "sections": [
        {"heading": "Drinks", "items": ["Coffee", "Matcha"]},
        {"heading": "Milks", "items": ["Whole", "Oat"]},
        {"heading": "Syrups", "items": ["Vanilla"]},
        {"heading": "Food", "items": ["Toast"]},
    ],
}


def broken(mutate):
    feed = copy.deepcopy(GOOD)
    mutate(feed)
    return feed


# Every malformation the site's check-menu-feed.mjs rejects.
BAD = {
    "feed is a list": [GOOD],
    "feed is a string": "Izzy's Cafe",
    "missing title": broken(lambda f: f.pop("title")),
    "blank title": broken(lambda f: f.update(title="  ")),
    "sections is an object": broken(lambda f: f.update(sections={"Drinks": ["Coffee"]})),
    "sections empty": broken(lambda f: f.update(sections=[])),
    "section is a string": broken(lambda f: f["sections"].__setitem__(0, "Drinks")),
    "heading missing": broken(lambda f: f["sections"][0].pop("heading")),
    "heading is a number": broken(lambda f: f["sections"][0].update(heading=7)),
    "items is a string": broken(lambda f: f["sections"][0].update(items="Coffee")),
    "items empty": broken(lambda f: f["sections"][0].update(items=[])),
    "item is a number": broken(lambda f: f["sections"][0]["items"].append(3)),
    "item is an object": broken(lambda f: f["sections"][0]["items"].append({"name": "Tea"})),
    "item is blank": broken(lambda f: f["sections"][0]["items"].append("")),
}


class FakeData:
    """Stands in for DataService: returns queued feeds, or the fallback when the
    queue holds None (i.e. a failed fetch with nothing cached)."""

    def __init__(self, *feeds):
        self.feeds = list(feeds)

    def get_json(self, url, ttl=300, fallback=None):
        feed = self.feeds.pop(0) if self.feeds else None
        return fallback if feed is None else feed


def make_app(*feeds, url="https://example.test/izzys-cafe.json"):
    logs = []
    app = CafeMenuApp({"menu_url": url} if url else {})
    app.on_start(Services(width=128, height=64, data=FakeData(*feeds), fonts=FONTS, log=logs.append))
    return app, logs


def renders(app):
    image = app.render(0)
    return image.size == (128, 64) and image.getbbox() is not None


# --- the contract -----------------------------------------------------------
print("feed contract")
check("a live-shaped feed is valid", menu_problem(GOOD) is None)
check("the bundled fallback menu is itself valid", menu_problem(FALLBACK_MENU) is None)
for name, feed in BAD.items():
    check(f"rejects: {name}", menu_problem(feed) is not None)

# --- the app ----------------------------------------------------------------
print("cafe_menu app")
app, logs = make_app(GOOD)
app.refresh()
check("a good feed is adopted", app._menu is GOOD)
check("and renders", renders(app))

for name, feed in BAD.items():
    app, logs = make_app(GOOD, feed)
    app.refresh()
    app.refresh()
    check(f"after a good feed, '{name}' keeps the last good menu", app._menu is GOOD)
    check(f"  ...logs the rejection", any("rejected feed" in line for line in logs))
    check(f"  ...and still renders", renders(app))

for name, feed in BAD.items():
    app, _ = make_app(feed)
    app.refresh()
    check(f"cold start on '{name}' shows the fallback and renders",
          app._menu is FALLBACK_MENU and renders(app))

app, _ = make_app(None)
app.refresh()
check("a failed fetch with nothing cached shows the fallback", app._menu is FALLBACK_MENU)
check("  ...and renders", renders(app))

app, _ = make_app(url=None)
app.refresh()
check("no menu_url configured shows the fallback", app._menu is FALLBACK_MENU)

app, _ = make_app(GOOD, BAD["section is a string"], GOOD)
app.refresh()
app.refresh()
app.refresh()
check("a good feed after a bad one is adopted again", app._menu is GOOD)

# --- layout -----------------------------------------------------------------
print("layout")


def rows(sections):
    return sum(1 + len(s["items"]) for s in sections)


left, right = CafeMenuApp._split_columns(FALLBACK_MENU["sections"])
check("the live menu (3/3/4/3 rows) splits 6/7, not 10/3",
      (rows(left), rows(right)) == (6, 7))
check("the split keeps section order",
      [s["heading"] for s in left + right] == [s["heading"] for s in FALLBACK_MENU["sections"]])
even = [{"heading": h, "items": ["a", "b"]} for h in ("A", "B", "C", "D")]
check("an evenly sized menu still splits in half",
      [rows(c) for c in CafeMenuApp._split_columns(even)] == [6, 6])
check("a single section stays in one column",
      [len(c) for c in CafeMenuApp._split_columns(even[:1])] == [1, 0] or
      [len(c) for c in CafeMenuApp._split_columns(even[:1])] == [0, 1])

app, _ = make_app(url=None)
app.refresh()
l_lines = app._section_lines(left)
r_lines = app._section_lines(right)
fits = [f for f in FONTS.bitmaps() if f is not None and
        app._fits(f, FALLBACK_MENU["title"], l_lines, r_lines, max(len(l_lines), len(r_lines)), 128, 64)]
check("a bundled bitmap font fits the whole live menu on 128x64 (nothing clipped)", bool(fits))

print(f"cafe menu smoke: {passed} checks passed")
