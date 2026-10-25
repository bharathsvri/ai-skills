import datetime
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import FIX, load

brief = load("hunter-research", "brief")
DIR = os.path.join(FIX, "hunter-research")
TODAY = datetime.date(2026, 10, 15)
EM = chr(0x2014)
OWN_DOMAINS = {
    "Google": "https://www.google.com/about/careers/",
    "Meta": "https://www.metacareers.com/",
    "NVIDIA": "https://www.nvidia.com/",
    "Netflix": "https://jobs.netflix.com/",
    "Amazon": "https://www.amazon.jobs/",
}


def raw(name):
    with open(os.path.join(DIR, name), "rb") as fh:
        return fh.read()


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = brief.main(args)
    return code, out.getvalue(), err.getvalue()


class Sec(unittest.TestCase):
    def setUp(self):
        self.sec = brief.sec_summary(json.loads(raw("submissions-CIK0001652044.json")), TODAY, 180)

    def test_facts(self):
        self.assertEqual(self.sec["name"], "Alphabet Inc.")
        self.assertEqual(self.sec["tickers"][:2], ["GOOGL", "GOOG"])
        self.assertEqual(self.sec["hq"], "1600 Amphitheatre Parkway, Mountain View, CA")
        self.assertEqual(self.sec["fiscal_year_end"], "December 31")

    def test_filings(self):
        self.assertEqual(self.sec["annual"]["url"],
                         "https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm")
        self.assertEqual(self.sec["annual"]["period"], "2025-12-31")
        self.assertEqual(self.sec["quarterly"]["filed"], "2026-07-23")
        self.assertEqual(self.sec["proxy"]["form"], "DEF 14A")
        events = self.sec["events"]
        self.assertEqual([e["filed"] for e in events][:3], ["2026-08-10", "2026-07-22", "2026-06-11"])
        self.assertEqual(len(events), 9)  # 8-Ks in the 180 days to 2026-10-15
        earn = [e for e in events if e["filed"] == "2026-07-22"][0]
        self.assertEqual(earn["about"], "earnings results")
        self.assertEqual(events[2]["about"], "director or officer change, shareholder vote results")

    def test_ticker_lookup(self):
        f = brief.Fetcher(offline=DIR)
        self.assertEqual(brief.cik_for(f, "goog"), "0001652044")
        self.assertEqual(brief.cik_for(f, "NFLX"), "0001065280")
        with self.assertRaises(brief.BriefError):
            brief.cik_for(f, "ZZZZ")

    def test_user_agent_rules(self):
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            self.assertIsNone(brief.sec_user_agent(None, "/nonexistent/profile.json"))
            self.assertIsNone(brief.sec_user_agent("Your Name you@example.com"))
            self.assertIsNone(brief.sec_user_agent("no email here"))
            self.assertEqual(brief.sec_user_agent("Hunter Skill test admin@example.com"),
                             "Hunter Skill test admin@example.com")
            with self.assertRaises(brief.BriefError):
                brief.Fetcher(None).get("https://data.sec.gov/x", "x", sec=True)
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old


class Feeds(unittest.TestCase):
    def test_rss(self):
        items = brief.parse_feed(raw("feed-google-blog.xml"), "News from Google")
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["title"], "An intelligent new shopping cart")
        self.assertEqual(items[0]["date"], datetime.date(2026, 10, 15))
        self.assertTrue(items[0]["link"].startswith("https://blog.google/"))

    def test_atom(self):
        items = brief.parse_feed(raw("feed-nvidia-dev.xml"), "NVIDIA Technical Blog")
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["link"].startswith("https://developer.nvidia.com/blog/"))
        self.assertEqual(items[0]["date"], datetime.date(2026, 10, 14))

    def test_dates_are_utc_in_any_time_zone(self):
        self.assertEqual(brief.feed_day("2026-10-14T23:30:00-05:00"), datetime.date(2026, 10, 15))
        self.assertEqual(brief.feed_day("Wed, 14 Oct 2026 23:30:00 -0500"), datetime.date(2026, 10, 15))
        self.assertEqual(brief.feed_day("2026-10-14T16:10:45Z"), datetime.date(2026, 10, 14))
        self.assertIsNone(brief.feed_day("soon"))

    def test_window_and_missing_feeds(self):
        notes = []
        feeds = [{"id": "google-blog", "name": "News from Google", "url": "x"},
                 {"id": "missing", "name": "Missing", "url": "y"}]
        posts = brief.fetch_feeds(brief.Fetcher(offline=DIR), feeds, TODAY, days=30, notes=notes)
        self.assertEqual(len(posts), 3)
        self.assertIn("Missing", notes[0])
        later = brief.fetch_feeds(brief.Fetcher(offline=DIR), feeds[:1], datetime.date(2027, 1, 1), days=30)
        self.assertEqual(later, [])


