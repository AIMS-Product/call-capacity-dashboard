import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from datetime import date
from unittest.mock import patch

from lane2_eod_roster import COMPANY_ID, EmailRoster, booked_goal, verified_snapshot
import update_dashboard as dashboard
import preview_eod_email as preview


DAY = date(2026, 11, 13)


def rep(uid="user_new", name="New Rep", **overrides):
    result = {
        "providerUserId": uid, "status": "active", "includedInReports": True,
        "includedInDashboard": True, "startDate": "2026-11-02", "exitDate": None,
        "configuration": {"attributionName": name, "setterAliases": [name],
                          "offer": "Vendingpreneurs (VP)", "repType": "full",
                          "titleRules": [], "dailyBookedGoal": None},
    }
    result.update(overrides)
    return result


def roster(accepted, saved=None):
    return EmailRoster.from_snapshots({"reps": accepted}, {"reps": saved if saved is not None else accepted},
                                     DAY, "191", "97", "98")


class RosterTests(unittest.TestCase):
    def test_saved_departure_removes_immediately_but_new_draft_is_not_admitted(self):
        original = rep()
        departed = rep(status="inactive", includedInReports=False, includedInDashboard=False)
        result = roster([original], [departed, rep("user_draft", "Draft Rep")])
        self.assertEqual(result.current_ids, set())
        self.assertEqual(len(result.reps), 1)

    def test_active_status_does_not_override_departure_date_or_visibility(self):
        rows = [rep("user_exit", exitDate="2026-11-12"), rep("user_hidden", includedInReports=False),
                rep("user_future", startDate="2026-11-16"), rep("user_manual", providerUserId=None), rep()]
        self.assertEqual(roster(rows).current_ids, {"user_new"})

    def test_duplicate_provider_id_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            roster([rep(), rep()])

    def test_explicit_zero_and_ramp_goals(self):
        row = rep()
        self.assertEqual(booked_goal(row, DAY), 1)
        row["configuration"]["dailyBookedGoal"] = 0
        self.assertEqual(booked_goal(row, DAY), 0)
        row["configuration"]["dailyBookedGoal"] = 4
        self.assertEqual(booked_goal(row, DAY), 4)
        self.assertEqual(booked_goal(row, date(2026, 11, 14)), 0)

    def test_part_time_ramp_and_reset(self):
        row = rep(startDate="2026-08-03")
        row["configuration"].update(repType="part_time", rampResetDates=["2026-11-02"])
        self.assertEqual(booked_goal(row, DAY), 0.5)
        self.assertEqual(booked_goal(row, date(2026, 11, 20)), 1)

    def test_current_and_former_sections_preserve_recorded_activity(self):
        departed = rep("user_gone", "Former Rep", status="inactive")
        current = rep()
        current["configuration"]["offer"] = "Acquisition Ace (AA)"
        result = roster([current, departed])
        sections = result.sections({"user_gone": {"set": 1, "booked": 2, "shown": 1}})
        self.assertIn("Acquisition Ace", sections[0]["title"])
        self.assertEqual(sections[0]["lines"][0]["name"], "New Rep")
        self.assertIn("Former / other", sections[1]["title"])
        self.assertEqual(sections[1]["lines"][0]["rate"], 50)
        self.assertEqual(sections[1]["lines"][0]["goal"], 0)

    def test_new_identity_and_alias_resolve_without_static_roster(self):
        result = roster([rep()])
        self.assertEqual(result.resolve("user_new", "", "", {}, "booked"), "user_new")
        self.assertEqual(result.resolve(None, "new REP", "", {}, "booked"), "user_new")
        self.assertIsNone(result.resolve(None, "New", "", {}, "booked"))

    def test_title_scope_and_required_setter(self):
        result = roster([rep()])
        rules = {"Next Steps": [{"provider_user_id": "user_new", "scope": "booked", "requiredSetter": "Legacy Name"}]}
        self.assertEqual(result.resolve(None, "Legacy Name", "Next Steps", rules, "booked"), "user_new")
        self.assertIsNone(result.resolve(None, "Other Rep", "Next Steps", rules, "booked"))
        self.assertIsNone(result.resolve(None, "Legacy Name", "Next Steps", rules, "resolved"))

    def test_counts_keep_per_meeting_attendance_and_per_lead_sets(self):
        result = roster([rep()])
        meeting = {"lead_id": "lead_test", "title": "Next Steps"}
        lead = {"lead_test": {f"custom.{dashboard.CF_REACT_SETTER}": "New Rep",
                              f"custom.{dashboard.CF_SHOW_UP}": "Yes"}}
        with patch.object(result, "match_titles", return_value={}), \
             patch.object(dashboard, "get_setter_user_keys", return_value=[dashboard.FIELD_REACT_SETTER_USER]):
            sections = dashboard.build_lane2_booking_sections(result, [meeting, meeting], [meeting, meeting], lead)
        row = sections[0]["lines"][0]
        self.assertEqual((row["booked"], row["shown"], row["set"]), (2, 2, 1))

    def test_snapshot_integrity_and_tenant_checks(self):
        document = {"companyId": COMPANY_ID, "schemaVersion": "lane2.configuration.v1", "reps": []}
        raw = json.dumps(document)
        row = {"canonical_json": raw, "snapshot_sha256": hashlib.sha256(raw.encode()).hexdigest(),
               "reporting_canonical_json": raw, "reporting_sha256": hashlib.sha256(raw.encode()).hexdigest()}
        self.assertEqual(verified_snapshot(row, ""), document)
        for field in ("snapshot_sha256", "reporting_sha256"):
            corrupt = dict(row, **{field: "0" * 64})
            with self.assertRaisesRegex(ValueError, "integrity"):
                verified_snapshot(corrupt, "")
        wrong = copy.deepcopy(document)
        wrong["companyId"] = "other-company"
        row["canonical_json"] = json.dumps(wrong)
        row["snapshot_sha256"] = hashlib.sha256(row["canonical_json"].encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "tenant"):
            verified_snapshot(row, "")

    def test_email_stops_before_api_work_if_lakebase_is_unavailable(self):
        with patch.object(dashboard, "load_email_roster", side_effect=RuntimeError("No accepted roster")), \
             patch.object(dashboard, "fetch_close_users") as fetch:
            with self.assertRaisesRegex(RuntimeError, "No accepted"):
                dashboard.build_eod_data({}, DAY)
            fetch.assert_not_called()

    def test_sender_never_sends_a_stale_roster_when_lakebase_is_unavailable(self):
        with patch.object(dashboard, "load_email_roster", side_effect=RuntimeError("No accepted roster")), \
             patch.object(dashboard, "GMAIL_APP_PASSWORD", "test"), \
             patch.object(dashboard, "EMAIL_FROM", "sender@example.com"), \
             patch("smtplib.SMTP_SSL") as smtp:
            dashboard.send_eod_email({}, DAY, ["recipient@example.com"])
        smtp.assert_not_called()

    def test_preview_renders_dynamic_roster_and_evidence_without_sending(self):
        result = roster([rep(name="New <Rep>")])
        data = dict(today=DAY, revenue=0, deals=0, today_count=0, tomorrow_count=0,
                    show_rate=0, closer_counts={}, icp_lines=[], lost_groups=[],
                    rep_breakdown_today=[], vendhub_lines=[],
                    lane2_sections=result.sections({}), lane2_roster=result.evidence())
        module = SimpleNamespace(CLOSE_API_KEY="test", PACIFIC=dashboard.PACIFIC,
                                 load_email_roster=lambda day: result,
                                 build_eod_data=lambda *args, **kwargs: data,
                                 format_eod_email=dashboard.format_eod_email)
        with TemporaryDirectory() as directory:
            html = Path(directory) / "preview.html"
            plain = Path(directory) / "preview.txt"
            args = SimpleNamespace(date=DAY.isoformat(), output=str(html), plain_output=str(plain))
            with patch.object(preview, "parse_args", return_value=args), \
                 patch.object(preview, "load_email_modules", return_value=module), \
                 patch.object(preview, "build_preview_rolling_data", return_value=({}, object())), \
                 patch("smtplib.SMTP_SSL") as smtp:
                preview.main()
            smtp.assert_not_called()
            self.assertIn("New &lt;Rep&gt;", html.read_text())
            self.assertIn("New <Rep>", plain.read_text())
            self.assertNotIn("TLG setter bookings", plain.read_text())
            self.assertEqual(json.loads(html.with_suffix(".roster.json").read_text())["configuration_version"], "97")


if __name__ == "__main__":
    unittest.main()
