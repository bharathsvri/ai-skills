import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, SKILLS

pipeline = load("hunter-tracker", "pipeline")

EXAMPLE = os.path.join(SKILLS, "hunter-tracker", "pipeline.example.json")
BROKEN = os.path.join(FIX, "hunter-tracker", "pipeline-broken.json")
CONNECTOR_DAY5 = os.path.join(FIX, "hunter-connector", "pipeline-day5.json")


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = pipeline.main(argv)
    return code, out.getvalue(), err.getvalue()


class Schema(unittest.TestCase):
    def test_fields_are_the_spec(self):
        self.assertEqual(pipeline.ROLE_FIELDS, ("id", "company", "title", "url", "stage", "applied", "next_step",
                                                "next_date", "notes"))
        self.assertEqual(pipeline.CONTACT_FIELDS, ("id", "name", "role", "company", "linkedin", "email",
                                                   "email_confidence", "source", "notes"))
        self.assertEqual(pipeline.THREAD_FIELDS, ("contact_id", "role_id", "channel", "messages", "status",
                                                  "next_followup"))
        self.assertEqual(pipeline.MESSAGE_FIELDS, ("date", "direction", "text"))
        self.assertEqual(pipeline.STAGES, ("saved", "applied", "screen", "interview", "onsite", "offer",
                                           "rejected", "withdrawn"))
        self.assertEqual(pipeline.THREAD_STATUSES, ("drafted", "sent", "replied", "booked", "declined", "closed"))

    def test_the_example_is_clean(self):
        data = pipeline.load(EXAMPLE)
        errors, warnings = pipeline.validate(data)
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])
        names = {c["name"] for c in data["contacts"]}
        self.assertEqual(names, {"Maya C."})  # only the reel's fictional people

    def test_the_connectors_file_is_valid_too(self):
        errors, warnings = pipeline.validate(pipeline.load(CONNECTOR_DAY5))
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])  # invite, _note: known optional fields

    def test_the_broken_file_lists_every_problem(self):
        errors, warnings = pipeline.validate(pipeline.load(BROKEN))
        text = "\n".join(errors)
        for needle in ("stage must be one of", "next_date must be YYYY-MM-DD", "duplicate id",
                       "is not an email address", "needs the public page", "contact_id 'nobody-at-all'",
                       "direction must be out or in", "role_id 'no-such-role'", "status must be one of",
                       "next_followup must be YYYY-MM-DD"):
            self.assertIn(needle, text)
        wtext = "\n".join(warnings)
        self.assertIn("url should start with https://", wtext)
        self.assertIn("stage applied but no applied date", wtext)
        self.assertIn("channel 'pigeon'", wtext)
        code, out, _ = run(["--file", BROKEN, "validate"])
        self.assertEqual(code, 1)
        self.assertIn("ERROR", out)

    def test_email_confidence(self):
        ok = pipeline.check_confidence
        self.assertEqual(ok(0.36, None), (None, None))
        self.assertEqual(ok("medium", None), (None, None))
        self.assertIsNotNone(ok("published", "guessed from the pattern")[0])
        self.assertIsNotNone(ok("verified", None)[0])
        self.assertEqual(ok("verified", "https://example.com/team"), (None, None))
        self.assertIsNotNone(ok(85, None)[1])
        self.assertIsNotNone(ok(150, None)[0])
        self.assertIsNotNone(ok(True, None)[0])
        self.assertIsNotNone(ok("certain", None)[0])


