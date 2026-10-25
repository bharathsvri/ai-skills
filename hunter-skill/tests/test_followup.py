import copy
import datetime
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, SKILLS

fu = load("hunter-followup", "followup")
tracker = load("hunter-tracker", "pipeline")

DAY1 = os.path.join(FIX, "hunter-followup", "pipeline-day1.json")
EXAMPLE = os.path.join(SKILLS, "hunter-tracker", "pipeline.example.json")
CONNECTOR_DAY5 = os.path.join(FIX, "hunter-connector", "pipeline-day5.json")
D = datetime.date


def fresh(path=DAY1):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fu.main(argv)
    return code, out.getvalue(), err.getvalue()


class Yes(unittest.TestCase):
    def test_only_an_explicit_yes(self):
        for r in ("yes", "Yes.", "y", "yes, send it", "YES send the follow-up"):
            self.assertTrue(fu.parse_yes(r)[0], r)
        for r in ("", "sure", "ok", "go ahead", "yeah", "yes to all", "yes, send them all", "yes but tomorrow",
                  "yes?", "no", "not yet", "yes if she has not replied", "yes, both"):
            self.assertFalse(fu.parse_yes(r)[0], r)


class StopRules(unittest.TestCase):
    def test_the_rule_constants(self):
        self.assertEqual((fu.MAX_FOLLOWUPS, fu.SILENCE_DAYS, fu.GAP_FIRST, fu.GAP_NEXT), (2, 21, 3, 7))

    def test_day_4_follow_up_is_due_by_email(self):
        data = fresh()
        st = fu.contact_state(data, "maya-c-google", D(2026, 10, 14))
        self.assertEqual((st["state"], st["due"], st["followup"]), ("waiting", "2026-10-15", 1))
        st = fu.contact_state(data, "maya-c-google", D(2026, 10, 15))
        self.assertEqual((st["state"], st["followup"], st["channel"]), ("due", 1, "email"))
        # the email and the LinkedIn request on the same day are one opening, not a follow-up
        self.assertEqual(st["followups_sent"], 0)

    def test_record_needs_a_yes_and_schedules_the_last_nudge(self):
        data = fresh()
        ok, msg = fu.record(data, "maya-c-google", "email", "Floating this back up.", "sure", D(2026, 10, 15))
        self.assertFalse(ok)
        self.assertIn("Not recorded", msg)
        ok, msg = fu.record(data, "maya-c-google", "email", "Floating this back up.", "yes to all", D(2026, 10, 15))
        self.assertFalse(ok)
        ok, msg = fu.record(data, "maya-c-google", "email", "Floating this back up.", "yes", D(2026, 10, 15))
        self.assertTrue(ok, msg)
        self.assertIn("follow-up 1 of 2", msg)
        email = [t for t in data["threads"] if t["channel"] == "email"][0]
        self.assertEqual(email["next_followup"], "2026-10-22")
        self.assertEqual(fu.contact_state(data, "maya-c-google", D(2026, 10, 21))["state"], "waiting")
        st = fu.contact_state(data, "maya-c-google", D(2026, 10, 22))
        self.assertEqual((st["state"], st["followup"]), ("due", 2))
        ok, msg = fu.record(data, "maya-c-google", "email", "One last note.", "yes", D(2026, 10, 22))
        self.assertTrue(ok, msg)
        self.assertIn("no more follow-ups", msg)
        st = fu.contact_state(data, "maya-c-google", D(2026, 10, 23))
        self.assertEqual(st["state"], "stopped")
        self.assertIn("2 follow-ups", st["reason"])
        ok, msg = fu.record(data, "maya-c-google", "email", "A third nudge.", "yes", D(2026, 10, 30))
        self.assertFalse(ok)
        self.assertIn("stop rule", msg)
        self.assertEqual(tracker.validate(data)[0], [])

    def test_nothing_after_21_days_of_silence(self):
        data = fresh()
        fu.record(data, "maya-c-google", "email", "Floating this back up.", "yes", D(2026, 10, 15))
        for t in data["threads"]:
            t["next_followup"] = None
        data["threads"][0]["next_followup"] = "2026-11-03"  # a date the user picked, day 22
        st = fu.contact_state(data, "maya-c-google", D(2026, 11, 3))
        self.assertEqual(st["state"], "stopped")
        data["threads"][0]["next_followup"] = "2026-11-02"  # day 21 is the last day
        self.assertEqual(fu.contact_state(data, "maya-c-google", D(2026, 11, 2))["state"], "due")
        self.assertEqual(fu.contact_state(data, "maya-c-google", D(2026, 11, 3))["state"], "stopped")

    def test_a_reply_is_your_turn_and_a_no_is_forever(self):
        data = fresh()
        msg = fu.log_reply(data, "maya-c-google", "email", "Happy to grab a coffee, does Thursday at 10 work?",
                           D(2026, 10, 16))
        self.assertIn("Your turn", msg)
        st = fu.contact_state(data, "maya-c-google", D(2026, 10, 16))
        self.assertEqual(st["state"], "your-turn")
        no = fresh()
        msg = fu.log_reply(no, "maya-c-google", "email", "Thanks, but I'm not interested.", D(2026, 10, 16))
        self.assertIn("said no", msg)
        self.assertTrue(all(t["status"] == "declined" for t in no["threads"]))
        self.assertEqual(fu.contact_state(no, "maya-c-google", D(2027, 1, 1))["state"], "stopped")
        ok, msg = fu.record(no, "maya-c-google", "linkedin", "Hi again", "yes", D(2026, 12, 1))
        self.assertFalse(ok)
        with self.assertRaises(fu.FollowupError):
            fu.draft(no, fu.load_templates(), "nudge-1", "maya-c-google", today=D(2026, 10, 20))

    def test_disinterest_phrases(self):
        for t in ("No thanks.", "Please stop emailing me", "unsubscribe", "We are not hiring right now",
                  "The role has been filled", "Not interested at the moment", "not the right person, sorry"):
            self.assertTrue(fu.NO_RE.search(t), t)
        for t in ("Notable work!", "I know the team", "Happy to chat, does Thursday work?", "Nothing to add"):
            self.assertFalse(fu.NO_RE.search(t), t)

    def test_stop_is_forever(self):
        data = fresh()
        msg = fu.mark_stop(data, "maya-c-google", D(2026, 10, 16), said="Please don't contact me again")
        self.assertIn("do not contact", msg)
        self.assertIn("DO NOT CONTACT", data["contacts"][0]["notes"])
        st = fu.contact_state(data, "maya-c-google", D(2030, 1, 1))
        self.assertEqual(st["state"], "stopped")
        self.assertEqual(tracker.validate(data)[0], [])

    def test_connector_flags_are_honoured(self):
        data = fresh()
        data["contacts"][0]["do_not_contact"] = True
        self.assertEqual(fu.contact_state(data, "maya-c-google", D(2026, 10, 15))["state"], "stopped")
        invite_only = fresh()
        invite_only["threads"] = [t for t in invite_only["threads"] if t["channel"] == "linkedin"]
        invite_only["threads"][0]["invite"] = True
        st = fu.contact_state(invite_only, "maya-c-google", D(2026, 10, 20))
        self.assertEqual(st["state"], "waiting")
        self.assertIn("invitation pending", st["reason"])
        drafted = fresh()
        drafted["threads"][0]["draft"] = {"kind": "followup", "subject": None, "text": "Hi Maya, ...",
                                          "created": "2026-10-15", "hash": "abc"}
        st = fu.contact_state(drafted, "maya-c-google", D(2026, 10, 15))
        self.assertEqual(st["state"], "draft")
        ok, _ = fu.record(drafted, "maya-c-google", "email", "Hi Maya, ...", "yes", D(2026, 10, 15))
        self.assertTrue(ok)
        self.assertNotIn("draft", drafted["threads"][0])

    def test_a_status_drafted_thread_is_not_sent(self):
        data = fresh()
        t = data["threads"][0]
        t["messages"] = [{"date": "2026-10-12", "direction": "out", "text": "draft text"}]
        t["status"] = "drafted"
        data["threads"] = [t]
        self.assertEqual(fu.sent_messages(t), [])
        self.assertEqual(fu.contact_state(data, "maya-c-google", D(2026, 10, 12))["state"], "draft")

    def test_same_answer_as_the_connector_on_its_fixture(self):
        data = fresh(CONNECTOR_DAY5)
        rep = fu.due_report(data, D(2026, 10, 19))
        states = {p["contact_id"]: p["state"] for p in rep["people"]}
        self.assertEqual(states, {"maya-c-google": "your-turn", "maya-c-netflix": "stopped"})


