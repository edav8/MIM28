#!/usr/bin/env python3
"""Structural check on the MIM'28 study hub before it goes live.

Two pages ship from this repo and both are hand-edited:

  index.html       the hub. Three courses in one file, each with its own set of
                   prefixed fields: mktSessions/mktBuilt/mktBank/mktLessons,
                   daSessions/daBuilt/..., faSessions/faBuilt/...
  accounting.html  the full accounting trainer, itself carrying two courses
                   (sessions s1..s15 and fraSessions f1..f10 sharing one `built`).

Adding a session means editing a very large JavaScript object literal, and the
way that fails is silent: one unclosed brace and support.js throws while
mounting, the page renders empty, and nothing says so.

So this checks, for each page: the logic block's delimiters balance, every
`built` flag names a session that exists, every bank/lessons key is a real
session key, and every file the pages reference actually exists on disk --
including the hub's link to accounting.html.

Pure stdlib. Exit 0 clean, 1 on any error. Warnings never fail the build.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = ["index.html", "accounting.html"]

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


# --- extracting the logic block ------------------------------------------------

def script_body(html: str) -> str:
    m = re.search(r'<script[^>]*\bdata-dc-script\b[^>]*>', html)
    if not m:
        err("no <script data-dc-script> block found in index.html")
        return ""
    start = m.end()
    end = html.find("</script>", start)
    if end == -1:
        err("<script data-dc-script> is never closed")
        return ""
    return html[start:end]


# --- a string/comment-aware scanner -------------------------------------------
# Enough JavaScript to know what is code and what is text. Regex-literal
# detection uses the standard previous-significant-character heuristic.

OPEN, CLOSE = "([{", ")]}"
PAIR = {")": "(", "]": "[", "}": "{"}
REGEX_OK_BEFORE = set("(,=:[!&|?{};+-*%~^<>") | {""}


def scan(src: str):
    """Yield (index, char) for characters that are actual code, and validate
    that every string, comment and delimiter is closed. Returns the stack
    remaining at EOF."""
    stack: list[tuple[str, int]] = []
    i, n = 0, len(src)
    prev = ""  # previous significant code character
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        # comments
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            if j == -1:
                err(f"unterminated block comment at line {src.count(chr(10), 0, i) + 1}")
                return stack
            i = j + 2
            continue
        # strings and template literals
        if c in "\"'`":
            quote, j = c, i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == quote:
                    break
                if quote != "`" and src[j] == "\n":
                    err(f"unterminated {quote} string at line {src.count(chr(10), 0, i) + 1}")
                    return stack
                j += 1
            if j >= n:
                err(f"unterminated {quote} string at line {src.count(chr(10), 0, i) + 1}")
                return stack
            i = j + 1
            prev = quote
            continue
        # regex literal
        if c == "/" and prev in REGEX_OK_BEFORE:
            j, ok = i + 1, False
            in_class = False
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    ok = True
                    break
                elif src[j] == "\n":
                    break
                j += 1
            if ok:
                i = j + 1
                prev = "/"
                continue
        # delimiters
        if c in OPEN:
            stack.append((c, i))
        elif c in CLOSE:
            if not stack:
                err(f"stray '{c}' at line {src.count(chr(10), 0, i) + 1} — one closer too many")
                return stack
            op, oi = stack.pop()
            if op != PAIR[c]:
                err(
                    f"mismatched delimiter at line {src.count(chr(10), 0, i) + 1}: "
                    f"'{c}' closes '{op}' opened at line {src.count(chr(10), 0, oi) + 1}"
                )
                return stack
        if not c.isspace():
            prev = c
        i += 1
    return stack


def find_field(src: str, name: str) -> str | None:
    """Return the source text of a class field's initializer literal."""
    m = re.search(r"^\s{2}" + re.escape(name) + r"\s*=\s*(?=[\[{])", src, re.M)
    if not m:
        return None
    start = m.end()
    depth, i, n = 0, start, len(src)
    while i < n:
        c = src[i]
        if c in "\"'`":
            quote, j = c, i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == quote:
                    break
                j += 1
            i = j + 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j == -1 else j
            continue
        if c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return None


def quoted_values(lit: str, key: str) -> list[str]:
    """All string values assigned to `key:` inside a literal."""
    return re.findall(key + r"\s*:\s*['\"]([^'\"]+)['\"]", lit)


