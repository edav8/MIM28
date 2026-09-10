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
ACCOUNTING = ROOT / "accounting.html"
MANUAL = ROOT / "tools" / "manual-todos.json"

DEFAULT_OBLIGATIONS = pathlib.Path.home() / "Desktop" / "INSEAD CLAUDE REPO" / "obligations"

# namespace in the obligation -> the hub's course field prefix
COURSE = {"dsc": "da", "mkt": "mkt", "acc": "fa"}
FIELD = {"da": "daTodo", "mkt": "mktTodo", "fa": "faTodo", "other": "otherTodo"}

# Everything the command centre tracks that is not one of the three courses:
# careers and consulting prep, the community challenge, clubs, leadership,
# immigration. These have deadlines like any other and were invisible here.
OTHER_LABEL = {"cdc": "Careers", "co-cdc": "Careers", "clubs": "Clubs",
               "lead": "Leadership", "life": "Admin", "mim28": "Programme"}

# statuses that still represent something to do
LIVE = {"open", "unanswered", "expired"}

# Where an obligation may come from for it to be published.
#
# This site is shared. Anything the command centre learned from a mailbox is
# private correspondence -- who wrote, what was sitting unread in Junk -- and
# it does not go on a public page no matter which namespace it landed in.
# Canvas and the calendar feed are course material and are fine.
PUBLISHABLE_SOURCES = {"ics", "canvas", "doc", ""}

# Work set for you and a handful of others, not for the cohort. Publishing it
# tells every reader who is on a retake, which is nobody else's business and
# is not undone by deleting it later. Two signals catch it on its own:
#
#   · the word retake / resit / remedial / make-up in the title
#   · a title that counts its own audience -- "(8 students)"
#
# Anything these miss goes in tools/private-todos.json by id, and is held back
# the same way.
PRIVATE_WORDS = ("retake", "resit", "remedial", "make-up", "makeup")
PRIVATE_COHORT = re.compile(r"\(\s*\d{1,2}\s+students?\s*\)", re.I)
PRIVATE_FILE = ROOT / "tools" / "private-todos.json"


def private_ids() -> set:
    if not PRIVATE_FILE.exists():
        return set()
    try:
        data = json.loads(PRIVATE_FILE.read_text(encoding="utf-8"))
        return {str(x) for x in data.get("never_publish", [])}
    except Exception:
        return set()


def is_private(title: str, stem: str, blocked: set) -> bool:
    low = title.lower()
    return (stem in blocked
            or any(w in low for w in PRIVATE_WORDS)
            or bool(PRIVATE_COHORT.search(title)))

# Already submitted, according to YOUR Canvas account.
#
# This is personal state and by default it is NOT published. The site is shared,
# and a submission flag baked into the file would tell every reader that they had
# handed in work they have not touched -- their own ticks are the only thing that
# can honestly say otherwise. So a shared build lists these as ordinary
# deadlines and each reader ticks their own.
#
# --personal re-includes them, for a build only you will read.
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


