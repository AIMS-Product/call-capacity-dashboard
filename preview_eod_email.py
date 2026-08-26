#!/usr/bin/env python3
"""
preview_eod_email.py - Write the production EOD email body to local files.

This uses the same build -> format path as the live EOD sender, but never calls
send_eod_email() or SMTP. It is meant for local design/data checks before any
email goes out.

Usage:
  export CLOSE_API_KEY=...
  python preview_eod_email.py

Optional:
  python preview_eod_email.py --date 2026-08-25 --output eod_preview_2026-08-25.html
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a local HTML preview of the EOD email without sending it."
    )
    parser.add_argument(
        "--date",
        help="PT report date to preview, in YYYY-MM-DD format. Defaults to today in PT.",
    )
    parser.add_argument(
        "--output",
        default="eod_preview.html",
        help="HTML output path. Defaults to eod_preview.html in this folder.",
    )
    parser.add_argument(
        "--plain-output",
        default="eod_preview.txt",
        help="Plain-text output path. Defaults to eod_preview.txt in this folder.",
    )
    return parser.parse_args()


def load_email_modules():
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import update_dashboard as ud
        from test_eod_email import build_minimal_rolling_data
    except ModuleNotFoundError as e:
        print(f"Missing Python dependency: {e.name}")
        print("Install local dependencies with: python -m pip install requests")
        sys.exit(1)
    return ud, build_minimal_rolling_data


def parse_report_date(raw, pacific):
    if not raw:
        return datetime.now(pacific).date()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        print(f"Invalid --date '{raw}'. Use YYYY-MM-DD.")
        sys.exit(1)


def resolve_output_path(raw_path):
    path = Path(raw_path)
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path


def main():
    args = parse_args()
    ud, build_minimal_rolling_data = load_email_modules()
    if not ud.CLOSE_API_KEY:
        print("CLOSE_API_KEY not set.")
        sys.exit(1)

    today = parse_report_date(args.date, ud.PACIFIC)
    html_path = resolve_output_path(args.output)
    plain_path = resolve_output_path(args.plain_output)

    print(f"Generating local EOD email preview for {today}...")
    rolling_data = build_minimal_rolling_data(today)
    data = ud.build_eod_data(rolling_data, today)
    subject, plain, html = ud.format_eod_email(data)

    html_path.parent.mkdir(parents=True, exist_ok=True)
    plain_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html, encoding="utf-8")
    plain_path.write_text(f"Subject: {subject}\n\n{plain}", encoding="utf-8")

    print(f"Subject: {subject}")
    print(f"HTML preview written to: {html_path}")
    print(f"Plain-text preview written to: {plain_path}")
    print("No email was sent.")


if __name__ == "__main__":
    main()
