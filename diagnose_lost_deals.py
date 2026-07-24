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


def build_summary(rows, key):
    """Aggregate rows by mover or owner → sorted [(name, total, missing, pct)]."""
    agg = {}
    for r in rows:
        k = r[key]
        agg.setdefault(k, {"total": 0, "missing": 0})
        agg[k]["total"] += 1
        if r["reason"] == NO_REASON:
            agg[k]["missing"] += 1
    out = []
    for k, v in sorted(agg.items(), key=lambda kv: (-kv[1]["missing"], -kv[1]["total"], kv[0].lower())):
        pct = (v["missing"] / v["total"] * 100) if v["total"] else 0
        out.append((k, v["total"], v["missing"], pct))
    return out


def render_markdown(rows, rng, mover_sum, owner_sum):
    missing_total = sum(1 for r in rows if r["reason"] == NO_REASON)
    md = []
    md.append(f"# Lost Deals Audit — {rng}")
    md.append("")
    md.append(f"**{len(rows)} leads moved to 💔 Lost · {missing_total} missing a reason "
              f"({missing_total/len(rows)*100:.0f}%)**")
    md.append("")
    md.append("## By Mover (who flipped the status)")
    md.append("")
    md.append("| Mover | Moved to Lost | No Reason | % Missing |")
    md.append("|---|---:|---:|---:|")
    for name, total, missing, pct in mover_sum:
        flag = " 🚩" if missing > 0 else ""
        md.append(f"| {name}{flag} | {total} | {missing} | {pct:.0f}% |")
    md.append("")
    md.append("## By Owner (who owns the lead)")
    md.append("")
    md.append("| Owner | Leads Lost | No Reason | % Missing |")
    md.append("|---|---:|---:|---:|")
    for name, total, missing, pct in owner_sum:
        flag = " 🚩" if missing > 0 else ""
        md.append(f"| {name}{flag} | {total} | {missing} | {pct:.0f}% |")
    md.append("")
    md.append("## Lead Detail")
    md.append("")
    md.append("_Missing-reason leads listed first._")
    md.append("")
    md.append("| | Lead | Moved By | Owner | Reason | Funnel | Changed (UTC) |")
    md.append("|---|---|---|---|---|---|---|")
    for r in rows:
        flag = "🚩" if r["reason"] == NO_REASON else ""
        lead_link = f"[{r['name']}](https://app.close.com/lead/{r['lead_id']}/)"
        md.append(f"| {flag} | {lead_link} | {r['mover']} | {r['owner']} | "
                  f"{r['reason']} | {r['funnel']} | {r['changed_at']} |")
    md.append("")
    md.append(f"_Generated {datetime.now(ud.PACIFIC).strftime('%Y-%m-%d %I:%M %p PT')} · "
              f"read-only audit via Close API status-change records_")
    return "\n".join(md)