def top_level_keys(lit: str) -> list[str]:
    """Keys at depth 1 of an object literal."""
    keys, depth, i, n = [], 0, 0, len(lit)
    while i < n:
        c = lit[i]
        if c in "\"'`":
            quote, j = c, i + 1
            while j < n:
                if lit[j] == "\\":
                    j += 2
                    continue
                if lit[j] == quote:
                    break
                j += 1
            if depth == 1:
                seg = lit[i + 1:j]
                after = lit[j + 1:j + 40].lstrip()
                if after.startswith(":"):
                    keys.append(seg)
            i = j + 1
            continue
        if c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        elif depth == 1 and (c.isalnum() or c == "_" or c == "$"):
            m = re.match(r"[A-Za-z_$][\w$]*", lit[i:])
            if m:
                after = lit[i + m.end():].lstrip()
                if after.startswith(":"):
                    keys.append(m.group(0))
                i += m.end()
                continue
        i += 1
    return keys



HUB_COURSES = {"mkt": "Marketing", "da": "Data Analysis", "fa": "Financial Accounting"}


def check_hub(body_src: str) -> None:
    for pre, label in HUB_COURSES.items():
        sess = find_field(body_src, f"{pre}Sessions")
        built = find_field(body_src, f"{pre}Built")
        if sess is None:
            err(f"[index.html] {label}: field `{pre}Sessions` not found")
            continue
        if not quoted_values(sess, "key"):
            print(f"  {label:<22} delegated to accounting.html (no sessions held in the hub)")
            continue
        keys = quoted_values(sess, "key")
        dup = {k for k in keys if keys.count(k) > 1}
        if dup:
            err(f"[index.html] {label}: duplicate session key(s) {', '.join(sorted(dup))}")
        built_keys = []
        if built:
            for k in top_level_keys(built):
                m = re.search(re.escape(k) + r"\s*:\s*([^,}\s]+)", built)
                if m and m.group(1) not in ("0", "false"):
                    built_keys.append(k)
        for name in (f"{pre}Bank", f"{pre}Lessons"):
            lit = find_field(body_src, name)
            if lit is None:
                continue
            for k in top_level_keys(lit):
                if k not in keys:
                    err(f"[index.html] {label}: `{name}` has key '{k}', not a session key — typo?")
                elif k not in built_keys:
                    warn(f"[index.html] {label}: '{k}' has content in {name} but is not flagged built")
        bank = find_field(body_src, f"{pre}Bank")
        bank_keys = top_level_keys(bank) if bank else []
        for k in built_keys:
            if k not in keys:
                err(f"[index.html] {label}: `{pre}Built` flags '{k}' but no such session exists")
            elif bank and k not in bank_keys:
                warn(f"[index.html] {label}: '{k}' is built but has no questions in {pre}Bank")
        missing = [k for k in keys if k not in built_keys]
        print(f"  {label:<22} {len(built_keys)}/{len(keys)} built"
              + (f"   (not yet: {', '.join(missing)})" if missing else ""))


def check_trainer(body_src: str) -> None:
    cm = find_field(body_src, "courseMeta")
    courses = top_level_keys(cm) if cm else []
    fa = quoted_values(find_field(body_src, "sessions") or "", "key")
    fra = quoted_values(find_field(body_src, "fraSessions") or "", "key")
    known = set(fa + fra)
    built = find_field(body_src, "built")
    built_keys = []
    if built:
        for k in top_level_keys(built):
            m = re.search(re.escape(k) + r"\s*:\s*([^,}\s]+)", built)
            if m and m.group(1) not in ("0", "false"):
                built_keys.append(k)
    bank = find_field(body_src, "bank")
    bank_keys = top_level_keys(bank) if bank else []
    for k in built_keys:
        if k not in known:
            err(f"[accounting.html] `built` flags '{k}' but no such session exists")
        elif k not in bank_keys:
            err(f"[accounting.html] '{k}' is flagged built but has no questions in `bank`")
    for k in bank_keys:
        if known and k not in known:
            err(f"[accounting.html] `bank` has key '{k}', not a session key — typo?")
    for name in ("checks",):
        lit = find_field(body_src, name)
        if lit:
            for k in top_level_keys(lit):
                if known and k not in known:
                    err(f"[accounting.html] `{name}` has key '{k}', not a session key — typo?")
    ex = find_field(body_src, "exercises")
    if ex:
        for k in top_level_keys(ex):
            if courses and k not in courses:
                err(f"[accounting.html] `exercises` has key '{k}', which is not a course in "
                    f"`courseMeta` ({', '.join(courses)}). Exercises are keyed by course, "
                    "not by session.")
    print(f"  Financial Accounting   {len([k for k in built_keys if k in fa])}/{len(fa)} sessions built")
    print(f"  Financial Reporting    {len([k for k in built_keys if k in fra])}/{len(fra)} chapters built")


