import datetime
import io
import json
import os
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, SKILLS

ats = load("hunter-resume", "ats")

EX = os.path.join(SKILLS, "hunter-resume", "examples")
BEFORE = os.path.join(EX, "jordan-before.md")
AFTER = os.path.join(EX, "jordan-after.md")
JD = os.path.join(EX, "google-swe-jd.md")
INVENTED = os.path.join(FIX, "hunter-resume", "jordan-after-invented.md")
JD_INLINE = os.path.join(FIX, "hunter-resume", "jd-inline.txt")
JD_PLAIN = os.path.join(FIX, "hunter-resume", "jd-plain.txt")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ats.main(argv)
    return code, out.getvalue(), err.getvalue()


class TheReel(unittest.TestCase):
    """Jordan Reyes vs the Google posting: 54 -> 96, and nothing invented."""

    @classmethod
    def setUpClass(cls):
        cls.terms = ats.load_terms()
        cls.before = ats.score(read(BEFORE), read(JD), cls.terms)
        cls.after = ats.score(read(AFTER), read(JD), cls.terms)

    def test_54_to_96(self):
        self.assertEqual(self.before["score"], 54)
        self.assertEqual(self.after["score"], 96)

    def test_the_formula_reproduces_the_number(self):
        for res in (self.before, self.after):
            w, p = res["weights"], res["parts"]
            self.assertEqual(sum(w.values()), 100)
            raw = sum(w[k] * p[k] for k in "RPBS")
            self.assertAlmostEqual(raw, res["raw"], places=2)
            self.assertEqual(res["score"], int(raw + 0.5))
        self.assertEqual(self.before["parts"], {"R": 0.625, "P": 0.5, "B": 0.2857, "S": 0.75})
        self.assertEqual(self.after["parts"], {"R": 1.0, "P": 0.85, "B": 0.9444, "S": 1.0})

    def test_the_rewrite_invents_nothing(self):
        t = ats.trace(read(BEFORE), read(AFTER), self.terms)
        self.assertTrue(t["clean"], t)
        self.assertEqual(t["new_names"], [])

    def test_the_reels_three_bullets(self):
        after = read(AFTER)
        for b in ("Rebuilt the payments API in Go, cutting p99 latency 38% across 4M requests a day",
                  "Shipped an ML ranking service that lifted search click-through 12%",
                  "Led on-call for 9 services and cut pages 60% with automated runbooks"):
            self.assertIn("- " + b, after)
        before = read(BEFORE)
        for b in ("Worked on backend services", "Helped with machine learning projects", "Responsible for on-call"):
            self.assertIn("- " + b, before)

    def test_reword_and_missing(self):
        rw = {(r["you_wrote"], r["posting_says"]) for r in self.before["reword"]}
        for pair in (("Golang", "Go"), ("k8s", "Kubernetes"), ("GCP", "Google Cloud Platform"),
                     ("distributed computing", "distributed systems")):
            self.assertIn(pair, rw)
        self.assertEqual([m["term"] for m in self.after["missing"]],
                         ["master's degree", "PhD", "mentoring", "documentation"])
        self.assertEqual(self.after["reword"], [])

    def test_compare_cli_is_clean(self):
        code, out, _ = run(["compare", BEFORE, AFTER, "--jd", JD])
        self.assertEqual(code, 0)
        self.assertIn("Before 54 -> after 96", out)
        self.assertIn("Truth check: CLEAN", out)
        code, out, _ = run(["score", AFTER, "--jd", JD, "--json", "--today", "2026-10-15"])
        res = json.loads(out)
        self.assertEqual(res["score"], 96)
        self.assertEqual(res["years"], {"resume": 3.0, "asked": 2})


class TruthCheck(unittest.TestCase):
    def test_invented_number_and_skill_are_caught(self):
        terms = ats.load_terms()
        t = ats.trace(read(BEFORE), read(INVENTED), terms)
        self.assertFalse(t["clean"])
        self.assertEqual(t["invented_numbers"], ["5"])
        self.assertEqual(t["invented_terms"], ["Kafka", "data pipelines"])
        self.assertIn("Senior", t["new_names"])
        code, out, _ = run(["trace", BEFORE, INVENTED])
        self.assertEqual(code, 1)
        self.assertIn("INVENTED", out)

    def test_facts_the_user_confirmed_are_allowed(self):
        terms = ats.load_terms()
        facts = "Confirmed by Jordan on 2026-10-14: led a team of 5 on Kafka data pipelines."
        t = ats.trace(read(BEFORE), read(INVENTED), terms, facts)
        self.assertEqual(t["invented_numbers"], [])
        self.assertEqual(t["invented_terms"], [])


