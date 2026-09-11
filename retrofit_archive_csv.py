#!/usr/bin/env python3
"""
retrofit_archive_csv.py — One-off: add the "⬇ Download CSV" button to EXISTING
archive snapshots (archive/*.html). New snapshots get the button from
update_dashboard.py automatically; this backfills the frozen ones.

Behavior per file:
  - Already has the button (downloadDashboardCSV present) → skipped
  - No </body> tag or no funnel/total table markers → skipped (very old vintage)
  - Otherwise → injects the shared csv_export_snippet() (imported from
    update_dashboard.py — single source of truth) in a right-aligned strip just
    before </body>, so it works across every layout vintage regardless of how
    that snapshot's footer was structured.

CSV filename derives from the archive filename:
  2026-08-12.html      → call-capacity-2026-08-12.csv
  week-2026-08-10.html → call-capacity-week-2026-08-10.csv
  month-2026-08.html   → call-capacity-month-2026-08.csv

Idempotent — safe to re-run. Read-only against Close (no API calls at all).

Usage locally:   python retrofit_archive_csv.py
Usage via CI:    Actions → "Retrofit Archive CSV Button" → Run workflow
                 (the workflow commits the modified archive files)
"""

import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_dashboard import csv_export_snippet  # shared implementation

ARCHIVE_DIR = "archive"


def wrap_snippet(snippet):
    return (
        '\n<div class="csv-retrofit" style="max-width:1400px;margin:4px auto 28px;'
        'padding:0 16px;display:flex;justify-content:flex-end;">'
        f"{snippet}</div>\n"
    )


def main():
    files = sorted(glob.glob(os.path.join(ARCHIVE_DIR, "*.html")))
    if not files:
        print(f"❌ No files found under {ARCHIVE_DIR}/ — run from the repo root.")
        sys.exit(1)

    injected, skipped_done, skipped_old = 0, 0, 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            html = f.read()

        stem = os.path.splitext(os.path.basename(path))[0]
        if "downloadDashboardCSV" in html:
            skipped_done += 1
            print(f"  ⏭ {stem}: already has the button")
            continue
        if "</body>" not in html or ("sec-label" not in html and "total-row" not in html):
            skipped_old += 1
            print(f"  ⏭ {stem}: no exportable funnel table in this vintage — skipped")
            continue

        csv_name = f"call-capacity-{stem}.csv"  # stems already carry week-/month- prefixes
        block = wrap_snippet(csv_export_snippet(csv_name))
        html = html.replace("</body>", block + "</body>", 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        injected += 1
        print(f"  ✅ {stem}: button injected → {csv_name}")

    print(f"\n═══ Done: {injected} injected · {skipped_done} already had it · "
          f"{skipped_old} too old to export ═══")


if __name__ == "__main__":
    main()
