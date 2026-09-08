#!/usr/bin/env python3
"""Rewrite the hub's assignment lists from the INSEAD command centre.

The lists in index.html were hand-written, and they had drifted badly: a group
assignment dated 30 September that was really due 14 September, a Marketing
entry carrying assignment 1's title with assignment 3's deadline, and no
accounting deadlines at all against eighteen real ones.

The command centre's obligations/ directory is the fix. Those files are derived
from the Canvas ICS feed, carry `source_reliable: true`, and are the same data
agenda.py reports from -- so this reads them rather than inventing dates.

  python3 tools/sync_todos.py            # rewrite the lists
  python3 tools/sync_todos.py --dry-run  # show what would change

Two things this deliberately does NOT do:

* It never invents an id. Ids come from the obligation's filename, which is the
  deduplication key in the command centre, so they are stable for good. Ticks
  are keyed by id, so stability is what stops a completed assignment coming
  back unticked. ID_ALIASES carries the handful of pre-existing hand-written
  ids across to their obligation, so ticks already made still count.
* It never touches hand-written entries. Readings, "bring your laptop" and
  case prep are not Canvas obligations and would vanish if this owned the whole
  list, so they live in tools/manual-todos.json and are merged in.

Only namespaces dsc / mkt / acc map to the hub's three courses. The command
centre's other obligations -- career, clubs, immigration, leadership -- have no
home here and are left alone; agenda.py remains the place they are read.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE = ROOT / "index.html"
MANUAL = ROOT / "tools" / "manual-todos.json"

DEFAULT_OBLIGATIONS = pathlib.Path.home() / "Desktop" / "INSEAD CLAUDE REPO" / "obligations"

# namespace in the obligation -> the hub's course field prefix
COURSE = {"dsc": "da", "mkt": "mkt", "acc": "fa"}
FIELD = {"da": "daTodo", "mkt": "mktTodo", "fa": "faTodo"}

# statuses that still represent something to do
LIVE = {"open", "unanswered", "expired"}

# Already submitted. These leave the to-do list but stay on the calendar, struck
# through -- the same treatment a tick gives, so finished work is still visible
# where you look for it rather than vanishing.
DONE = {"done"}

# hand-written ids that already exist in the page, mapped onto the obligation
# they were describing, so a tick already made survives this rewrite
ID_ALIASES = {
    "dsc-s03-da-individual-assignment-2-session-3-exercises-3-2-and": "a3",
    "dsc-s02-da-individual-assignment-1-session-2-exercise-2-2-e1": "a2",
    "dsc-s07-da-group-assignment-1-bad-statistics-detection-e1": "g1",
    "mkt-mkt-individual-assignment-01-conjoint-analysis-e01-e1": "mk1",
}


def frontmatter(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*?)\s*(?:#.*)?$", line)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return out


def clean_title(t: str) -> str:
    """Titles embed their own deadline; the page prints the date separately."""
    t = re.sub(r"\s*[—-]\s*due\s.*$", "", t, flags=re.I)
    return t.strip().rstrip("—-").strip()


def parse_local(fm: dict):
    """Return (date, time or None) in campus local terms."""
    raw = fm.get("due_local") or fm.get("due_utc") or fm.get("due") or ""
    if not raw:
        return None, None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})", raw)
    if m:
        if fm.get("due_local"):
            return m.group(1), f"{m.group(2)}:{m.group(3)}"
        # only a UTC instant: shift to Paris (CEST +2 through 24 Oct 2026)
        d = dt.datetime.strptime(raw[:16], "%Y-%m-%dT%H:%M")
        off = 2 if dt.datetime(2026, 3, 29) <= d < dt.datetime(2026, 10, 25) else 1
        d += dt.timedelta(hours=off)
        return d.strftime("%Y-%m-%d"), d.strftime("%H:%M")
    m = re.match(r"(\d{4}-\d{2}-\d{2})$", raw)
    if m:
        return m.group(1), None
    return None, None


def js(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def collect(obligations: pathlib.Path, today: dt.date):
    buckets = {k: [] for k in FIELD}
    skipped = 0
    for f in sorted(obligations.glob("*.md")):
        fm = frontmatter(f)
        ns = fm.get("namespace", "")
        course = COURSE.get(ns)
        if not course:
            continue
        if fm.get("stale", "").lower() == "true":
            continue
        status = fm.get("status", "open")
        if status not in LIVE and status not in DONE:
            skipped += 1          # not-applicable or stale: never happened, show nothing
            continue
        stem = f.stem
        date, time = parse_local(fm)
        entry = {
            "id": ID_ALIASES.get(stem, stem),
            "title": clean_title(fm.get("title", stem)),
            "due": date,
            "time": time,
            "done": status in DONE,
        }
        if date:
            d = dt.date.fromisoformat(date)
            when = "Due " + d.strftime("%a %d %b").lstrip("0")
            if time:
                when += f" at {time}"
            if entry["done"]:
                entry["when"] = when + " · submitted"
                entry["tag"] = "Done"
            else:
                entry["when"] = when + (" · overdue" if d < today else "")
                entry["tag"] = "Overdue" if d < today else "Due"
            entry["_sort"] = date + (time or "23:59")
        else:
            rule = fm.get("due_rule") or "No date in Canvas"
            entry["when"] = rule
            entry["tag"] = "Undated"
            entry["_sort"] = "9999"
        buckets[course].append(entry)
    return buckets, skipped


def render(entries: list) -> str:
    if not entries:
        return "[]"
    rows = []
    for e in sorted(entries, key=lambda x: x["_sort"]):
        parts = [f"id: {js(e['id'])}", f"title: {js(e['title'])}", f"when: {js(e['when'])}",
                 f"tag: {js(e['tag'])}"]
        if e.get("due"):
            parts.append(f"due: {js(e['due'])}")
        if e.get("time"):
            parts.append(f"time: {js(e['time'])}")
        if e.get("done"):
            parts.append("done: true")
        rows.append("      { " + ", ".join(parts) + " }")
    return "[\n" + ",\n".join(rows) + "\n    ]"


def field_span(src: str, name: str):
    m = re.search(r"^  " + name + r"\s*=\s*(?=\[)", src, re.M)
    if not m:
        return None
    start = m.end()
    depth, i = 0, start
    while i < len(src):
        c = src[i]
        if c in "\"'`":
            q, j = c, i + 1
            while j < len(src):
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == q:
                    break
                j += 1
            i = j + 1
            continue
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=pathlib.Path, default=DEFAULT_OBLIGATIONS)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.dir.is_dir():
        print(f"error: no obligations directory at {a.dir}")
        print("       pass --dir if the command centre lives somewhere else.")
        return 1

    today = dt.date.today()
    buckets, skipped = collect(a.dir, today)

    manual = json.loads(MANUAL.read_text(encoding="utf-8")) if MANUAL.exists() else {}
    for course, items in manual.items():
        if course.startswith("_"):      # comment blocks, not a course
            continue
        for m in items:
            m.setdefault("_sort", m.get("due") or "9999")
        buckets.setdefault(course, []).extend(items)

    html = PAGE.read_text(encoding="utf-8")
    changed = False
    for course, field in FIELD.items():
        span = field_span(html, field)
        if not span:
            print(f"error: could not find `{field}` in index.html")
            return 1
        new = render(buckets[course])
        old = html[span[0]:span[1]]
        n_man = len(manual.get(course, []))
        print(f"{field:<8} {len(buckets[course]):>2} entries "
              f"({len(buckets[course]) - n_man} from obligations, {n_man} hand-written)")
        if old.strip() != new.strip():
            changed = True
            if not a.dry_run:
                html = html[:span[0]] + new + html[span[1]:]
                # spans shift after each edit, so re-read positions next loop
                PAGE.write_text(html, encoding="utf-8")
                html = PAGE.read_text(encoding="utf-8")

    print(f"\n{skipped} obligation(s) skipped as not applicable or stale.")
    if a.dry_run:
        print("dry run — nothing written.")
    elif changed:
        print("index.html updated. Run tools/check_content.py, then commit.")
    else:
        print("already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
