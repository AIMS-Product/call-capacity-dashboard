"""Read SteelTrap's accepted Lane 2 roster; never fall back to a static list."""

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta


COMPANY_ID = "88a28173-2a61-4cbb-92ea-f6b8be4592f3"
FULL_TIME_BOOKED_GOALS = (1, 1, 2, 3)
PART_TIME_BOOKED_GOALS = (1, 0.5, 1, 1)


@contextmanager
def roster_connection():
    import psycopg
    from psycopg.rows import dict_row

    required = ("LAKEBASE_HOST", "LAKEBASE_DATABASE", "LAKEBASE_USER", "LAKEBASE_PASSWORD")
    if any(not os.environ.get(key) for key in required):
        raise RuntimeError("Lakebase roster credentials are required for the EOD email")
    with psycopg.connect(
        host=os.environ["LAKEBASE_HOST"], dbname=os.environ["LAKEBASE_DATABASE"],
        user=os.environ["LAKEBASE_USER"], password=os.environ["LAKEBASE_PASSWORD"],
        port=int(os.environ.get("LAKEBASE_PORT", "5432")), sslmode="require",
        connect_timeout=15, row_factory=dict_row,
    ) as connection:
        connection.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("select set_config('app.company_id', %s, true)", (COMPANY_ID,))
        connection.execute("set local statement_timeout = '15000ms'")
        yield connection


def verified_snapshot(row, prefix):
    for field, digest in (("canonical_json", "snapshot_sha256"),
                          ("reporting_canonical_json", "reporting_sha256")):
        raw = row[prefix + field]
        if not isinstance(raw, str) or len(raw.encode()) > 2_000_000:
            raise ValueError("Invalid Lakebase roster document")
        if hashlib.sha256(raw.encode()).hexdigest() != row[prefix + digest]:
            raise ValueError("Lakebase roster integrity check failed")
        document = json.loads(raw)
        if document.get("companyId") != COMPANY_ID or document.get("schemaVersion") != "lane2.configuration.v1":
            raise ValueError("Lakebase roster tenant/schema differs")
        if field == "canonical_json":
            snapshot = document
    return snapshot


def booked_goal(rep, report_date):
    """Same daily ramp schedule and explicit overrides as SteelTrap's scorecard."""
    config = rep["configuration"]
    start = date.fromisoformat(rep["startDate"]) if rep.get("startDate") else None
    for raw in config.get("rampResetDates", []):
        reset = date.fromisoformat(raw)
        if reset <= report_date:
            start = reset
    if report_date.weekday() >= 5 or (start and report_date < start):
        return 0
    if config.get("dailyBookedGoal") is not None:
        return config["dailyBookedGoal"]
    goals = PART_TIME_BOOKED_GOALS if config["repType"] == "part_time" else FULL_TIME_BOOKED_GOALS
    week = len(goals) - 1 if start is None else (
        (report_date - timedelta(days=report_date.weekday())) -
        (start - timedelta(days=start.weekday()))
    ).days // 7
    return goals[min(max(week, 0), len(goals) - 1)]