class Commands(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.f = os.path.join(self.d, "hunter", "pipeline.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def data(self):
        with open(self.f, encoding="utf-8") as fh:
            return json.load(fh)

    def test_init_add_move(self):
        self.assertEqual(run(["--file", self.f, "init"])[0], 0)
        self.assertEqual(run(["--file", self.f, "init"])[0], 2)  # never overwrites
        code, out, _ = run(["--file", self.f, "add-role", "--company", "Google", "--title", "Software Engineer",
                            "--today", "2026-10-11"])
        self.assertEqual(code, 0)
        self.assertIn("google-software-engineer", out)
        code, out, _ = run(["--file", self.f, "add-role", "--company", "google", "--title", "software engineer",
                            "--today", "2026-10-11"])
        self.assertEqual(code, 1)  # duplicate caught
        self.assertIn("Already in the pipeline", out)
        self.assertEqual(run(["--file", self.f, "add-role", "--company", "Google", "--title", "Software Engineer",
                              "--force", "--today", "2026-10-11"])[0], 0)
        ids = [r["id"] for r in self.data()["roles"]]
        self.assertEqual(ids, ["google-software-engineer", "google-software-engineer-2"])
        code, out, _ = run(["--file", self.f, "move", "google-software-engineer", "applied", "--today", "2026-10-23"])
        self.assertEqual(code, 0)
        role = self.data()["roles"][0]
        self.assertEqual(role["stage"], "applied")
        self.assertEqual(role["applied"], "2026-10-23")
        self.assertIn("2026-10-23: saved -> applied", role["notes"])
        run(["--file", self.f, "move", "google-software-engineer", "rejected", "--today", "2026-11-02"])
        role = self.data()["roles"][0]
        self.assertEqual((role["next_step"], role["next_date"]), (None, None))
        errors, _ = pipeline.validate(self.data())
        self.assertEqual(errors, [])

    def test_contacts_and_bad_updates(self):
        run(["--file", self.f, "init"])
        code, out, _ = run(["--file", self.f, "add-contact", "--name", "Maya C.", "--company", "Google",
                            "--role", "Engineering Manager", "--email", "maya.c@example.com",
                            "--email-confidence", "0.36", "--source", "pattern guess"])
        self.assertEqual(code, 0)
        c = self.data()["contacts"][0]
        self.assertEqual(c["id"], "maya-c-google")
        self.assertEqual(c["email_confidence"], 0.36)
        # a "published" address without the page it is published on is refused, file unchanged
        code, _, err = run(["--file", self.f, "update-contact", "maya-c-google", "--email-confidence", "published"])
        self.assertEqual(code, 2)
        self.assertIn("needs the public page", err)
        self.assertEqual(self.data()["contacts"][0]["email_confidence"], 0.36)
        code, _, err = run(["--file", self.f, "update-role", "nope", "--next-step", "x"])
        self.assertEqual(code, 2)

    def test_add_role_refuses_a_bad_date(self):
        run(["--file", self.f, "init"])
        code, _, err = run(["--file", self.f, "add-role", "--company", "Meta", "--title", "SWE",
                            "--next-date", "next week", "--today", "2026-10-11"])
        self.assertEqual(code, 2)
        self.assertEqual(self.data()["roles"], [])


class Reports(unittest.TestCase):
    def setUp(self):
        self.data = pipeline.load(EXAMPLE)

    def test_summary_on_day_5(self):
        s = pipeline.summary(self.data, pipeline.parse_day("2026-10-16"))
        self.assertEqual((s["roles"], s["active"], s["applied"], s["contacts"]), (5, 5, 2, 1))
        self.assertEqual({k: v for k, v in s["by_stage"].items() if v}, {"saved": 3, "applied": 1, "screen": 1})
        self.assertEqual(s["threads"]["booked"], 1)
        self.assertEqual([n["id"] for n in s["next"]],
                         ["amazon-software-development-engineer-ii", "meta-software-engineer-product",
                          "google-software-engineer"])
        self.assertEqual([r["id"] for r in s["stale"]],
                         ["netflix-senior-software-engineer", "nvidia-deep-learning-software-engineer"])
        self.assertEqual([r["idle_days"] for r in s["stale"]], [22, 16])

    def test_next_marks_overdue(self):
        items = pipeline.upcoming(self.data, pipeline.parse_day("2026-10-21"), 1)
        self.assertEqual([(d.isoformat(), i) for d, k, i, w in items],
                         [("2026-10-19", "amazon-software-development-engineer-ii"),
                          ("2026-10-19", "meta-software-engineer-product"),
                          ("2026-10-22", "google-software-engineer")])
        code, out, _ = run(["--file", EXAMPLE, "next", "--today", "2026-10-21", "--days", "1"])
        self.assertIn("OVERDUE", out)

    def test_stale_threshold(self):
        rows = pipeline.stale_roles(self.data, pipeline.parse_day("2026-10-16"), 20)
        self.assertEqual([r.get("id") for r, _, _ in rows], ["netflix-senior-software-engineer"])

    def test_export_csv(self):
        text = pipeline.to_csv(self.data, "roles")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(tuple(rows[0]), pipeline.ROLE_FIELDS)
        self.assertEqual(len(rows), 6)
        rows = list(csv.reader(io.StringIO(pipeline.to_csv(self.data, "threads"))))
        self.assertEqual(rows[1][:4], ["maya-c-google", "google-software-engineer", "email", "booked"])
        self.assertEqual(rows[1][5:], ["4", "2026-10-12", "2026-10-16", "out"])

    def test_show_and_summary_cli(self):
        code, out, _ = run(["--file", EXAMPLE, "show", "maya-c-google"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out)["threads"]), 2)
        code, out, _ = run(["--file", EXAMPLE, "summary", "--today", "2026-10-16"])
        self.assertIn("5 roles (5 active, 2 applied), 1 contact", out)


if __name__ == "__main__":
    unittest.main()
