#!/usr/bin/env python3
"""
Diagnose Lane 2 attribution for deals closed won on a given PT date.

This is a local test harness for the EOD email idea:
  closed-won today -> lead meetings -> Lane 2 setup title match -> fallback to
  Reactivation - Setter Name when title evidence is missing.

It does not send email and does not write to Close.
"""

import argparse
import csv
import re
import sys
from datetime import date, datetime
from pathlib import Path

import update_dashboard as ud


SCRAPER_TITLE_MAP = [
    (re.compile(r"vendingpren[eu]+rs?\s+-\s+next\s+steps\s+call", re.IGNORECASE), "Charlie Ingram", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+call\s+-\s+next\s+steps", re.IGNORECASE), "Jacob Hepner", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+next\s+steps\s+call", re.IGNORECASE), "Vince Bartolini", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+next\s+steps\s+session", re.IGNORECASE), "Pearl Sathekge", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+discovery\s+-\s+next\s+steps", re.IGNORECASE), "Kelly Schrader", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+-\s+next\s+steps(?!\s+call)", re.IGNORECASE), "Jacob Herbig", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+r\s+next\s+steps", re.IGNORECASE), "William Nowak", "next_steps_title"),
    (re.compile(r"vending\s+discovery\s+call\s+-\s+next\s+steps", re.IGNORECASE), "August Young", "next_steps_title"),
    (re.compile(r"vending\s+discovery\s+-\s+next\s+steps", re.IGNORECASE), "Spencer Reynolds", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+strategy\s*-?\s*next\s+steps", re.IGNORECASE), "Amy Mulch", "next_steps_title"),
    (re.compile(r"vending\s+opportunity\s*-?\s*next\s+steps", re.IGNORECASE), "Cassie Caraballo", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+connect\s*-?\s*next\s+steps", re.IGNORECASE), "Jessica Zatkin", "next_steps_title"),
    (re.compile(r"vending\s+success\s*-?\s*next\s+steps", re.IGNORECASE), "Abigail Garza", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+momentum\s*-?\s*next\s+steps", re.IGNORECASE), "Connor George", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+launch\s*-?\s*next\s+steps", re.IGNORECASE), "Dana Lesiuk", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+pathway\s*-?\s*next\s+steps", re.IGNORECASE), "Naria Torres", "next_steps_title"),
    (re.compile(r"vendingpren[eu]+rs?\s+blueprint\s*-?\s*next\s+steps", re.IGNORECASE), "Melia King", "next_steps_title"),
    # William's second Lane 2 title. This is intentionally surfaced with the
    # rule name so we can inspect whether it conflicts with closer-call titles.
    (re.compile(r"\bvending\s+consult\s+call\b", re.IGNORECASE), "William Nowak", "william_consult_call"),
]

CONFIGURED_SETTERS = {close_name for close_name, _display, _goal in ud.SCRAPER_SETTERS}
DISPLAY_BY_SETTER = {close_name: display for close_name, display, _goal in ud.SCRAPER_SETTERS}


def parse_args():
    parser = argparse.ArgumentParser(description="Report Lane 2 attribution for closed-won deals.")
    parser.add_argument("--date", required=True, help="Closed-won PT date, YYYY-MM-DD.")
    parser.add_argument("--output", help="Optional CSV output path.")
    return parser.parse_args()


def parse_date(raw):
    try:
        return date.fromisoformat(raw)
    except ValueError:
        sys.exit(f"Invalid --date {raw!r}. Use YYYY-MM-DD.")


def parse_dt(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ud.PACIFIC)
    except (ValueError, TypeError):
        return None


def money(cents):
    return (cents or 0) / 100


def format_money(amount):
    if amount >= 1000:
        return f"${amount / 1000:.1f}k"
    return f"${amount:,.0f}"


def fetch_lead(lead_id):
    fields = ",".join([
        "id",
        "display_name",
        "name",
        ud.FIELD_FIRST_SALES_CALL,
        ud.FIELD_FUNNEL_NAME_DEAL,
        ud.FIELD_REACTIVATION_SETTER,
        ud.FIELD_LEAD_OWNER,
    ])
    return ud.close_get(f"lead/{lead_id}", {"_fields": fields})


def fetch_lead_meetings(lead_id):
    meetings = []
    skip = 0
    fields = "id,lead_id,user_id,title,starts_at,date_start,date_created,status"
    while True:
        data = ud.close_get("activity/meeting", {
            "lead_id": lead_id,
            "_fields": fields,
            "_skip": skip,
            "_limit": 100,
        })
        batch = data.get("data", [])
        meetings.extend(batch)
        if not data.get("has_more"):
            break
        skip += len(batch) or 100
    return meetings


def match_lane2_title(title):
    for pattern, setter, rule in SCRAPER_TITLE_MAP:
        if pattern.search(title or ""):
            return setter, rule
    return None, None


def meeting_status_is_active(meeting):
    status = (meeting.get("status") or "").lower()
    title = (meeting.get("title") or "").strip().lower()
    return not status.startswith(("canceled", "cancelled", "declined")) and not title.startswith("canceled")


def choose_lane2_meeting(meetings, report_date):
    matches = []
    for meeting in meetings:
        if not meeting_status_is_active(meeting):
            continue
        setter, rule = match_lane2_title(meeting.get("title") or "")
        if not setter:
            continue
        created_at = parse_dt(meeting.get("date_created"))
        starts_at = parse_dt(meeting.get("starts_at") or meeting.get("date_start"))
        if created_at and created_at.date() > report_date:
            continue
        matches.append({
            "meeting": meeting,
            "setter": setter,
            "rule": rule,
            "created_at": created_at,
            "starts_at": starts_at,
        })

    if not matches:
        return None, []

    # Prefer the latest Lane 2 setup created before the close date. If the lead
    # had multiple setup attempts, this usually reflects the one that led to the
    # won opportunity.
    matches.sort(key=lambda m: m["created_at"] or datetime.min.replace(tzinfo=ud.PACIFIC), reverse=True)
    return matches[0], matches


def confidence_for(match, setter_field, funnel):
    if not match:
        if setter_field in CONFIGURED_SETTERS:
            return "fallback", "no title match; used Reactivation - Setter Name"
        return "none", "no Lane 2 title match or configured setter field"

    title_setter = match["setter"]
    rule = match["rule"]
    if setter_field and setter_field != title_setter:
        return "conflict", f"title says {title_setter}; field says {setter_field}"
    if rule == "william_consult_call" and funnel != "Reactivation Scrapers" and setter_field != "William Nowak":
        return "review", "William consult title without scraper funnel/setter-field confirmation"
    if setter_field == title_setter:
        return "high", "title match agrees with setter field"
    if funnel == "Reactivation Scrapers":
        return "high", "title match on Reactivation Scrapers lead"
    return "medium", "title match only"


def build_rows(report_date):
    user_map = ud.fetch_close_users()
    user_map.update(ud.USER_DISPLAY_OVERRIDES)
    opps = ud.fetch_todays_won_opps(report_date.isoformat())
    rows = []

    for opp in opps:
        lead_id = opp.get("lead_id")
        if not lead_id:
            continue
        lead = fetch_lead(lead_id)
        meetings = fetch_lead_meetings(lead_id)
        match, all_matches = choose_lane2_meeting(meetings, report_date)

        raw_funnel = lead.get(ud.FIELD_FUNNEL_NAME_DEAL) or ""
        funnel = ud.CLOSE_VALUE_TO_FUNNEL.get(raw_funnel, raw_funnel) or "Unknown"
        setter_field = (lead.get(ud.FIELD_REACTIVATION_SETTER) or "").strip()
        confidence, reason = confidence_for(match, setter_field, funnel)
        fallback_setter = setter_field if setter_field in CONFIGURED_SETTERS else ""
        setter = match["setter"] if match else fallback_setter

        created_at = match["created_at"] if match else None
        starts_at = match["starts_at"] if match else None
        first_sales_date = lead.get(ud.FIELD_FIRST_SALES_CALL) or ""
        days_to_close = ""
        if created_at:
            days_to_close = (report_date - created_at.date()).days
        elif first_sales_date:
            try:
                days_to_close = (report_date - date.fromisoformat(first_sales_date)).days
            except ValueError:
                days_to_close = ""

        rows.append({
            "lead_name": lead.get("display_name") or lead.get("name") or lead_id,
            "lead_id": lead_id,
            "closer": user_map.get(opp.get("user_id") or "") or opp.get("user_id") or "",
            "revenue": money(opp.get("value")),
            "funnel": funnel,
            "setter": setter,
            "setter_display": DISPLAY_BY_SETTER.get(setter, setter),
            "setter_field": setter_field,
            "source": "title" if match else ("field_fallback" if fallback_setter else ""),
            "confidence": confidence,
            "reason": reason,
            "set_date": created_at.date().isoformat() if created_at else "",
            "call_date": starts_at.date().isoformat() if starts_at else "",
            "days_to_close": days_to_close,
            "first_sales_call_date": first_sales_date,
            "matched_title": (match["meeting"].get("title") if match else "") or "",
            "match_rule": match["rule"] if match else "",
            "all_lane2_title_matches": len(all_matches),
        })

    return rows


def print_report(rows, report_date):
    total_revenue = sum(r["revenue"] for r in rows)
    lane2_rows = [r for r in rows if r["setter"]]
    lane2_revenue = sum(r["revenue"] for r in lane2_rows)
    print(f"Closed won on {report_date}: {len(rows)} deals, {format_money(total_revenue)}")
    print(f"Lane 2 attributed: {len(lane2_rows)} deals, {format_money(lane2_revenue)}")
    print()
    if not rows:
        return
    print(f"{'Setter':<12} {'Confidence':<10} {'Set':<10} {'Call':<10} {'Days':>4} {'Revenue':>8}  {'Closer':<18} Lead")
    print("-" * 112)
    for r in rows:
        setter = r["setter_display"] or "-"
        set_date = r["set_date"] or "-"
        call_date = r["call_date"] or "-"
        days = str(r["days_to_close"]) if r["days_to_close"] != "" else "-"
        print(
            f"{setter:<12} {r['confidence']:<10} {set_date:<10} {call_date:<10} "
            f"{days:>4} {format_money(r['revenue']):>8}  {r['closer'][:18]:<18} {r['lead_name']}"
        )
        if r["reason"] or r["matched_title"]:
            print(f"  reason: {r['reason']}")
            if r["matched_title"]:
                print(f"  title: {r['matched_title']}")
            if r["setter_field"] and r["setter_field"] != r["setter"]:
                print(f"  setter field: {r['setter_field']}")


def write_csv(rows, output_path):
    if not output_path:
        return
    path = Path(output_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "lead_name", "lead_id", "closer", "revenue", "funnel", "setter",
        "setter_display", "setter_field", "source", "confidence", "reason",
        "set_date", "call_date", "days_to_close", "first_sales_call_date",
        "matched_title", "match_rule", "all_lane2_title_matches",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print()
    print(f"CSV written to: {path}")


def main():
    args = parse_args()
    if not ud.CLOSE_API_KEY:
        sys.exit("CLOSE_API_KEY not set.")
    report_date = parse_date(args.date)
    rows = build_rows(report_date)
    print_report(rows, report_date)
    write_csv(rows, args.output)


if __name__ == "__main__":
    main()