def collect(obligations: pathlib.Path, today: dt.date, personal: bool = False):
    buckets = {k: [] for k in FIELD}
    submitted = []
    skipped_done = []
    private = []
    restricted = []
    blocked = private_ids()
    skipped = 0
    for f in sorted(obligations.glob("*.md")):
        fm = frontmatter(f)
        ns = fm.get("namespace", "")
        course = COURSE.get(ns)
        if not course:
            if ns in OTHER_LABEL:
                course = "other"
            else:
                continue
        if fm.get("stale", "").lower() == "true":
            continue
        stem = f.stem
        title_raw = fm.get("title", stem)
        if is_private(title_raw, stem, blocked):
            restricted.append(title_raw[:72])
            continue

        src = fm.get("source", "").strip().lower()
        # found_only_in is usually harmless ("canvas api"); it disqualifies only
        # when it says the item exists nowhere but a mailbox
        only_in = fm.get("found_only_in", "").strip().lower()
        found_by = fm.get("found_by", "").strip().lower()
        mail_words = ("email", "mail", "outlook", "junk", "inbox", "gmail")
        from_mail = (src not in PUBLISHABLE_SOURCES
                     or any(w in only_in for w in mail_words)
                     or any(w in found_by for w in mail_words))
        if from_mail:
            private.append((fm.get("title", stem)[:70], src or "unknown"))
            continue

        status = fm.get("status", "open")
        if status not in LIVE and status not in DONE:
            skipped += 1          # not-applicable or stale: never happened, show nothing
            continue
        date, time = parse_local(fm)
        entry = {
            "source": OTHER_LABEL.get(ns, ""),
            "id": ID_ALIASES.get(stem, stem),
            "title": clean_title(fm.get("title", stem)),
            "due": date,
            "time": time,
            "done": personal and status in DONE,
        }
        if date:
            d = dt.date.fromisoformat(date)
            when = "Due " + d.strftime("%a %d %b").lstrip("0")
            if time:
                when += f" at {time}"
            if entry["done"]:
                entry["when"] = when + " · submitted"
                entry["tag"] = "Done"
            elif status in DONE:
                # Finished by you. A shared build cannot mark it done for everyone,
                # so it appears as a plain deadline -- but only while it is still
                # ahead. Work you finished weeks ago would otherwise turn up as
                # everyone's overdue backlog, which is noise, not information.
                if d < today:
                    # Finished and past. It leaves the to-do list -- there is
                    # nothing left to do -- but stays on the calendar, struck
                    # through, so the term still reads as a record of what
                    # happened. `closed` rather than `done`: on a shared page
                    # this says the deadline is closed in the course record, not
                    # that the reader submitted anything.
                    entry["closed"] = True
                    entry["when"] = when
                    entry["tag"] = "Closed"
                    skipped_done.append(entry["title"])
                else:
                    entry["when"] = when
                    entry["tag"] = "Due"
                    submitted.append(entry["title"])
            else:
                # No "overdue" baked in. It is stale the day after it is written,
                # and for a shared page lateness is the reader's, not the author's.
                entry["when"] = when
                entry["tag"] = "Due"
            entry["_sort"] = date + (time or "23:59")
        else:
            rule = fm.get("due_rule") or "No date in Canvas"
            entry["when"] = rule
            entry["tag"] = "Undated"
            entry["_sort"] = "9999"
        buckets[course].append(entry)
    return buckets, skipped, submitted, skipped_done, private, restricted


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
        if e.get("closed"):
            parts.append("closed: true")
        if e.get("source"):
            parts.append(f"source: {js(e['source'])}")
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
    ap.add_argument("--personal", action="store_true",
                    help="bake YOUR Canvas submission state into the page. Do not use "
                         "for the shared site: it marks work done for readers who have "
                         "not done it.")
    a = ap.parse_args()

    if not a.dir.is_dir():
        print(f"error: no obligations directory at {a.dir}")
        print("       pass --dir if the command centre lives somewhere else.")
        return 1

    today = dt.date.today()
    buckets, skipped, submitted, skipped_done, private, restricted = collect(a.dir, today, personal=a.personal)

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

    # the accounting trainer keeps its own copy of the accounting deadlines, so it
    # can show them without sending you back to the hub
    if ACCOUNTING.exists():
        acc = ACCOUNTING.read_text(encoding="utf-8")
        span = field_span(acc, "todo")
        if span:
            new_lit = render(buckets["fa"])
            if acc[span[0]:span[1]].strip() != new_lit.strip():
                if not a.dry_run:
                    ACCOUNTING.write_text(acc[:span[0]] + new_lit + acc[span[1]:], encoding="utf-8")
                changed = True
            print(f"accounting.html  {len(buckets['fa'])} entries")
        else:
            print("warning: no `todo` field found in accounting.html")

    print(f"\n{skipped} obligation(s) skipped as not applicable or stale.")
    if skipped_done:
        print(f"{len(skipped_done)} finished and past their deadline: calendar only, struck through.")
    if restricted:
        print(f"\n{len(restricted)} obligation(s) held back as yours alone — a retake or a "
              "named group, not the cohort's work:")
        for t in restricted:
            print(f"  · {t}")
    if private:
        print(f"\n{len(private)} obligation(s) held back as private — they came from a "
              "mailbox, and this site is shared:")
        for t, sname in private:
            print(f"  · [{sname}] {t}")
    if submitted:
        print(f"\n{len(submitted)} assignment(s) Canvas says YOU submitted are listed as "
              "ordinary deadlines,\nbecause this build is shared. Tick them once in your "
              "own browser and the tick sticks:")
        for t in submitted:
            print(f"  · {t}")
    if a.dry_run:
        print("dry run — nothing written.")
    elif changed:
        print("index.html updated. Run tools/check_content.py, then commit.")
    else:
        print("already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