def render_html(rows, rng, mover_sum, owner_sum):
    missing_total = sum(1 for r in rows if r["reason"] == NO_REASON)

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def sum_table(title, label, data):
        trs = ""
        for name, total, missing, pct in data:
            color = "#a02929" if missing > 0 else "#333"
            coach = ' <span style="color:#a02929;font-size:12px;">← coach</span>' if missing > 0 else ""
            trs += (f'<tr><td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;color:{color};">{esc(name)}{coach}</td>'
                    f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:right;">{total}</td>'
                    f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:right;color:{color};font-weight:700;">{missing}</td>'
                    f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;text-align:right;">{pct:.0f}%</td></tr>')
        return (f'<h2 style="font-size:14px;color:#1b5e1b;border-left:3px solid #1b5e1b;padding-left:8px;'
                f'text-transform:uppercase;letter-spacing:0.08em;">{title}</h2>'
                f'<table style="border-collapse:collapse;font-size:14px;min-width:480px;">'
                f'<tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">{label}</th>'
                f'<th style="text-align:right;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">Total</th>'
                f'<th style="text-align:right;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">No Reason</th>'
                f'<th style="text-align:right;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">% Missing</th></tr>'
                f'{trs}</table>')

    detail_trs = ""
    for r in rows:
        missing = r["reason"] == NO_REASON
        rstyle  = "background:#fdf5f5;" if missing else ""
        rcolor  = "#a02929" if missing else "#555"
        flag    = "🚩 " if missing else ""
        detail_trs += (
            f'<tr style="{rstyle}">'
            f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">{flag}'
            f'<a href="https://app.close.com/lead/{r["lead_id"]}/" style="color:#1b5e1b;">{esc(r["name"])}</a></td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">{esc(r["mover"])}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;">{esc(r["owner"])}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;color:{rcolor};">{esc(r["reason"])}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;color:#888;">{esc(r["funnel"])}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #f0f0f0;color:#888;white-space:nowrap;">{r["changed_at"]}</td>'
            f'</tr>')

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Lost Deals Audit — {esc(rng)}</title></head>
<body style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#333;max-width:1000px;margin:24px auto;padding:0 16px;">
<div style="background:#173317;color:#fff;padding:20px 28px;border-radius:8px;">
  <div style="font-size:11px;letter-spacing:0.15em;text-transform:uppercase;opacity:0.8;">Lost Deals Audit</div>
  <div style="font-size:24px;font-weight:800;margin-top:4px;">{esc(rng)}</div>
  <div style="margin-top:8px;font-size:14px;">{len(rows)} leads moved to 💔 Lost ·
    <span style="font-weight:800;color:#ffb3b3;">{missing_total} missing a reason ({missing_total/len(rows)*100:.0f}%)</span></div>
</div>
{sum_table("By Mover — who flipped the status", "Mover", mover_sum)}
{sum_table("By Owner — who owns the lead", "Owner", owner_sum)}
<h2 style="font-size:14px;color:#1b5e1b;border-left:3px solid #1b5e1b;padding-left:8px;text-transform:uppercase;letter-spacing:0.08em;">Lead Detail — missing reasons first</h2>
<table style="border-collapse:collapse;font-size:13px;width:100%;">
<tr><th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">Lead</th>
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">Moved By</th>
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">Owner</th>
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">Reason</th>
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">Funnel</th>
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #ddd;color:#888;font-size:12px;">Changed (UTC)</th></tr>
{detail_trs}
</table>
<p style="color:#999;font-size:12px;margin-top:20px;">Generated {datetime.now(ud.PACIFIC).strftime('%Y-%m-%d %I:%M %p PT')} · read-only audit via Close API status-change records</p>
</body></html>"""


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
    mover_sum = build_summary(rows, "mover")
    owner_sum = build_summary(rows, "owner")

    def print_summary(title, data):
        print(f"\n═══ {title} ═══")
        print(f"{'':<22} {'Moved':>6} {'No reason':>10} {'%':>6}")
        for name, total, missing, pct in data:
            marker = " ← coach" if missing > 0 else ""
            print(f"{name[:21]:<22} {total:>6} {missing:>10} {pct:>5.0f}%{marker}")

    print_summary("By MOVER (who flipped the status)", mover_sum)
    print_summary("By OWNER (who owns the lead)", owner_sum)

    missing_total = sum(1 for r in rows if r["reason"] == NO_REASON)
    print(f"\n═══ {len(rows)} lost leads · {missing_total} missing a reason "
          f"({missing_total/len(rows)*100:.0f}%) ═══")

    # ── Shareable report files ───────────────────────────────────────────────
    os.makedirs("reports", exist_ok=True)
    stem = f"lost_deals_audit_{start_d}" if start_d == end_d else f"lost_deals_audit_{start_d}_to_{end_d}"
    md_path   = os.path.join("reports", stem + ".md")
    html_path = os.path.join("reports", stem + ".html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(rows, rng, mover_sum, owner_sum))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(rows, rng, mover_sum, owner_sum))
    print(f"\n📄 Wrote {md_path} and {html_path}")
    print("   (In GitHub Actions these are uploaded as the 'lost-deals-audit' artifact —")
    print("    download from the run's Summary page.)")


if __name__ == "__main__":
    main()
