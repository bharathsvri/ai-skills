import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

li = load("hunter-linkedin", "profile")
JD = os.path.join(FIX, "hunter-linkedin", "swe-infra-jd.txt")
SKILLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")
EXAMPLE = os.path.join(SKILLS, "hunter-linkedin", "linkedin.example.json")
PROFILE = os.path.join(SKILLS, "hunter-apply", "profile.example.json")
EM = chr(0x2014)


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = li.main(args)
    return code, out.getvalue(), err.getvalue()


def example():
    with open(EXAMPLE, encoding="utf-8") as fh:
        return json.load(fh)


def jd():
    with open(JD, encoding="utf-8") as fh:
        return fh.read()


class Keywords(unittest.TestCase):
    def test_zones_and_weights(self):
        kws = {k["term"]: k for k in li.keywords(jd())}
        for term in ("Go", "Python", "Java", "C++", "Distributed systems", "System design", "Algorithms"):
            self.assertEqual((kws[term]["zone"], kws[term]["weight"]), ("must", 3), term)
        for term in ("Kubernetes", "Kafka", "PostgreSQL", "Google Cloud"):
            self.assertEqual(kws[term]["zone"], "nice", term)
        self.assertEqual(kws["Design reviews"]["zone"], "body")
        self.assertEqual(li.keywords(jd())[0]["term"], "Distributed systems")  # required and named twice

    def test_go_is_a_language_not_a_verb(self):
        self.assertEqual(li.terms_in("ready to go"), [])
        self.assertIn("Go", li.terms_in("services in Go"))
        self.assertIn("Go", li.terms_in("golang services"))
        self.assertIn("C++", li.terms_in("modern c++ and Rust"))
        self.assertIn("Machine learning", li.terms_in("an ML ranking service"))


class Report(unittest.TestCase):
    def setUp(self):
        self.doc = example()
        self.limits = li.load_json(li.LIMITS)

    def test_before_and_after(self):
        before = li.report(self.doc["current"], jd(), self.limits)
        after = li.report(self.doc["draft"], jd(), self.limits)
        self.assertEqual((before["coverage"], before["must_covered"], before["must_total"]), (22, 2, 8))
        self.assertEqual((after["coverage"], after["must_covered"], after["must_total"]), (86, 7, 8))
        self.assertEqual(after["missing_must"], ["C++"])
        self.assertTrue(any("default" in t for t in li.advice(self.doc["current"],
                                                               li.coverage(self.doc["current"], li.keywords(jd())),
                                                               li.keywords(jd()))))
        self.assertTrue(any("About is empty" in t for t in before["advice"]))
        self.assertTrue(any("no numbers" in t for t in before["advice"]))

    def test_limits(self):
        long = dict(self.doc["draft"], headline="x" * 221, skills=["s%d" % i for i in range(101)])
        checks = {c["field"]: c for c in li.limit_checks(long, self.limits)}
        self.assertFalse(checks["headline"]["ok"])
        self.assertFalse(checks["skills"]["ok"])
        self.assertTrue(checks["about"]["ok"])
        self.assertEqual(checks["skills"]["source"], "https://www.linkedin.com/help/linkedin/answer/35265")
        self.assertIn("reported", checks["headline"]["source"])

    def test_limits_file(self):
        f = self.limits["fields"]
        self.assertEqual(f["headline"]["max"], 220)
        self.assertEqual(f["about"]["max"], 2600)
        self.assertEqual(f["skills"]["max"], 100)
        self.assertEqual(f["invitation_note"]["max"], 200)
        self.assertEqual(f["invitation_note"]["source"], "https://www.linkedin.com/help/linkedin/answer/46662")
        self.assertIn("8.2", self.limits["automation"]["rule"])

    def test_truth_check_flags_unbacked_claims(self):
        truth = "Go Python Java Kubernetes"
        flagged = li.unproven(self.doc["draft"], truth)
        self.assertIn("Kafka", flagged)
        self.assertNotIn("Go", flagged)
        backed = li.unproven(self.doc["draft"], truth + " Kafka", None)
        self.assertNotIn("Kafka", backed)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "linkedin.json")
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(example(), fh)

    def tearDown(self):
        self.tmp.cleanup()

    def test_compare(self):
        code, out, err = run(["compare", "--linkedin", self.path, "--job", JD, "--profile", PROFILE])
        self.assertEqual(code, 0, err)
        self.assertIn("Keyword coverage              22%        86%", out)
        self.assertIn("Required terms                2/8        7/8", out)
        self.assertIn("Gained: Distributed systems, Go", out)
        self.assertIn("Still missing: C++", out)
        self.assertIn("Paste the draft into LinkedIn yourself", out)
        self.assertNotIn(EM, out)

    def test_check_fails_over_a_limit(self):
        doc = example()
        doc["draft"]["about"] = "a" * 2601
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        code, out, _ = run(["check", "--linkedin", self.path, "--job", JD, "--json"])
        self.assertEqual(code, 1)
        about = [c for c in json.loads(out)["limits"] if c["field"] == "about"][0]
        self.assertEqual((about["value"], about["ok"]), (2601, False))

    def test_missing_inputs(self):
        self.assertEqual(run(["check", "--linkedin", os.path.join(self.tmp.name, "no.json"), "--job", JD])[0], 2)
        self.assertEqual(run(["keywords", "--job", os.path.join(self.tmp.name, "no.txt")])[0], 2)

    def test_limits_command(self):
        code, out, _ = run(["limits"])
        self.assertEqual(code, 0)
        self.assertIn("invitation_note          200 characters", out)


if __name__ == "__main__":
    unittest.main()