class Applications(unittest.TestCase):
    def test_the_reel_pipeline(self):
        data = fresh(EXAMPLE)
        rep = fu.due_report(data, D(2026, 10, 16))
        self.assertEqual([(p["contact_id"], p["state"]) for p in rep["people"]], [("maya-c-google", "done")])
        apps = rep["applications"]
        self.assertEqual([a["role_id"] for a in apps], ["nvidia-deep-learning-software-engineer"])
        self.assertIn("no contact at NVIDIA yet", apps[0]["what"])
        rep = fu.due_report(data, D(2026, 10, 22))
        google = [a for a in rep["applications"] if a["role_id"] == "google-software-engineer"][0]
        self.assertIn("after-coffee", google["what"])
        rep = fu.due_report(data, D(2026, 10, 23))
        google = [a for a in rep["applications"] if a["role_id"] == "google-software-engineer"][0]
        self.assertIn("was yesterday", google["what"])

    def test_check_in_goes_to_a_known_contact(self):
        data = fresh(EXAMPLE)
        data["contacts"].append({"id": "maya-c-nvidia", "name": "Maya C.", "role": "Engineering Manager",
                                 "company": "NVIDIA", "linkedin": None, "email": None, "email_confidence": None,
                                 "source": "test", "notes": ""})
        apps = fu.application_items(data, D(2026, 10, 16))
        nvidia = [a for a in apps if a["role_id"] == "nvidia-deep-learning-software-engineer"][0]
        self.assertEqual(nvidia["contact_id"], "maya-c-nvidia")
        self.assertEqual(fu.application_items(data, D(2026, 10, 9)), [])  # 9 days: too early


