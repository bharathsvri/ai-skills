import copy
import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

emails = load("hunter-connector", "emails")
out = load("hunter-connector", "outreach")
DAY5 = os.path.join(FIX, "hunter-connector", "pipeline-day5.json")
D = datetime.date
EM = chr(0x2014)
FIRST = ("Hi Maya, Your post about how your team runs design reviews hit home. I used the same approach to "
         "rebuild our payments API. I'm a fellow Michigan alum and I'm applying for the Software Engineer role "
         "on your team. Would you be open to a 20 minute coffee chat next week? Jordan")
NOTE = "Hi Maya, fellow Michigan alum and backend engineer. Would love to connect."


def day5():
    with open(DAY5, encoding="utf-8") as fh:
        return json.load(fh)


def run(mod, args):
    o, e = io.StringIO(), io.StringIO()
    with redirect_stdout(o), redirect_stderr(e):
        code = mod.main(args)
    return code, o.getvalue(), e.getvalue()


class Names(unittest.TestCase):
    def test_parse(self):
        n = emails.parse_name("Dr. Jordan Reyes Jr.")
        self.assertEqual((n["first"], n["last"], n["initial_only"]), ("jordan", "reyes", False))
        n = emails.parse_name("Jordan O'Reyes-Díaz")
        self.assertEqual(n["last"], "oreyesdiaz")
        self.assertTrue(n["hyphenated"])
        n = emails.parse_name("Maya C.")
        self.assertEqual((n["first"], n["last_initial"], n["initial_only"]), ("maya", "c", True))
        with self.assertRaises(emails.EmailError):
            emails.parse_name("   ")

    def test_known_parsing(self):
        self.assertEqual(emails.parse_known("Maya C. <Maya.C@Example.com>"), ("Maya C.", "maya.c@example.com"))
        with self.assertRaises(emails.EmailError):
            emails.parse_known("maya.c@example.com")


class Guess(unittest.TestCase):
    def test_common_patterns_ranked_and_never_verified(self):
        res = emails.guess("Jordan Reyes", "example.com")
        top = res["candidates"][0]
        self.assertEqual((top["email"], top["pattern"], top["confidence"], top["label"]),
                         ("jordan.reyes@example.com", "first.last", 0.36, "medium"))
        self.assertEqual(res["candidates"][1]["email"], "jordan@example.com")
        self.assertTrue(all(c["status"] == "guessed" for c in res["candidates"]))
        self.assertNotIn("verified", json.dumps(res).lower())
        confs = [c["confidence"] for c in res["candidates"]]
        self.assertEqual(confs, sorted(confs, reverse=True))

    def test_initial_only(self):
        res = emails.guess("Maya C.", "example.com")
        self.assertEqual([c["email"] for c in res["candidates"]],
                         ["maya@example.com", "mayac@example.com", "maya.c@example.com"])
        self.assertTrue(all(c["label"] == "low" for c in res["candidates"]))
        self.assertIn("full last name", res["notes"][0])

    def test_learned_pattern_wins(self):
        res = emails.guess("Jordan Reyes", "example.com", [("Maya C.", "maya.c@example.com")])
        top = res["candidates"][0]
        self.assertEqual((top["email"], top["confidence"], top["label"]), ("jordan.r@example.com", 0.8, "high"))
        self.assertIn("learned from 1 known address", top["why"])
        res2 = emails.guess("Maya C.", "example.com", [("Jordan Reyes", "jordan.r@example.com"),
                                                        ("Jordan Reyes", "jordan.r@example.com")])
        self.assertEqual((res2["candidates"][0]["email"], res2["candidates"][0]["confidence"]),
                         ("maya.c@example.com", 0.9))

    def test_known_addresses_that_do_not_count(self):
        res = emails.guess("Jordan Reyes", "example.com",
                           [("Maya C.", "maya.c@example.org"), ("Maya C.", "careers@example.com")])
        self.assertIsNone(res["learned"])
        self.assertEqual(len(res["notes"]), 2)
        self.assertEqual(res["candidates"][0]["pattern"], "first.last")

    def test_published_needs_a_source(self):
        with self.assertRaises(emails.EmailError):
            emails.guess("Jordan Reyes", "example.com", found="jordan.reyes@example.com")
        res = emails.guess("Jordan Reyes", "example.com", found="jreyes@example.com",
                           found_source="https://example.com/team")
        top = res["candidates"][0]
        self.assertEqual((top["email"], top["status"], top["confidence"]), ("jreyes@example.com", "published", 1.0))
        self.assertEqual(sum(1 for c in res["candidates"] if c["email"] == "jreyes@example.com"), 1)

    def test_cli(self):
        code, o, _ = run(emails, ["guess", "--name", "Jordan Reyes", "--domain", "example.com"])
        self.assertEqual(code, 0)
        self.assertIn("none is verified", o)
        self.assertNotIn(EM, o)
        self.assertEqual(run(emails, ["guess", "--name", "Jordan Reyes", "--domain", "not a domain"])[0], 2)
        code, o, _ = run(emails, ["pattern", "--known", "Jordan Reyes <jreyes@example.com>"])
        self.assertIn("flast", o)


