import unittest
from unittest.mock import patch
from datetime import date
import update_dashboard as dashboard
import first_call_title_rules as classifier
from appointment_closer import MeetingSnapshot
from copy import deepcopy


def build(dashboard, leads, scrapers, dates, today, totals, categories, snapshot=None):
    categories = deepcopy(categories)
    result = dashboard.build_dashboard_data(deepcopy(leads), dates, today=today,
        lane_reps=dashboard.ALL_LANE_REPS, lane_label="Team", rep_total_meetings=deepcopy(totals),
        rep_meetings_by_category=categories, scraper_meetings=deepcopy(scrapers), appointment_meetings=snapshot)
    result["rep_meetings_by_category"] = categories
    return result


DAY = date(2026, 11, 12)
ROBIN = "user_7F059xEinVentOEvkRMP77fWZyvwUiTRTUOuhD11J0e"
NARIA = "user_PBMfAYkPSkMaYK58gXuG70Vu1SLd2bsG3Mvys6RZNgY"
SCOTT = "user_F0VeLnOQlWpkDncNW8rBl1V2QJ08fnDt6DcUjNATUJK"


def lead(owner=ROBIN, **extra):
    return {"id": "lead_test", "display_name": "Fixture", "status_id": "active",
            dashboard.FIELD_FIRST_SALES_CALL: DAY.isoformat(),
            dashboard.FIELD_FUNNEL_NAME_DEAL: "YouTube", dashboard.FIELD_LEAD_OWNER: owner, **extra}


def meeting(closer=ROBIN, **extra):
    return {"id": "meeting_test", "lead_id": "lead_test", "user_id": closer,
            "title": "Vending Consult Call", "status": "completed",
            "starts_at": "2026-11-12T19:00:00Z", "date_created": "2026-11-10T19:00:00Z", **extra}


class AttributionTests(unittest.TestCase):
    def compare(self, record, meetings):
        baseline = build(dashboard, [record], [], [DAY], DAY, {}, {})
        snapshot = MeetingSnapshot(meetings)
        closer, resolution = snapshot.first_call_closer(record["id"], record[dashboard.FIELD_FIRST_SALES_CALL])
        audit = [{"resolution": resolution}]
        candidate = build(dashboard, [record], [], [DAY], DAY, {}, {}, snapshot)
        return baseline, candidate, audit

    def test_reassignment_to_setter_restores_original_closer_booking(self):
        before, after, _ = self.compare(lead(NARIA), [meeting()])
        self.assertEqual(before["daily_data"][DAY]["booked"], 0)
        self.assertEqual(after["rep_data"][ROBIN][DAY], {"YouTube": 1})

    def test_matching_ownership_keeps_all_calculated_data_identical(self):
        before, after, _ = self.compare(lead(), [meeting()])
        self.assertEqual(before, after)

    def test_no_show_and_canceled_activity_do_not_add_new_first_date_filters(self):
        for attrs in ({"outcome": "No Show"}, {"status": "canceled"}):
            before, after, _ = self.compare(lead(), [meeting(**attrs)])
            self.assertEqual(before, after)
            self.assertEqual(after["daily_data"][DAY]["booked"], 1)

    def test_canceled_lead_is_excluded_in_both_versions(self):
        before, after, _ = self.compare(lead(status_id=next(iter(dashboard.EXCLUDED_LEAD_STATUS_IDS))), [meeting()])
        self.assertEqual(before["daily_data"][DAY]["booked"], 0)
        self.assertEqual(after["daily_data"][DAY]["booked"], 0)

    def test_duplicates_on_same_closer_do_not_duplicate_first_date_credit(self):
        _, after, audit = self.compare(lead(), [meeting(), meeting(id="copy")])
        self.assertEqual(after["daily_data"][DAY]["booked"], 1)
        self.assertEqual(audit[0]["resolution"], "resolved")

    def test_conflicting_closers_are_visible_and_never_fall_back_to_owner(self):
        _, after, audit = self.compare(lead(), [meeting(), meeting(SCOTT, id="second")])
        self.assertEqual(audit[0]["resolution"], "conflicting_meeting_closers")
        self.assertEqual(after["daily_data"][DAY]["booked"], 0)

    def test_wrong_date_and_followups_do_not_supply_closer(self):
        for source in (meeting(starts_at="2026-11-13T19:00:00Z"), meeting(title="Follow Up")):
            self.assertEqual(MeetingSnapshot([source]).first_call_closer("lead_test", DAY.isoformat())[1], "no_matching_meeting")

    def test_existing_consultation_title_retains_upstream_classification(self):
        self.assertEqual(MeetingSnapshot([meeting(title="Maya and Vendingprenuers Consultation")])
                         .first_call_closer("lead_test", DAY.isoformat()), (ROBIN, "resolved"))

    def test_snapshot_pagination_and_transport_reuse_are_complete(self):
        snapshot = MeetingSnapshot([meeting(), meeting(SCOTT, id="second", lead_id="lead_other")])
        with patch.object(dashboard, "_meeting_snapshot", snapshot), \
             patch.object(dashboard.session, "get", side_effect=AssertionError("network read")):
            self.assertTrue(dashboard.close_get("activity/meeting", {"_limit": 1})["has_more"])
            self.assertEqual(dashboard.close_get("activity/meeting/", {"lead_id": "lead_other"})["data"][0]["user_id"], SCOTT)
            self.assertFalse(dashboard.close_get("activity/meeting", {"_skip": 1, "_limit": 1})["has_more"])

    def test_old_scraper_cache_resolves_meeting_closer_without_lead_owner(self):
        snapshot = MeetingSnapshot([meeting(title="Next Steps")])
        self.assertEqual(snapshot.scraper_closer({"lead_id": "lead_test", "date": DAY,
                         "title": "Next Steps", "lead_owner": NARIA}), (ROBIN, "resolved"))

    def test_duplicate_history_identity_is_rejected(self):
        with self.assertRaises(ValueError):
            MeetingSnapshot([meeting(), meeting()])

    def test_scraper_totals_setter_credit_and_repeat_meetings_are_preserved(self):
        records = [{"lead_id": "lead_test", "date": DAY, "title": "Next Steps", "setter": "Naria Torres",
                    "lead_owner": NARIA, "status_id": "active", "display_name": "Fixture"} for _ in range(2)]
        raw = [{"lead_id": "lead_test", "meeting_date": DAY, "title": "Next Steps", "user_id": ROBIN,
                "meeting_id": str(i)} for i in range(2)]
        records = [{**row, "appointment_closer": ROBIN, "meeting_id": str(i)} for i, row in enumerate(records)]
        before = build(dashboard, [], records, [DAY], DAY, {}, {})
        after = build(dashboard, [], records, [DAY], DAY, {}, {}, MeetingSnapshot([]))
        self.assertEqual(before["daily_data"], after["daily_data"])
        self.assertEqual(before["setter_data"], after["setter_data"])
        self.assertEqual(after["rep_data"][ROBIN][DAY], {"Reactivation Scrapers": 2})


if __name__ == "__main__":
    unittest.main()
