import unittest
import sys
import types
from datetime import date
from unittest.mock import patch

try:
    import requests  # noqa: F401
except ImportError:
    # Production installs requests; these pure attribution tests need no HTTP.
    requests_stub = types.ModuleType("requests")
    requests_stub.Session = type("Session", (), {"headers": {}})
    sys.modules["requests"] = requests_stub

import update_dashboard as dashboard


class InstagramNextStepsAttributionTests(unittest.TestCase):
    def test_title_only_targets_pearl_session(self):
        self.assertTrue(dashboard.is_instagram_next_steps_title(
            "Vendingpreneurs Next Steps Session with Alex"
        ))
        self.assertFalse(dashboard.is_instagram_next_steps_title(
            "Vendingpreneurs Next Steps Call with Alex"
        ))
        self.assertFalse(dashboard.is_instagram_next_steps_title(
            "Canceled: Vendingpreneurs Next Steps Session with Alex"
        ))

    def test_resolver_assigns_title_to_instagram_and_keeps_pearl_credit(self):
        day = date(2026, 10, 9)
        lead = {
            "id": "lead_test",
            dashboard.FIELD_REACT_SETTER_USER: "user_0SuNg0OWd2reYMeyuDVqiVvjiGcRiFheKKOXXZpyaPZ",
            dashboard.FIELD_FUNNEL_NAME_DEAL: "Reactivation Scrapers",
        }
        meeting = {
            "lead_id": "lead_test",
            "meeting_date": day,
            "title": "Vendingpreneurs Next Steps Session with Alex",
        }
        with patch.object(dashboard, "get_setter_user_keys", return_value=[dashboard.FIELD_REACT_SETTER_USER]), patch.object(
            dashboard, "fetch_close_users", return_value={}
        ):
            records = dashboard.resolve_scraper_meetings([meeting], {"lead_test": lead})
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["setter"], "Pearl Sathekge")
        self.assertEqual(records[0]["funnel"], "Instagram (Mike)")

    def test_meeting_counts_once_under_instagram_instead_of_scrapers(self):
        day = date(2026, 10, 9)
        lead = {
            "id": "lead_test",
            "status_id": "active",
            dashboard.FIELD_FIRST_SALES_CALL: day.isoformat(),
            dashboard.FIELD_FUNNEL_NAME_DEAL: "Reactivation Scrapers",
        }
        meeting = {
            "date": day,
            "lead_id": "lead_test",
            "setter": "Pearl Sathekge",
            "status_id": "active",
            "funnel": "Instagram (Mike)",
        }
        result = dashboard.build_dashboard_data(
            [lead], [day], scraper_meetings=[meeting]
        )
        self.assertEqual(result["daily_data"][day]["booked"], 1)
        self.assertEqual(result["daily_data"][day]["funnels"], {"Instagram (Mike)": 1})
        self.assertEqual(result["setter_data"], {})
        detail = dashboard.build_funnel_detail(
            result, [], {}, [day], ["Instagram"], "Instagram"
        )
        self.assertEqual(detail[day]["closer"], 1)

    def test_repeat_meetings_count_once_each_without_lead_row(self):
        day = date(2026, 10, 9)
        next_day = date(2026, 10, 10)
        lead = {
            "id": "lead_test",
            "status_id": "active",
            dashboard.FIELD_FIRST_SALES_CALL: day.isoformat(),
            dashboard.FIELD_FUNNEL_NAME_DEAL: "Instagram",
        }
        meeting = {
            "date": day,
            "lead_id": "lead_test",
            "setter": "Pearl Sathekge",
            "status_id": "active",
            "funnel": "Instagram (Mike)",
        }
        repeat_meeting = dict(meeting, date=next_day)
        result = dashboard.build_dashboard_data(
            [lead], [day, next_day], scraper_meetings=[meeting, repeat_meeting]
        )
        self.assertEqual(result["daily_data"][day]["booked"], 1)
        self.assertEqual(result["daily_data"][day]["funnels"], {"Instagram (Mike)": 1})
        self.assertEqual(result["daily_data"][next_day]["booked"], 1)
        self.assertEqual(result["daily_data"][next_day]["funnels"], {"Instagram (Mike)": 1})


if __name__ == "__main__":
    unittest.main()
