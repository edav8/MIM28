# MIM'28 study hub

Live at **https://edav8.github.io/mim28/**

Three courses in one place, built from the class handouts.

| Page | What it holds | Saved under |
| --- | --- | --- |
| `index.html` | The hub: Marketing, Data Analysis, the assignment list and the calendar | `mim28-hub-v1` |
| `accounting.html` | The full accounting trainer: Financial Accounting (`s1`–`s15`) and Financial Reporting & Analysis (`f1`–`f10`) | `fa-trainer-v1` |

The hub holds no accounting sessions of its own — it links across to `accounting.html`.

## Adding a session

No build step: the file you edit is the file that ships.

**In the hub** (`index.html`), fields are prefixed by course — `mkt` for Marketing,
`da` for Data Analysis:

1. Add the write-up to `mktLessons` / `daLessons`, keyed by session key.
2. Add questions to `mktBank` / `daBank` under the same key.
3. Flip the flag in `mktBuilt` / `daBuilt`.

**In the accounting trainer** (`accounting.html`), add to `bank` (keyed by session)
and flip `built`. Note `exercises` there is keyed by **course** (`fa` / `fra`), not
by session.

Then check, commit and push:

```bash
cd ~/Documents/GitHub/mim28 && python3 tools/check_content.py
```

## Updating without losing anyone's progress

Ticked assignments, drill scores and mistake history live in the reader's browser,
not in this repo. Republishing the site does **not** clear them — browser storage
survives deploys. Two edits would destroy them anyway, and neither looks dangerous
in a diff, so both are checked against the previous commit and fail the build:

- **Changing a page's localStorage key** (`mim28-hub-v1`, `fa-trainer-v1`). Bump the
  key and every reader silently restarts from zero.
- **Renumbering or removing an assignment `id`.** Ticks are keyed by id. Change an
  id and a completed assignment comes back unticked while some other row shows as
  done. To reword an assignment, keep its id and edit the title.

All three courses share one `todoDone` map, so assignment ids must be unique across
`mktTodo`, `daTodo` and `faTodo` too. That is also checked.

Deliberately resetting everyone is still possible — change the key on purpose and
the failure message tells you that is what you are doing.

## A note on progress carried over from the older sites

GitHub Pages serves all of your repos from the single origin `edav8.github.io`, and
browser storage is per-origin. So `accounting.html` here reads the **same**
`fa-trainer-v1` data as the older `fra-trainer` site: accounting progress carries
over by itself.

The hub uses a new key, `mim28-hub-v1`, so Data Analysis progress does **not** carry
over from `data-trainer` — that starts fresh. Nothing is lost; the old site still has
it under `da-trainer-v1`.

## What is here

| Path | What it is |
| --- | --- |
| `index.html`, `accounting.html` | The two pages. **The only files you edit.** |
| `support.js` | The runtime that mounts them. Do not edit. |
| `assets/` | Archivo fonts, the design-system bundle, one image. |
| `.nojekyll` | Stops GitHub Pages running Jekyll over the site. |
| `tools/` | Pre-publish checks, run by the workflow on every push. |

## How this repo came to be

Both pages arrived as compiled single-file bundles with no source. Each turned out to
carry a resource manifest of gzipped dependencies plus a JSON-encoded copy of its own
template, so the editable source was recovered from inside the artifact, and the
shared runtime, fonts and design-system bundle were extracted into `assets/` once and
pointed at from both pages.

React, ReactDOM and Babel are still fetched at runtime from unpkg by `support.js` with
SRI hashes, so the pages need a network connection.

## Coverage gaps worth knowing

- Marketing: 3 of 10 sessions built.
- Data Analysis: 3 of 15 sessions built.
- Financial Accounting: 6 of 15 sessions built; FRA chapters are complete.
- The FRA list covers chapters 1–12 in 10 entries, and **chapter 8 is not covered**
  by any of them (`f6` is Ch 7, `f7` is Ch 9).
