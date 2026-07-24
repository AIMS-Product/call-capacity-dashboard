#!/usr/bin/env python3
"""
diagnose_lost_deals.py — Audit who is moving leads to 💔 Lost and whether
they're setting a Lost Reason.

For a given date range (PT days), this script:
  1. Pulls every lead → 💔 Lost status change via /activity/status_change/lead/
     (same endpoint the EOD email's Closed Lost section uses)
  2. Captures WHO made each change (the status-change activity's user_id —
     this is the piece Close smart views can't surface)
  3. Fetches each lead's display name, Lost Reason, and Lead Owner
  4. Prints a per-lead detail list (missing-reason leads flagged + Close links)
  5. Prints two coaching summaries:
       - by MOVER  (who flipped the status): total moved · # missing reason · %
       - by OWNER  (who owns the lead):      total lost  · # missing reason · %

Dedupe: if a lead bounced Lost → Open → Lost within the range, only the
LATEST transition is kept (that's the state and actor that stuck).

Read-only. Doesn't send email or modify anything.

Usage (locally):
  CLOSE_API_KEY=xxx python diagnose_lost_deals.py                # today
  CLOSE_API_KEY=xxx START_DATE=2026-07-17 python diagnose_lost_deals.py
  CLOSE_API_KEY=xxx START_DATE=2026-07-17 END_DATE=2026-07-23 python diagnose_lost_deals.py

Usage (GitHub Actions):
  Actions → "Diagnose Lost Deals" → Run workflow.
  Optional inputs: start_date / end_date (YYYY-MM-DD, PT). Both blank = today.
"""

import os
import sys
from datetime import datetime, timedelta, date, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import update_dashboard as ud

NO_REASON = "(NO REASON GIVEN)"


def parse_date_env(name, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        print(f"❌ {name}={raw!r} is not YYYY-MM-DD.")
        sys.exit(1)


def fetch_lost_changes(start_d, end_d):
    """All lead→Lost status changes in [start_d, end_d] (PT days, inclusive).
    Returns {lead_id: {"changed_at", "changed_by_uid"}} keeping the LATEST
    transition per lead."""
    day_start = datetime(start_d.year, start_d.month, start_d.day, tzinfo=ud.PACIFIC)
    day_end   = datetime(end_d.year, end_d.month, end_d.day, tzinfo=ud.PACIFIC) + timedelta(days=1)
    start_utc = day_start.astimezone(timezone.utc).isoformat()
    end_utc   = day_end.astimezone(timezone.utc).isoformat()

    latest = {}  # lead_id -> {"changed_at", "changed_by_uid"}
    skip = 0
    while True:
        data = ud.close_get("activity/status_change/lead", {
            "date_created__gte": start_utc,
            "date_created__lt":  end_utc,
            "_limit":            100,
            "_skip":             skip,
        })
        batch = data.get("data", [])
        for sc in batch:
            if sc.get("new_status_label") != ud.LOST_STATUS_LABEL:
                continue
            lid = sc.get("lead_id")
            if not lid:
                continue
            changed_at = sc.get("date_created") or ""
            prev = latest.get(lid)
            if prev is None or changed_at > prev["changed_at"]:
                latest[lid] = {
                    "changed_at":     changed_at,
                    "changed_by_uid": sc.get("user_id") or sc.get("created_by") or "",
                }
        if not data.get("has_more"):
            break
        skip += len(batch) or 100
    return latest


def main():
    today   = datetime.now(ud.PACIFIC).date()
    start_d = parse_date_env("START_DATE", today)
    end_d   = parse_date_env("END_DATE", start_d)
    if end_d < start_d:
        print("❌ END_DATE is before START_DATE.")
        sys.exit(1)

    rng = f"{start_d}" if start_d == end_d else f"{start_d} → {end_d}"
    print(f"═══ Lost Deals Audit — {rng} (PT) ═══\n")

    user_map = ud.fetch_close_users()
    print(f"Resolved {len(user_map)} Close users for name lookup")

    changes = fetch_lost_changes(start_d, end_d)
    print(f"Found {len(changes)} unique leads moved to {ud.LOST_STATUS_LABEL} in range\n")
    if not changes:
        print("Nothing to audit. Done.")
        return

    fields = ",".join([
        "id", "display_name", "name",
        f"custom.{ud.CF_LOST_REASON}",
        f"custom.{ud.CF_LEAD_OWNER_NAME}",
        f"custom.{ud.CF_FUNNEL_DEAL}",
    ])

    rows = []
    for lid, ch in changes.items():
        try:
            lead = ud.close_get(f"lead/{lid}", {"_fields": fields})
        except Exception as e:
            print(f"  ⚠ Could not fetch lead {lid}: {e}")
            continue
        owner_uid = lead.get(f"custom.{ud.CF_LEAD_OWNER_NAME}") or ""
        rows.append({
            "lead_id":    lid,
            "name":       lead.get("display_name") or lead.get("name") or "(no name)",
            "reason":     (lead.get(f"custom.{ud.CF_LOST_REASON}") or "").strip() or NO_REASON,
            "funnel":     (lead.get(f"custom.{ud.CF_FUNNEL_DEAL}") or "").strip() or "(no funnel)",
            "owner":      user_map.get(owner_uid) or (owner_uid[:14] + "…" if owner_uid else "(no owner)"),
            "mover":      user_map.get(ch["changed_by_uid"]) or (ch["changed_by_uid"][:14] + "…" if ch["changed_by_uid"] else "(unknown)"),
            "changed_at": ch["changed_at"][:16].replace("T", " "),
        })

    # ── Per-lead detail — missing-reason leads first ─────────────────────────
    rows.sort(key=lambda r: (r["reason"] != NO_REASON, r["mover"].lower(), r["changed_at"]))
    print("─" * 100)
    print(f"{'Lead':<30} {'Moved by':<18} {'Owner':<18} {'Reason':<28} Changed (UTC)")
    print("─" * 100)
    for r in rows:
        flag = "🚩 " if r["reason"] == NO_REASON else "   "
        print(f"{flag}{r['name'][:28]:<28} {r['mover'][:17]:<18} {r['owner'][:17]:<18} "
              f"{r['reason'][:27]:<28} {r['changed_at']}")
        print(f"     ↳ {r['funnel']}  ·  https://app.close.com/lead/{r['lead_id']}/")
    print("─" * 100)

    # ── Coaching summaries ───────────────────────────────────────────────────
    def summarize(key, title):
        agg = {}
        for r in rows:
            k = r[key]
            agg.setdefault(k, {"total": 0, "missing": 0})
            agg[k]["total"] += 1
            if r["reason"] == NO_REASON:
                agg[k]["missing"] += 1
        print(f"\n═══ {title} ═══")
        print(f"{'':<22} {'Moved':>6} {'No reason':>10} {'%':>6}")
        for k, v in sorted(agg.items(), key=lambda kv: (-kv[1]["missing"], -kv[1]["total"], kv[0].lower())):
            pct = f"{v['missing']/v['total']*100:.0f}%" if v["total"] else "—"
            marker = " ← coach" if v["missing"] > 0 else ""
            print(f"{k[:21]:<22} {v['total']:>6} {v['missing']:>10} {pct:>6}{marker}")

    summarize("mover", "By MOVER (who flipped the status)")
    summarize("owner", "By OWNER (who owns the lead)")

    missing_total = sum(1 for r in rows if r["reason"] == NO_REASON)
    print(f"\n═══ {len(rows)} lost leads · {missing_total} missing a reason "
          f"({missing_total/len(rows)*100:.0f}%) ═══")


if __name__ == "__main__":
    main()