class Loops(unittest.TestCase):
    def test_every_note_is_cited_or_marked(self):
        doc = brief.load_json(brief.LOOPS)
        self.assertEqual(sorted(doc["companies"]), sorted(OWN_DOMAINS))
        for company, entry in doc["companies"].items():
            self.assertTrue(entry["prep_pages"], company)
            for page in entry["prep_pages"]:
                self.assertTrue(page["url"].startswith(OWN_DOMAINS[company]), page["url"])
            kinds = {n["kind"] for n in entry["notes"]}
            self.assertIn("official", kinds, company)
            for n in entry["notes"]:
                if n["kind"] == "official":
                    self.assertTrue(n["source"].startswith(OWN_DOMAINS[company]), n)
                else:
                    self.assertEqual((n["kind"], n["source"]), ("community-reported", "community-reported"))

    def test_loop_command(self):
        code, out, _ = run(["loop", "--company", "amazon"])
        self.assertEqual(code, 0)
        self.assertIn("four 55-minute interviews", out)
        self.assertIn("[source: https://www.amazon.jobs/content/en/how-we-hire/sde-ii-interview-prep]", out)
        self.assertIn("Community-reported, not confirmed by the company: The Bar Raiser", out)
        code, out, _ = run(["loop", "--company", "Acme Rockets"])
        self.assertEqual(code, 1)
        self.assertIn("(fill in)", out)

    def test_companies_file(self):
        doc = brief.load_json(brief.COMPANIES)
        for name in OWN_DOMAINS:
            info = doc["companies"][name]
            self.assertRegex(info["cik"], r"^\d{10}$")
            self.assertTrue(info["feeds"])


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, "hunter", "companies", "google.md")
        self.base = ["build", "--company", "google", "--role", "Software Engineer",
                     "--team", "Google Cloud, Infrastructure", "--candidate", "Jordan Reyes",
                     "--offline", DIR, "--today", "2026-10-15", "--out", self.out]

    def tearDown(self):
        self.tmp.cleanup()

    def test_brief(self):
        code, out, err = run(self.base)
        self.assertEqual(code, 0, err)
        with open(self.out, encoding="utf-8") as fh:
            text = fh.read()
        self.assertTrue(text.startswith("# Google: research brief"))
        self.assertIn("Prepared 2026-10-15 for Jordan Reyes", text)
        self.assertIn("Headquarters on file with the SEC: 1600 Amphitheatre Parkway, Mountain View, CA", text)
        self.assertIn("goog-20251231.htm", text)
        self.assertIn("- 2026-07-22 8-K: earnings results", text)
        self.assertIn("Latest results: the 8-K of 2026-07-22 (item 2.02)", text)
        self.assertIn("News from Google: An intelligent new shopping cart", text)
        self.assertIn("Team named in the posting: Google Cloud, Infrastructure", text)
        self.assertIn("AI tools are not permitted during Google interviews.", text)
        self.assertIn("Community-reported, not confirmed by the company", text)
        self.assertIn("(fill in)", text)
        self.assertIn("## Sources", text)
        self.assertNotIn("{{", text)
        self.assertNotIn(EM, text)
        self.assertIn("Google Cloud Blog: offline: no file", text)  # notes say what was missing

    def test_existing_brief_is_kept(self):
        self.assertEqual(run(self.base)[0], 0)
        with open(self.out, "a") as fh:
            fh.write("my notes\n")
        code, _, err = run(self.base)
        self.assertEqual(code, 3)
        self.assertIn("--force", err)
        with open(self.out) as fh:
            self.assertIn("my notes", fh.read())
        self.assertEqual(run(self.base + ["--force"])[0], 0)

    def test_private_company(self):
        code, out, _ = run(["build", "--company", "Brightline Labs", "--offline", DIR, "--today", "2026-10-15",
                            "--stdout", "--profile", os.path.join(self.tmp.name, "none.json")])
        self.assertEqual(code, 0)
        self.assertIn("Private companies do not file with the SEC", out)
        self.assertIn("No bundled loop for this company", out)

    def test_sec_skipped_without_user_agent(self):
        old = os.environ.pop("SEC_USER_AGENT", None)
        try:
            code, out, _ = run(["sec", "--company", "Google", "--today", "2026-10-15",
                                "--profile", os.path.join(self.tmp.name, "none.json")])
        finally:
            if old is not None:
                os.environ["SEC_USER_AGENT"] = old
        self.assertEqual(code, 1)
        self.assertIn("SEC filings skipped", out)


if __name__ == "__main__":
    unittest.main()
