import copy
import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

ans = load("hunter-apply", "answers")
FORM = os.path.join(FIX, "hunter-apply", "application-form.json")
EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "skills", "hunter-apply", "profile.example.json")
EM = chr(0x2014)
ROLE = {"id": "google-swe", "company": "Google", "title": "Software Engineer",
        "url": "https://www.google.com/about/careers/applications/jobs/results", "stage": "saved",
        "applied": None, "next_step": None, "next_date": None, "notes": ""}


def profile():
    with open(EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def form():
    with open(FORM, encoding="utf-8") as fh:
        return json.load(fh)


def run(args):
    o, e = io.StringIO(), io.StringIO()
    with redirect_stdout(o), redirect_stderr(e):
        code = ans.main(args)
    return code, o.getvalue(), e.getvalue()


class Answers(unittest.TestCase):
    def setUp(self):
        self.p = profile()

    def get(self, label, **kw):
        return ans.answer(label, self.p, **kw)

    def test_facts_from_the_profile(self):
        self.assertEqual(self.get("First Name")["answer"], "Jordan")
        self.assertEqual(self.get("Last Name")["answer"], "Reyes")
        self.assertEqual(self.get("Email address")["answer"], "jordan.reyes@example.com")
        self.assertEqual(self.get("Current company")["answer"], "Brightline Labs")
        self.assertEqual(self.get("School")["answer"], "University of Michigan")
        self.assertEqual(self.get("How many years of experience do you have?")["answer"], "3")
        r = self.get("Are you legally authorized to work in the United States?", options=["Yes", "No"])
        self.assertEqual((r["answer"], r["status"], r["source"]), ("Yes", "filled", "profile.work_authorization"))
        r = self.get("Will you now or in the future require sponsorship?", options=["Yes", "No"])
        self.assertEqual(r["answer"], "No")
        r = self.get("Are you willing to relocate?", options=["Yes", "No"])
        self.assertEqual(r["answer"], "Yes")  # the saved sentence maps onto the option

    def test_missing_means_ask_never_guess(self):
        r = self.get("Phone number")
        self.assertEqual((r["status"], r["answer"]), ("ask", None))
        r = self.get("What are your salary expectations?")
        self.assertEqual(r["status"], "ask")
        self.assertIn("/hunter-salary", r["note"])
        r = self.get("Do you have a non-compete agreement?")
        self.assertEqual((r["status"], r["key"]), ("ask", None))
        r = self.get("Referred by")
        self.assertEqual(r["status"], "ask")
        self.assertIn("only a real referral", r["note"])

    def test_sensitive_questions_are_the_users(self):
        for label in ("Gender", "Race/Ethnicity", "Are you a protected veteran?", "Disability status"):
            r = self.get(label)
            self.assertEqual((r["status"], r["answer"]), ("sensitive", None), label)
        r = self.get("What is your current salary?")
        self.assertEqual(r["status"], "sensitive")
        self.assertIn("never estimate", r["note"])
        self.p["self_identification"]["veteran_status"] = "I am not a protected veteran"
        r = self.get("Are you a protected veteran?",
                     options=["I am a protected veteran", "I am not a protected veteran", "I don't wish to answer"])
        self.assertEqual(r["answer"], "I am not a protected veteran")

    def test_role_specific(self):
        with tempfile.TemporaryDirectory() as ws:
            r = ans.answer("Why do you want to work at Google?", self.p, "google-swe", ws)
            self.assertEqual(r["status"], "role-specific")
            self.assertIn("/hunter-cover", r["note"])
            os.makedirs(os.path.join(ws, "covers"))
            with open(os.path.join(ws, "covers", "google-swe.md"), "w") as fh:
                fh.write("cover")
            r = ans.answer("Cover letter", self.p, "google-swe", ws)
            self.assertEqual(r["source"], os.path.join(ws, "covers", "google-swe.md"))

    def test_options_that_do_not_match(self):
        r = self.get("Do you have a Bachelor's degree?", options=["Yes", "No"])
        self.assertEqual(r["status"], "ask")
        self.assertIn("matches none of the options", r["note"])

    def test_fill(self):
        res = ans.fill(form(), self.p, "google-swe")
        self.assertEqual(res["counts"], {"filled": 9, "ask": 3, "sensitive": 3, "role-specific": 1})
        self.assertFalse(res["ready"])
        labels = {q["label"]: q for q in res["questions"]}
        self.assertEqual(labels["Gender"]["answer"], None)


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = os.path.join(self.tmp.name, "hunter")
        self.pipe_path = os.path.join(self.ws, "pipeline.json")
        self.prof_path = os.path.join(self.ws, "profile.json")
        ans.save_json(self.pipe_path, {"roles": [dict(ROLE)], "contacts": [], "threads": []})
        ans.save_json(self.prof_path, profile())
        self.base = ["--profile", self.prof_path, "--pipeline", self.pipe_path, "--workspace", self.ws]

    def tearDown(self):
        self.tmp.cleanup()

    def test_draft_then_the_user_submits(self):
        pipe = ans.load_pipeline(self.pipe_path)
        r = ans.record_draft(pipe, "google-swe", "https://example.com/apply", None, datetime.date(2026, 10, 23))
        self.assertEqual(r["stage"], "saved")
        self.assertEqual(r["application"]["status"], "draft")
        self.assertEqual(r["next_step"], "Review the application draft and submit it yourself")
        with self.assertRaises(ans.ApplyError):
            ans.record_submitted(pipe, "google-swe", "yes", datetime.date(2026, 10, 24))
        r = ans.record_submitted(pipe, "google-swe", "I submitted it", datetime.date(2026, 10, 24))
        self.assertEqual((r["stage"], r["applied"], r["next_date"]), ("applied", "2026-10-24", "2026-10-31"))
        with self.assertRaises(ans.ApplyError):
            ans.record_draft(pipe, "google-swe", "https://example.com/apply", None, datetime.date(2026, 10, 25))
        with self.assertRaises(ans.ApplyError):
            ans.record_draft(pipe, "nope", "https://example.com/apply", None, datetime.date(2026, 10, 25))

    def test_checklist(self):
        items = ans.checklist(ans.load_pipeline(self.pipe_path), "google-swe", self.ws, profile())
        done = {i["item"]: i["done"] for i in items}
        self.assertTrue(done["Work authorization answered in the profile"])
        self.assertFalse(done["Resume tailored for this role"])
        self.assertFalse(done["Form filled in the browser and saved as a draft, not submitted"])
        os.makedirs(os.path.join(self.ws, "resumes"))
        with open(os.path.join(self.ws, "resumes", "google-swe.md"), "w") as fh:
            fh.write("resume")
        items = ans.checklist(ans.load_pipeline(self.pipe_path), "google-swe", self.ws, profile())
        self.assertTrue(items[0]["done"])

    def test_cli(self):
        out_path = os.path.join(self.ws, "applications", "google-swe.json")
        code, o, e = run(self.base + ["fill", "--questions", FORM, "--role", "google-swe", "--out", out_path])
        self.assertEqual(code, 0, e)
        self.assertIn("Stop before Submit", o)
        self.assertNotIn(EM, o)
        self.assertTrue(os.path.isfile(out_path))
        code, o, _ = run(self.base + ["checklist", "--role", "google-swe"])
        self.assertEqual(code, 1)
        self.assertIn("[ ] Resume tailored for this role", o)
        code, o, _ = run(self.base + ["draft", "--role", "google-swe", "--form-url", "https://example.com/apply",
                                      "--answers", out_path, "--today", "2026-10-23"])
        self.assertEqual(code, 0)
        self.assertIn("not submitted", o)
        pipe = ans.load_json(self.pipe_path)
        self.assertEqual(pipe["roles"][0]["application"]["form_url"], "https://example.com/apply")
        code, _, e = run(self.base + ["submitted", "--role", "google-swe", "--confirm", "go ahead"])
        self.assertEqual(code, 2)
        code, o, _ = run(self.base + ["submitted", "--role", "google-swe", "--confirm", "Done, I submitted it",
                                      "--date", "2026-10-24"])
        self.assertEqual(code, 0)
        self.assertEqual(ans.load_json(self.pipe_path)["roles"][0]["stage"], "applied")
        code, o, _ = run(self.base + ["answer", "--question", "Gender"])
        self.assertEqual(code, 1)
        self.assertIn("sensitive", o)

    def test_needs_a_profile(self):
        code, _, e = run(["--profile", os.path.join(self.tmp.name, "none.json"), "answer", "--question", "Email"])
        self.assertEqual(code, 2)
        self.assertIn("profile.example.json", e)


class Example(unittest.TestCase):
    def test_example_profile_shape(self):
        p = profile()
        for key in ("name", "location", "target_roles", "skills", "links", "work_authorization",
                    "salary_floor", "resume_path", "answers"):
            self.assertIn(key, p)
        self.assertEqual(p["name"], "Jordan Reyes")
        self.assertTrue(all(v is None for k, v in p["self_identification"].items() if k != "_note"))
        self.assertTrue(p["email"].endswith("@example.com"))


if __name__ == "__main__":
    unittest.main()