class Rules(unittest.TestCase):
    def test_yes_means_yes_for_this_message(self):
        for r in ("yes", "Yes, send it", "send it", "Yes!", "ok send it", "approve"):
            self.assertTrue(out.is_yes(r)[0], r)
        for r in ("sure", "yes to all", "yes but change the subject", "no", "send both", "maybe", "", "y"):
            self.assertFalse(out.is_yes(r)[0], r)

    def test_research_is_professional_and_sourced(self):
        errs, _ = out.research_problems("Ran the Chicago Marathon last October")
        self.assertTrue(errs)
        errs, warns = out.research_problems("Posted about how her team runs design reviews (public post)")
        self.assertEqual((errs, warns), ([], []))
        self.assertTrue(out.research_problems("Spoke on a mentoring panel")[1])  # no source given

    def test_lint(self):
        errs, _ = out.lint("linkedin", "first", "x" * 201)
        self.assertIn("200 characters", errs[0])
        self.assertEqual(out.lint("linkedin", "first", NOTE)[0], [])
        errs, _ = out.lint("email", "first", FIRST, subject="")
        self.assertIn("subject", errs[0])
        _, warns = out.lint("email", "followup", "As per my last email, any update.")
        self.assertTrue(any("question" in w for w in warns))
        self.assertTrue(any("pressure" in w for w in warns))


