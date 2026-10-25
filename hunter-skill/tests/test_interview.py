import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, SKILLS

star = load("hunter-interview", "star")

ANSWER = os.path.join(SKILLS, "hunter-interview", "example-answer.md")
LPS = ["Customer Obsession", "Ownership", "Invent and Simplify", "Are Right, A Lot", "Learn and Be Curious",
       "Hire and Develop the Best", "Insist on the Highest Standards", "Think Big", "Bias for Action",
       "Frugality", "Earn Trust", "Dive Deep", "Have Backbone; Disagree and Commit", "Deliver Results",
       "Strive to be Earth's Best Employer", "Success and Scale Bring Broad Responsibility"]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = star.main(argv)
    return code, out.getvalue(), err.getvalue()


class Bank(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = star.load_bank()

    def test_every_question_cites_a_source(self):
        ids = set()
        for q in self.bank["questions"]:
            self.assertNotIn(q["id"], ids)
            ids.add(q["id"])
            self.assertIn(q["basis"], ("official", "community"))
            src = self.bank["sources"][q["source"]]
            if q["basis"] == "official":
                self.assertTrue(src["url"].startswith("https://"), q["id"])
                self.assertNotEqual(q["source"], "community")
            else:
                self.assertEqual(q["source"], "community", q["id"])
            self.assertTrue(q["question"].strip())
            self.assertIn(q["company"], self.bank["companies"])

    def test_official_sources_are_the_companies_own_pages(self):
        own = {"Google": "google.com/about/careers/", "Meta": "metacareers.com/", "NVIDIA": "nvidia.com/",
               "Netflix": "jobs.netflix.com/", "Amazon": "amazon.jobs/"}
        for key, src in self.bank["sources"].items():
            if key == "community":
                self.assertIsNone(src["url"])
                continue
            self.assertIn(own[src["publisher"]], src["url"], key)
            self.assertEqual(src["checked"], "2026-10-15")

    def test_the_five_hardest_companies_and_their_loops(self):
        for key in ("google", "meta", "nvidia", "netflix", "amazon"):
            qs = [q for q in self.bank["questions"] if q["company"] == key]
            self.assertGreaterEqual(len(qs), 8, key)
            loop = self.bank["companies"][key]["loop"]
            self.assertTrue(any(r["basis"] == "official" for r in loop), key)
            for r in loop:
                self.assertIn(r["source"], self.bank["sources"])
        rounds = {r["round"] for r in self.bank["companies"]["amazon"]["loop"]}
        self.assertIn("bar-raiser", rounds)

    def test_one_question_per_leadership_principle(self):
        tested = [q["tests"] for q in self.bank["questions"] if q["round"] == "leadership-principles"]
        self.assertEqual(sorted(tested), sorted(LPS))

    def test_labels_say_what_is_official(self):
        q = [q for q in self.bank["questions"] if q["id"] == "google-behavioral-02"][0]
        self.assertIn("https://www.google.com/about/careers/applications/interview-tips/", star.label(self.bank, q))
        q = [q for q in self.bank["questions"] if q["basis"] == "community"][0]
        self.assertIn("not confirmed", star.label(self.bank, q))


class StarCheck(unittest.TestCase):
    def test_jordans_answer_is_complete(self):
        with open(ANSWER, encoding="utf-8") as fh:
            res = star.check(fh.read())
        self.assertEqual(res["score"], 5)
        self.assertIn("38%", res["found"]["N"])
        self.assertEqual(res["found"]["N"], res["found"]["R"])  # the number sits in the result
        self.assertGreaterEqual(len(res["found"]["A"]), 3)

    def test_a_vague_answer(self):
        res = star.check("We worked on a project and it went well. We improved things a lot. Everyone was happy.")
        self.assertLessEqual(res["score"], 2)
        joined = " ".join(res["notes"])
        for part in ("Situation", "Task", "Action", "Number"):
            self.assertIn(part, joined)
        self.assertIsNone(res["found"]["A"])

    def test_we_drowns_out_i(self):
        res = star.check("At Brightline Labs we had a slow API. We needed to fix it. We rewrote it, we tested it, "
                         "we shipped it, and we cut latency 38%.")
        self.assertTrue(any('say what YOU did' in n for n in res["notes"]))

    def test_cognition_is_not_action(self):
        self.assertEqual(star.i_actions("I thought about it and I wanted to help, so I felt good."), [])
        self.assertEqual(star.i_actions("I wrote the doc and I then ran the review."), ["I wrote", "I then ran"])


class Sessions(unittest.TestCase):
    def setUp(self):
        self.bank = star.load_bank()
        self.d = tempfile.mkdtemp()
        self.s = os.path.join(self.d, "hunter", "interviews", "google.json")

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_pick_is_deterministic(self):
        a = [q["id"] for q in star.pick(self.bank, "Google", "behavioral", 3, seed=7)]
        b = [q["id"] for q in star.pick(self.bank, "google", "behavioral", 3, seed=7)]
        self.assertEqual(a, b)
        first = [q["id"] for q in star.pick(self.bank, "google", "behavioral", 2)]
        self.assertEqual(first, ["google-behavioral-01", "google-behavioral-02"])
        nxt = [q["id"] for q in star.pick(self.bank, "google", "behavioral", 2, exclude=first)]
        self.assertEqual(nxt, ["google-behavioral-03", "google-behavioral-04"])
        other = star.pick(self.bank, "Brightline Labs", None, 3)
        self.assertTrue(all(q["company"] == "any" for q in other))

    def test_ask_log_review(self):
        code, out, _ = run(["ask", "--company", "google", "--round", "behavioral", "--count", "1",
                            "--session", self.s, "--today", "2026-10-20"])
        self.assertEqual(code, 0)
        self.assertIn("google-behavioral-01", out)
        code, out, _ = run(["log", "--session", self.s, "--question", "google-behavioral-01",
                            "--answer-file", ANSWER, "--today", "2026-10-20"])
        self.assertEqual(code, 0)
        self.assertIn("STAR 5/5", out)
        run(["log", "--session", self.s, "--question", "google-behavioral-02",
             "--text", "We worked on it together and it went fine.", "--today", "2026-10-20"])
        with open(self.s, encoding="utf-8") as fh:
            sess = json.load(fh)
        self.assertEqual(sess["started"], "2026-10-20")
        self.assertEqual([a["date"] for a in sess["attempts"]], ["2026-10-20", "2026-10-20"])
        r = star.review(sess, self.bank)
        self.assertEqual((r["attempts"], r["questions"]), (2, 2))
        self.assertEqual(r["below_4"], ["google-behavioral-02"])
        self.assertNotIn("google-behavioral-01", r["not_practiced"])
        code, out, _ = run(["ask", "--company", "google", "--round", "behavioral", "--count", "1",
                            "--session", self.s, "--today", "2026-10-21"])
        self.assertIn("google-behavioral-03", out)  # answered ones are skipped

    def test_loop_cli(self):
        code, out, _ = run(["loop", "--company", "Amazon"])
        self.assertEqual(code, 0)
        self.assertIn("Bar Raiser", out)
        self.assertIn("https://www.amazon.jobs/content/en/how-we-hire/interview-loop", out)
        code, out, _ = run(["loop", "--company", "Brightline Labs"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
