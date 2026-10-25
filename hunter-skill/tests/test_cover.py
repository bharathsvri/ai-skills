import io
import os
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, SKILLS

cover = load("hunter-cover", "cover")

EXAMPLE = os.path.join(SKILLS, "hunter-cover", "example-cover.md")
RESUME = os.path.join(SKILLS, "hunter-resume", "examples", "jordan-after.md")
PIPELINE = os.path.join(SKILLS, "hunter-tracker", "pipeline.example.json")
GENERIC = os.path.join(FIX, "hunter-cover", "generic-letter.md")
META_COPY = os.path.join(FIX, "hunter-cover", "meta-copy-letter.md")
GOOGLE = dict(company="Google", role="Software Engineer", team="Google Cloud, Infrastructure")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return fh.read()


def status(res):
    return {c["check"]: c["status"] for c in res["checks"]}


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cover.main(argv)
    return code, out.getvalue(), err.getvalue()


class JordansLetter(unittest.TestCase):
    def test_ready_with_every_check_passing(self):
        res = cover.check(read(EXAMPLE), resume_text=read(RESUME),
                          others=cover.other_companies(PIPELINE, "Google"), **GOOGLE)
        self.assertTrue(res["ready"])
        self.assertEqual(set(status(res).values()), {"PASS"})
        self.assertTrue(150 <= res["words"] <= 400)
        self.assertLessEqual(res["reading"]["grade"], 12)

    def test_cli_exit_codes(self):
        code, out, _ = run(["check", EXAMPLE, "--company", "Google", "--role", "Software Engineer",
                            "--team", "Google Cloud, Infrastructure", "--resume", RESUME, "--pipeline", PIPELINE])
        self.assertEqual(code, 0)
        self.assertIn("READY", out)
        code, out, _ = run(["check", GENERIC, "--company", "Google", "--role", "Software Engineer"])
        self.assertEqual(code, 1)
        self.assertIn("FIX", out)


class BadLetters(unittest.TestCase):
    def test_the_generic_letter_fails_loudly(self):
        res = cover.check(read(GENERIC), **GOOGLE)
        s = status(res)
        for k in ("length", "greeting", "company", "role", "team", "proof", "cliches", "placeholders"):
            self.assertEqual(s[k], "FAIL", k)
        cl = [c for c in res["checks"] if c["check"] == "cliches"][0]["detail"]
        for phrase in ("to whom it may concern", "team player", "passionate about", "proven track record"):
            self.assertIn(phrase, cl)
        ph = [c for c in res["checks"] if c["check"] == "placeholders"][0]["detail"]
        self.assertIn("[Company]", ph)

    def test_a_letter_copied_from_another_application(self):
        res = cover.check(read(META_COPY), resume_text=read(RESUME),
                          others=cover.other_companies(PIPELINE, "Google"), **GOOGLE)
        s = status(res)
        self.assertEqual(s["other names"], "FAIL")
        self.assertIn("Meta", [c for c in res["checks"] if c["check"] == "other names"][0]["detail"])
        self.assertEqual(s["numbers"], "FAIL")  # "cut our cloud bill 45%" is not in the resume
        self.assertIn("45", [c for c in res["checks"] if c["check"] == "numbers"][0]["detail"])

    def test_other_companies_come_from_the_pipeline(self):
        self.assertEqual(cover.other_companies(PIPELINE, "Google"), ["Meta", "NVIDIA", "Netflix", "Amazon"])


class Helpers(unittest.TestCase):
    def test_reading_level(self):
        easy = cover.reading("I ran the team. We shipped it. It was fast.")
        hard = cover.reading("Organizational transformation necessitates comprehensive interdepartmental "
                             "collaboration, institutionalized accountability and multidimensional evaluation.")
        self.assertLess(easy["grade"], 4)
        self.assertGreater(hard["grade"], 15)

    def test_sign_off_is_not_the_ask(self):
        text = read(EXAMPLE)
        res = cover.check(text, **GOOGLE)
        self.assertEqual(status(res)["ask"], "PASS")
        no_ask = text.replace("Would you be open to a short call in the next few weeks about what the team is "
                              "building next? I would value your view on where someone with my background "
                              "could help first.", "I look forward to it.")
        self.assertEqual(status(cover.check(no_ask, **GOOGLE))["ask"], "WARN")

    def test_role_words(self):
        res = cover.check(read(EXAMPLE), company="Google", role="Site Reliability Engineer")
        self.assertEqual(status(res)["role"], "FAIL")


if __name__ == "__main__":
    unittest.main()