class Flow(unittest.TestCase):
    def setUp(self):
        self.pipe = out.load("/nonexistent/pipeline.json")
        out.add_contact(self.pipe, "Maya C.", "Engineering Manager", "Google", email="maya.c@example.com",
                        email_confidence=0.36, source="team page",
                        research=["University of Michigan alum (public profile)"])
        self.pipe["roles"].append({"id": "google-swe", "company": "Google", "title": "Software Engineer",
                                   "url": "https://example.com/job", "stage": "saved", "applied": None,
                                   "next_step": None, "next_date": None, "notes": ""})

    def send(self, text, when, channel="email", subject=None, connected=False):
        out.make_draft(self.pipe, "maya-c-google", channel, text, subject, "google-swe", when, connected)
        out.approve(self.pipe, "maya-c-google", channel, "yes", when)
        return out.mark_sent(self.pipe, "maya-c-google", channel, when)

    def test_the_reel(self):
        t, _ = out.make_draft(self.pipe, "maya-c-google", "email", FIRST, "Michigan alum + your design review post",
                              "google-swe", D(2026, 10, 15))
        self.assertEqual((t["status"], t["draft"]["kind"]), ("drafted", "first"))
        with self.assertRaises(out.OutreachError):
            out.mark_sent(self.pipe, "maya-c-google", "email", D(2026, 10, 15))  # no yes yet
        with self.assertRaises(out.OutreachError):
            out.approve(self.pipe, "maya-c-google", "email", "yes to all", D(2026, 10, 15))
        out.approve(self.pipe, "maya-c-google", "email", "Yes, send it", D(2026, 10, 15))
        t = out.mark_sent(self.pipe, "maya-c-google", "email", D(2026, 10, 15))
        self.assertEqual((t["status"], t["next_followup"]), ("sent", "2026-10-18"))  # Day 1 -> Day 4
        li = self.send(NOTE, D(2026, 10, 15), channel="linkedin")
        self.assertIsNone(li["next_followup"])  # an invitation gets no follow-up
        with self.assertRaises(out.OutreachError):
            out.make_draft(self.pipe, "maya-c-google", "linkedin", "Hi again?", today=D(2026, 10, 16))
        with self.assertRaises(out.OutreachError):
            out.make_draft(self.pipe, "maya-c-google", "email", "Any thoughts?", today=D(2026, 10, 17))  # not due
        t = self.send("Hi Maya, here is the one-page design doc from that rebuild. Would a 20 minute chat work?",
                      D(2026, 10, 18))
        self.assertEqual(t["next_followup"], "2026-10-25")
        t, declined, stop = out.log_reply(self.pipe, "maya-c-google", "email",
                                          "Love that you rebuilt payments that way. Happy to grab a coffee, "
                                          "does Thursday at 10 work?", D(2026, 10, 19))
        self.assertEqual((t["status"], t["next_followup"], declined, stop), ("replied", None, False, False))
        with self.assertRaises(out.OutreachError):
            out.book(self.pipe, "maya-c-google", "email", "2026-10-22 10:00", 30, "Google Meet", "sure")
        t = out.book(self.pipe, "maya-c-google", "email", "2026-10-22 10:00", 30, "Google Meet", "yes")
        self.assertEqual(t["status"], "booked")
        role = out.role(self.pipe, "google-swe")
        self.assertEqual((role["next_step"], role["next_date"]),
                         ("Coffee chat with Maya C. (Google Meet)", "2026-10-22"))
        self.assertEqual(role["stage"], "saved")  # the application is still the user's to send
        d = out.due(self.pipe, D(2026, 10, 20))
        self.assertEqual(d["chats"], ["Maya C.: coffee chat 2026-10-22 10:00, Google Meet"])
        self.assertEqual(d["close_keys"], [])

    def test_an_edited_draft_needs_a_new_yes(self):
        out.make_draft(self.pipe, "maya-c-google", "email", FIRST, "Hello", today=D(2026, 10, 15))
        out.approve(self.pipe, "maya-c-google", "email", "yes", D(2026, 10, 15))
        out.make_draft(self.pipe, "maya-c-google", "email", FIRST + " Thanks!", "Hello", today=D(2026, 10, 15))
        with self.assertRaises(out.OutreachError):
            out.mark_sent(self.pipe, "maya-c-google", "email", D(2026, 10, 15))

    def test_two_follow_ups_then_stop(self):
        self.send(FIRST, D(2026, 10, 1), subject="Hello")
        self.send("Following up with one more detail. Would a short chat work?", D(2026, 10, 4))
        t = self.send("Last note from me. Would a short chat work?", D(2026, 10, 11))
        self.assertIsNone(t["next_followup"])
        with self.assertRaises(out.OutreachError):
            out.make_draft(self.pipe, "maya-c-google", "email", "One more?", today=D(2026, 10, 18))
        d = out.due(self.pipe, D(2026, 10, 18))
        self.assertIn("two follow-ups and no reply", d["close"][0])

    def test_twenty_one_days_of_silence(self):
        self.send(FIRST, D(2026, 9, 1), subject="Hello")
        t = self.send("Following up. Would a short chat work?", D(2026, 9, 20), )
        self.assertIsNone(t["next_followup"])  # 2026-09-27 would be 26 days after the first message
        with self.assertRaises(out.OutreachError) as ctx:
            out.make_draft(self.pipe, "maya-c-google", "email", "Still keen?", today=D(2026, 9, 25), early=True)
        self.assertIn("days of silence", str(ctx.exception))
        self.assertIn("days of silence", out.due(self.pipe, D(2026, 9, 25))["close"][0])

    def test_a_no_ends_the_thread(self):
        self.send(FIRST, D(2026, 10, 15), subject="Hello")
        t, declined, stop = out.log_reply(self.pipe, "maya-c-google", "email", "Not right now, sorry.",
                                          D(2026, 10, 16))
        self.assertEqual((t["status"], declined, stop), ("declined", True, False))
        with self.assertRaises(out.OutreachError):
            out.make_draft(self.pipe, "maya-c-google", "email", "Maybe next month?", today=D(2026, 11, 20))
        self.assertEqual(out.reopen(self.pipe, "maya-c-google", "email")["status"], "replied")

    def test_stop_is_forever_on_every_channel(self):
        self.send(FIRST, D(2026, 10, 15), subject="Hello")
        self.send(NOTE, D(2026, 10, 15), channel="linkedin")
        _, _, stop = out.log_reply(self.pipe, "maya-c-google", "email", "Please unsubscribe me.", D(2026, 10, 16))
        self.assertTrue(stop)
        c = out.contact(self.pipe, "maya-c-google")
        self.assertTrue(c["do_not_contact"])
        self.assertEqual({t["status"] for t in self.pipe["threads"]}, {"declined", "closed"})
        with self.assertRaises(out.OutreachError) as ctx:
            out.make_draft(self.pipe, "maya-c-google", "linkedin", "Hi?", connected=True, today=D(2027, 6, 1))
        self.assertIn("asked not to be contacted", str(ctx.exception))
        with self.assertRaises(out.OutreachError):
            out.reopen(self.pipe, "maya-c-google", "email")

    def test_contact_rules(self):
        with self.assertRaises(out.OutreachError):
            out.add_contact(self.pipe, "Maya C.", company="Netflix", email="maya.c@example.org")  # no confidence
        with self.assertRaises(out.OutreachError):
            out.add_contact(self.pipe, "Maya C.", company="Netflix", research=["Ran the Chicago Marathon"])
        with self.assertRaises(out.OutreachError):
            out.add_contact(self.pipe, "Maya C.", company="Google")  # exists
        c, warns = out.add_contact(self.pipe, "Maya C.", company="NVIDIA", research=["Spoke on a mentoring panel"])
        self.assertEqual(c["id"], "maya-c-nvidia")
        self.assertTrue(warns)
        self.assertEqual(sorted(k for k in c), sorted(["id", "name", "role", "company", "linkedin", "email",
                                                       "email_confidence", "source", "notes"]))