class Drafts(unittest.TestCase):
    def test_templates(self):
        t = fu.load_templates()
        for k in ("nudge-1", "nudge-2", "application-check-in", "thank-you", "after-coffee", "confirm-time"):
            self.assertIn(k, t)
            self.assertTrue(t[k]["body"].strip())
        self.assertIn("last", t["nudge-2"]["body"].lower())

    def test_draft_fills_from_the_pipeline(self):
        d = fu.draft(fresh(), fu.load_templates(), "nudge-1", contact_id="maya-c-google", me="Jordan Reyes",
                     today=D(2026, 10, 15))
        self.assertTrue(d["body"].startswith("Hi Maya,"))
        self.assertIn("Software Engineer role", d["body"])
        self.assertTrue(d["body"].rstrip().endswith("Jordan"))
        self.assertIn("hook", d["missing"])
        self.assertIn("[fill: hook]", d["body"])

    def test_cli_due_and_record(self):
        tmp = tempfile.mkdtemp()
        try:
            f = os.path.join(tmp, "pipeline.json")
            shutil.copy(DAY1, f)
            code, out, _ = run(["--file", f, "due", "--today", "2026-10-15"])
            self.assertEqual(code, 0)
            self.assertIn("DUE NOW", out)
            self.assertIn("follow-up 1 of 2", out)
            code, out, _ = run(["--file", f, "record", "--contact", "maya-c-google", "--channel", "email",
                                "--text", "Floating this back up.", "--approval", "ok", "--today", "2026-10-15"])
            self.assertEqual(code, 1)
            with open(f, encoding="utf-8") as fh:
                self.assertEqual(len(json.load(fh)["threads"][0]["messages"]), 1)  # nothing written
            code, out, _ = run(["--file", f, "record", "--contact", "maya-c-google", "--channel", "email",
                                "--text", "Floating this back up.", "--approval", "yes", "--today", "2026-10-15"])
            self.assertEqual(code, 0, out)
            code, out, _ = run(["--file", f, "draft", "--contact", "maya-c-google", "--template", "nudge-2",
                                "--me", "Jordan Reyes", "--hook", "Here is the one-page design doc.",
                                "--today", "2026-10-22"])
            self.assertEqual(code, 0)
            self.assertIn("One last note", out)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
