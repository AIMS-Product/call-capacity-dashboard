"""Resolve booking credit from the actual meeting without changing counting rules."""
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

from first_call_title_rules import classify_meeting

PACIFIC = ZoneInfo("America/Los_Angeles")
FIRST_CALL_TIERS = frozenset({
    "closer", "post_webinar", "scraper", "vendhub_consultation",
    "vendhub_nextsteps", "react_email", "quick_discovery",
})


def meeting_day(meeting):
    raw = meeting.get("starts_at") or meeting.get("activity_at") or meeting.get("date_start")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(PACIFIC).date().isoformat()
    except (ValueError, TypeError):
        return None


class MeetingSnapshot:
    """One complete run history shared by all dashboard meeting readers."""

    def __init__(self, meetings):
        self.meetings = deepcopy(meetings)
        self.by_lead = defaultdict(list)
        seen = set()
        for meeting in self.meetings:
            identity = meeting.get("id")
            if not identity or identity in seen:
                raise ValueError("Meeting history has missing or duplicate activity IDs")
            seen.add(identity)
            self.by_lead[meeting.get("lead_id")].append(meeting)

    def read_page(self, params=None):
        params = params or {}
        rows = self.by_lead.get(params["lead_id"], []) if params.get("lead_id") else self.meetings
        offset, limit = int(params.get("_skip", 0)), int(params.get("_limit", 100))
        return {"data": deepcopy(rows[offset:offset + limit]), "has_more": offset + limit < len(rows)}

    def first_call_closer(self, lead_id, first_date):
        matches = [m for m in self.by_lead.get(lead_id, [])
                   if meeting_day(m) == first_date and classify_meeting(m)[0] in FIRST_CALL_TIERS]
        return self._unique_closer(matches)

    def scraper_closer(self, record):
        """Also upgrades older last-good cache records without owner fallback."""
        day = record["date"].isoformat()
        matches = [m for m in self.by_lead.get(record["lead_id"], [])
                   if meeting_day(m) == day and (m.get("title") or "") == record["title"]]
        return self._unique_closer(matches)

    @staticmethod
    def _unique_closer(matches):
        if not matches:
            return "", "no_matching_meeting"
        closers = {m.get("user_id") for m in matches}
        if None in closers or "" in closers:
            return "", "missing_meeting_closer"
        if len(closers) != 1:
            return "", "conflicting_meeting_closers"
        return next(iter(closers)), "resolved"
