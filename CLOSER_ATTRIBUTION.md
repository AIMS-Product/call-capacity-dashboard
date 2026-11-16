# Call Capacity attribution — November 15, 2026

The live refresh, day-detail panel, rep breakdown, missed-window calculation,
and newly generated weekly/monthly summaries credit the closer recorded on the
call, rather than the lead's current owner. Existing saved archives are untouched.

First-date bookings still use First Sales Call Booked Date. The meeting on that
Pacific date is resolved using the existing field updater's qualifying-title
rules, pinned from `close-first-sales-meeting` commit `46427f98fc8a`. The pure
classifier and its title roster are retained in `first_call_title_rules.py` and
`first_call_roster.py`. These files perform no CRM writes or network calls.
Future changes to upstream first-call title recognition should update these
pinned rules together.

All existing funnel mappings, date rules, lead-status exclusions, meeting
cancellation handling, closer rosters, funnel restrictions, goals, capacity,
scraper setter credit and repeat-booking rules are preserved. Scrapers retain
their existing team inclusion; their rep credit uses the actual meeting closer.
The existing separate first-date and scraper entries can still count on the
same lead/date. This release does not introduce MTD outcome rules or new deduping.

One complete meeting history is captured before calculating the dashboard and
reused for all meeting readers in that run. Duplicate identities or incomplete
pagination stop the refresh before publication. Duplicate copies with one
closer supply one first-date credit. Missing or conflicting closer identities
are logged for review without falling back to Lead Owner. Older scraper caches
resolve their meeting closer from this same history.

The local candidate was replayed against the release using the same captured
inputs. Daily, funnel, rep, setter and counted-item results match exactly:
103 → 107 booking entries, Thursday 18 → 21, Friday 11 → 11, and Luke 16 → 23.
Those figures describe the reviewed snapshot; subsequent refreshes use live data.