def check_references(name: str, html: str) -> None:
    """Every local file a page points at must exist -- fonts, the runtime, and
    the hub's link across to accounting.html."""
    refs = set(re.findall(r'src="([^"#:]+)"', html))
    refs |= set(re.findall(r'href="([^"#:]+)"', html))
    refs |= set(re.findall(r'url\("([^"#:]+)"\)', html))
    for r in sorted(refs):
        if r.startswith(("http", "//", "data:", "#", "mailto:")):
            continue
        target = ROOT / r.lstrip("./")
        if not target.exists():
            err(f"[{name}] references '{r}', which does not exist in the repo")


# --- keeping saved progress ------------------------------------------------
# Everything a reader has done -- ticked assignments, drill scores, what they
# got wrong -- lives in the browser under one localStorage key per page. Two
# edits can silently throw that away, and neither looks dangerous in a diff:
#
#   1. changing the storage key      -> every reader starts from zero
#   2. renumbering a todo id         -> ticks reappear on the wrong assignment
#
# Both are checked against the previous commit.

TODO_FIELDS = {"index.html": ("mktTodo", "daTodo", "faTodo"), "accounting.html": ("faTodo",)}


def storage_key(html: str) -> str | None:
    m = re.search(r"localStorage\.setItem\('([^']+)'", html)
    return m.group(1) if m else None


def todo_ids(body_src: str, fields) -> dict:
    out = {}
    for f in fields:
        lit = find_field(body_src, f)
        if lit:
            out[f] = quoted_values(lit, "id")
    return out


def prev_version(name: str) -> str | None:
    try:
        r = subprocess.run(["git", "show", f"HEAD:{name}"], cwd=ROOT,
                           capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 and r.stdout else None
    except Exception:
        return None


def check_memory(name: str, html: str, body_src: str) -> None:
    fields = TODO_FIELDS.get(name, ())
    ids = todo_ids(body_src, fields)

    flat = [i for v in ids.values() for i in v]
    dup = {i for i in flat if flat.count(i) > 1}
    if dup:
        err(f"[{name}] duplicate assignment id(s) {', '.join(sorted(dup))}. All courses "
            "share one todoDone map, so a repeated id ticks two assignments at once.")

    prev = prev_version(name)
    if not prev:
        return

    now_key, old_key = storage_key(html), storage_key(prev)
    if old_key and now_key and now_key != old_key:
        err(f"[{name}] the localStorage key changed from '{old_key}' to '{now_key}'. "
            "Every reader's ticks, scores and history would be lost. Keep the old key "
            "unless you intend exactly that.")

    old_body = script_body(prev) if "data-dc-script" in prev else ""
    if not old_body:
        return
    old_ids = todo_ids(old_body, fields)
    for f, old in old_ids.items():
        gone = [i for i in old if i not in ids.get(f, [])]
        if gone:
            err(f"[{name}] assignment id(s) removed or renumbered in `{f}`: "
                f"{', '.join(gone)}. Saved ticks are keyed by id -- keep the id and edit "
                "the title instead, or completed assignments come back as unticked and "
                "the wrong rows show as done.")


def main() -> int:
    for name in PAGES:
        page = ROOT / name
        if not page.exists():
            err(f"{name} not found")
            continue
        html = page.read_text(encoding="utf-8")
        if "support.js" not in html:
            err(f"[{name}] no longer references support.js — the page cannot mount")
        check_references(name, html)
        src = script_body(html)
        if not src:
            continue
        check_memory(name, html, src)
        for op, oi in scan(src):
            err(f"[{name}] unclosed '{op}' opened at line {src.count(chr(10), 0, oi) + 1} "
                "of the logic block")
        print(f"{name}:")
        if name == "index.html":
            check_hub(src)
        else:
            check_trainer(src)
    return report()


def report() -> int:
    for w in warnings:
        print(f"warning: {w}")
    for e in errors:
        print(f"error: {e}")
    if errors:
        print(f"\nFAILED — {len(errors)} error(s). Nothing was published.")
        return 1
    print(f"\nOK — no errors{f', {len(warnings)} warning(s)' if warnings else ''}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