class Matching(unittest.TestCase):
    def setUp(self):
        self.terms = ats.load_terms()

    def names(self, line):
        out = []
        for g in ats.line_groups(line, self.terms):
            n = [self.terms[i]["term"] for i in g["terms"]]
            out.append(("or", tuple(n)) if g["choice"] else n[0])
        return out

    def test_choice_and_required_groups(self):
        self.assertEqual(self.names("2 years of experience with software development in Go, C++ or Java."),
                         ["software development", ("or", ("Go", "C++", "Java"))])
        self.assertEqual(self.names("Experience with Kubernetes, containers and Google Cloud Platform."),
                         ["Kubernetes", "containers", "Google Cloud"])
        self.assertEqual(self.names("Master's degree or PhD in Computer Science or a related technical field."),
                         [("or", ("master's degree", "PhD")), "computer science"])

    def test_wording_case_and_forms(self):
        rx = ats.form_regex
        self.assertFalse(rx("Go", True).search("we go to the office"))
        self.assertTrue(rx("Go", True).search("services in Go, Python"))
        self.assertFalse(rx("Go", True).search("Google"))
        self.assertTrue(rx("debug", False).search("debugging production issues"))
        self.assertTrue(rx("on-call", False).search("the oncall rotation"))
        self.assertTrue(rx("data structures", False).search("a data structure"))
        self.assertTrue(rx("C++", False).search("C++ and Rust"))
        self.assertTrue(rx("bachelor's degree", False).search(ats.norm_text("Bachelor’s degree")))

    def test_degrees_count_by_meaning(self):
        res = ats.score("Education\nB.S. in Computer Science\n", "Minimum qualifications:\n- Bachelor's degree.\n",
                        self.terms)
        self.assertEqual(res["parts"]["R"], 1.0)

    def test_bullet_checks(self):
        b = ats.check_bullet("Worked on backend services")
        self.assertEqual((b["number"], b["verb"], b["length"]), (False, False, False))
        b = ats.check_bullet("Moved our services onto k8s on GCP, containerized with Docker")
        self.assertFalse(b["number"])  # k8s is a name, not a number
        self.assertTrue(b["verb"])
        b = ats.check_bullet("Rebuilt the payments API in Go, cutting p99 latency 38% across 4M requests a day")
        self.assertEqual(b["points"], 1.0)

    def test_inline_headings_and_curly_quotes(self):
        reqs, forms, sec = ats.requirements(read(JD_INLINE), self.terms)
        self.assertEqual(len(reqs["must"]), 3)
        self.assertEqual(len(reqs["preferred"]), 1)
        self.assertTrue(sec["ignore"])  # "About the job" is not scored
        res = ats.score("Experience\n- Built payments APIs in Python and PostgreSQL\nEducation\nBS, Computer Science\n",
                        read(JD_INLINE), self.terms)
        self.assertEqual([m["term"] for m in res["missing"]], ["Redis", "Kubernetes"])

    def test_no_sections_means_all_required(self):
        res = ats.score("Skills\nSQL, Python, Airflow\n", read(JD_PLAIN), self.terms)
        self.assertEqual(res["weights"]["R"], 70)
        self.assertEqual(res["weights"]["P"], 0)
        self.assertEqual([m["term"] for m in res["missing"]], ["data pipelines", "BigQuery"])

    def test_today_only_changes_the_years_line(self):
        a = ats.score(read(AFTER), read(JD), self.terms, datetime.date(2026, 10, 15))
        b = ats.score(read(AFTER), read(JD), self.terms, datetime.date(2031, 1, 1))
        self.assertEqual(a["score"], b["score"])
        self.assertNotEqual(a["years"]["resume"], b["years"]["resume"])

    def test_terms_file_is_well_formed(self):
        with open(os.path.join(SKILLS, "hunter-resume", "terms.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        seen = set()
        for t in data["terms"]:
            self.assertNotIn(t["term"], seen)
            seen.add(t["term"])
            self.assertTrue(t["forms"])
            for f in t.get("case", []):
                self.assertIn(f, t["forms"])


if __name__ == "__main__":
    unittest.main()