class Day5(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "pipeline.json")
        out.save(self.path, day5())

    def tearDown(self):
        self.tmp.cleanup()

    def test_due(self):
        d = out.due(out.load(self.path), D(2026, 10, 19))
        self.assertEqual(d["reply"], ["Maya C. at Google (email) replied on 2026-10-19: answer them"])
        self.assertEqual(d["close"], ["Maya C. at Netflix (email): 29 days of silence, close it"])
        self.assertEqual(d["close_keys"], [["maya-c-netflix", "email"]])
        self.assertEqual(d["followup"], [])

    def test_cli_round(self):
        base = ["--pipeline", self.path]
        code, o, _ = run(out, base + ["due", "--today", "2026-10-19", "--close"])
        self.assertEqual(code, 0)
        self.assertIn("They replied:", o)
        pipe = out.load(self.path)
        self.assertEqual([t["status"] for t in pipe["threads"]], ["replied", "sent", "closed"])
        self.assertEqual(pipe["roles"], day5()["roles"])  # roles untouched
        code, o, e = run(out, base + ["draft", "--contact", "maya-c-google", "--channel", "email", "--text",
                                      "Thursday at 10 works great. I'll send an invite for Google Meet. Thank you!",
                                      "--today", "2026-10-19"])
        self.assertEqual(code, 0, e)
        self.assertIn("Send this exact message? yes or no", o)
        code, _, e = run(out, base + ["approve", "--contact", "maya-c-google", "--reply", "sure"])
        self.assertEqual(code, 1)
        self.assertIn("Not recorded", e)
        self.assertEqual(run(out, base + ["approve", "--contact", "maya-c-google", "--reply", "yes"])[0], 0)
        self.assertEqual(run(out, base + ["sent", "--contact", "maya-c-google", "--date", "2026-10-19"])[0], 0)
        code, o, _ = run(out, base + ["book", "--contact", "maya-c-google", "--when", "2026-10-22 10:00",
                                      "--where", "Google Meet", "--reply", "yes"])
        self.assertEqual(code, 0)
        code, o, _ = run(out, base + ["show"])
        self.assertIn("email    booked", o)
        self.assertNotIn(EM, o)
        code, o, _ = run(out, base + ["contact", "stop", "--contact", "maya-c-netflix", "--today", "2026-10-19"])
        self.assertIn("forever", o)


if __name__ == "__main__":
    unittest.main()