@dataclass
class EmailRoster:
    publication_id: str
    configuration_version: str
    saved_version: str
    reps: list
    current_ids: set
    report_date: date

    @classmethod
    def from_snapshots(cls, accepted, saved, report_date, publication_id, version, saved_version):
        reps = [rep for rep in accepted["reps"] if rep.get("providerUserId")]
        ids = [rep["providerUserId"] for rep in reps]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate Lakebase roster identity")
        saved_by_id = {rep["providerUserId"]: rep for rep in saved["reps"] if rep.get("providerUserId")}
        current = set()
        for rep in reps:
            latest = saved_by_id.get(rep["providerUserId"])
            # Match SteelTrap's immediate-removal gate; drafts cannot admit new reps.
            if not latest or latest["status"] != "active" or not latest["includedInReports"] or not latest["includedInDashboard"]:
                continue
            if rep.get("startDate") and date.fromisoformat(rep["startDate"]) > report_date:
                continue
            if latest.get("exitDate") and date.fromisoformat(latest["exitDate"]) <= report_date:
                continue
            current.add(rep["providerUserId"])
        return cls(str(publication_id), str(version), str(saved_version), reps, current, report_date)

    def match_titles(self, titles):
        """Use PostgreSQL's regex engine, just like the SteelTrap editor."""
        rules = [dict(rule, provider_user_id=rep["providerUserId"])
                 for rep in self.reps for rule in rep["configuration"]["titleRules"]]
        if not rules or not titles:
            return {}
        with roster_connection() as connection:
            rows = connection.execute("""
                select title, rule.provider_user_id, rule."requiredSetter", rule.scope
                from unnest(%s::text[]) title
                cross join jsonb_to_recordset(%s::jsonb) as rule(
                  provider_user_id text, pattern text, priority integer,
                  "requiredSetter" text, scope text)
                where title ~* rule.pattern
                order by title, rule.priority, rule.provider_user_id
            """, (sorted(set(titles)), json.dumps(rules))).fetchall()
        result = {}
        for row in rows:
            result.setdefault(row["title"], []).append(row)
        return result

    def resolve(self, user_value, setter_name, title, title_matches, scope):
        by_id = {rep["providerUserId"]: rep for rep in self.reps}
        if isinstance(user_value, list):
            user_value = user_value[0] if len(user_value) == 1 else None
        if isinstance(user_value, str) and user_value in by_id:
            return user_value
        for rule in title_matches.get(title, []):
            if rule["scope"] in (scope, "both") and (
                rule["requiredSetter"] is None or rule["requiredSetter"] == setter_name
            ):
                return rule["provider_user_id"]
        matches = [rep["providerUserId"] for rep in self.reps
                   if setter_name.strip().casefold() in {
                       name.strip().casefold() for name in
                       [rep["configuration"]["attributionName"], *rep["configuration"]["setterAliases"]]
                   }]
        return matches[0] if len(matches) == 1 else None

    def sections(self, stats):
        offers = {}
        former = []
        for rep in sorted(self.reps, key=lambda rep: rep["configuration"]["attributionName"].casefold()):
            uid = rep["providerUserId"]
            counts = stats.get(uid, {"set": 0, "booked": 0, "shown": 0})
            config = rep["configuration"]
            line = dict(counts, name=config["attributionName"], provider_user_id=uid,
                        goal=booked_goal(rep, self.report_date) if uid in self.current_ids else 0,
                        rate=counts["shown"] / counts["booked"] * 100 if counts["booked"] else None)
            if uid in self.current_ids:
                offers.setdefault(config["offer"] or "Unassigned offer", []).append(line)
            elif counts["set"] or counts["booked"]:
                former.append(line)
        sections = [{"title": f"{offer} setter bookings", "lines": lines}
                    for offer, lines in sorted(offers.items())]
        if former:
            sections.append({"title": "Former / other reps — recorded activity", "lines": former})
        return sections

    def evidence(self):
        return {"source": "Lakebase", "publication_id": self.publication_id,
                "configuration_version": self.configuration_version, "saved_version": self.saved_version,
                "report_date": self.report_date.isoformat(),
                "current_reps": [{"name": rep["configuration"]["attributionName"],
                                  "offer": rep["configuration"]["offer"],
                                  "goal": booked_goal(rep, self.report_date)}
                                 for rep in self.reps if rep["providerUserId"] in self.current_ids]}


def load_email_roster(report_date):
    with roster_connection() as connection:
        row = connection.execute("""
            select publication.publication_id::text, publication.version::text,
              control.latest_version::text as saved_version,
              accepted.canonical_json as accepted_canonical_json,
              accepted.snapshot_sha256 as accepted_snapshot_sha256,
              accepted.reporting_canonical_json as accepted_reporting_canonical_json,
              accepted.reporting_sha256 as accepted_reporting_sha256,
              saved.canonical_json as saved_canonical_json,
              saved.snapshot_sha256 as saved_snapshot_sha256,
              saved.reporting_canonical_json as saved_reporting_canonical_json,
              saved.reporting_sha256 as saved_reporting_sha256
            from app.lane2_configuration_control control
            join serving.lane2_configuration_publications publication
              on publication.company_id=control.company_id
              and publication.publication_id=control.current_publication_id
            join app.lane2_configuration_versions accepted
              on accepted.company_id=publication.company_id and accepted.version=publication.version
            join app.lane2_configuration_versions saved
              on saved.company_id=control.company_id and saved.version=control.latest_version
            where control.company_id=%s::uuid
        """, (COMPANY_ID,)).fetchone()
        if not row:
            raise RuntimeError("No accepted Lakebase Lane 2 roster is available; EOD email stopped")
        accepted = verified_snapshot(row, "accepted_")
        saved = verified_snapshot(row, "saved_")
        return EmailRoster.from_snapshots(accepted, saved, report_date,
                                         row["publication_id"], row["version"], row["saved_version"])
