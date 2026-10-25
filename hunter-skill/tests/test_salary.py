import io
import json
import os
import re
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from _load import load, FIX, SKILLS

offer = load("hunter-salary", "offer")

HERE = os.path.join(SKILLS, "hunter-salary")
GOOGLE = os.path.join(HERE, "offer.example.json")
AMAZON = os.path.join(HERE, "competing.example.json")
BENCH = os.path.join(HERE, "bench.example.json")
BLS = os.path.join(FIX, "hunter-salary", "bls-oews-15-1252-2025.json")


def read(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = offer.main(argv)
    return code, out.getvalue(), err.getvalue()


class TotalComp(unittest.TestCase):
    def test_even_vesting(self):
        t = offer.yearly(read(GOOGLE))
        self.assertEqual([r["tc"] for r in t["years"]], [282750, 262750, 262750, 262750])
        self.assertEqual(t["total"], 1071000)
        self.assertEqual(t["one_time"], 10000)  # relocation stays out of TC

    def test_back_loaded_vesting_with_a_two_year_sign_on(self):
        t = offer.yearly(read(AMAZON))
        self.assertEqual([r["equity"] for r in t["years"]], [10000, 30000, 80000, 80000])
        self.assertEqual([r["tc"] for r in t["years"]], [230000, 240000, 255000, 255000])
        self.assertEqual(t["total"], 980000)

    def test_schedules_and_errors(self):
        self.assertEqual(offer.schedule({"vesting": "front-loaded"}), [33, 33, 22, 12])
        self.assertEqual(offer.schedule({"vesting": [10, 20, 30, 40]}), [10.0, 20.0, 30.0, 40.0])
        for bad in ({"vesting": [25, 25, 25]}, {"vesting": "mystery"}, {"vesting": [-5, 105]}):
            with self.assertRaises(offer.OfferError):
                offer.schedule(bad)
        self.assertEqual(offer.grant_value({"shares": 100, "share_price": 250.5}), 25050)
        with self.assertRaises(offer.OfferError):
            offer.grant_value({"shares": 100})
        raised = offer.yearly({"base": 100000, "raise_pct": 10, "equity": {"grant_value": 0, "vesting": "even-4"}})
        self.assertAlmostEqual(raised["years"][1]["base"], 110000)
        with self.assertRaises(offer.OfferError):
            offer.yearly({"company": "X"})

    def test_compare_calls_out_the_back_loaded_offer(self):
        text = offer.render_compare([offer.yearly(read(GOOGLE)), offer.yearly(read(AMAZON))])
        self.assertIn("Highest in year 1: Google. Highest over the full schedule: Google.", text)
        self.assertIn("Amazon changes a lot by year", text)
        self.assertIn("5/15/40/40", text)


class Bls(unittest.TestCase):
    def test_series_ids(self):
        self.assertEqual(offer.series_ids("15-1252", "msa:41940")["p50"], "OEUM004194000000015125213")
        self.assertEqual(offer.series_ids("15-1252", "state:CA")["p75"], "OEUS060000000000015125214")
        self.assertEqual(offer.series_ids("15-1252", "national")["mean"], "OEUN000000000000015125204")
        for bad in (("15125", "national"), ("15-1252", "msa:419"), ("15-1252", "state:ZZ"), ("15-1252", "moon")):
            with self.assertRaises(offer.OfferError):
                offer.series_ids(*bad)

    def test_real_bls_response(self):
        resp = read(BLS)
        sj = offer.bls_benchmark(resp, "15-1252", "msa:41940", 2025)
        self.assertEqual((sj["p10"], sj["p25"], sj["p50"], sj["p75"], sj["p90"], sj["mean"]),
                         (138420, 173650, 213110, 226080, 289150, 221710))
        self.assertEqual(sj["label"],
                         "BLS OEWS May 2025, Software Developers (SOC 15-1252), San Jose-Sunnyvale-Santa Clara, CA")
        self.assertTrue(sj["url"].endswith("OEUM004194000000015125213"))
        us = offer.bls_benchmark(resp, "15-1252", "national", 2025)
        self.assertEqual(us["p50"], 135980)
        chi = offer.bls_benchmark(resp, "15-1252", "msa:16980", 2025, area_name="Chicago metro area")
        self.assertEqual(chi["p50"], 134380)
        with self.assertRaises(offer.OfferError):
            offer.bls_benchmark(resp, "15-1252", "msa:41940", 2024)  # not in the file: no number is made up
        with self.assertRaises(offer.OfferError):
            offer.bls_benchmark({"status": "REQUEST_NOT_PROCESSED", "message": ["daily limit"]}, "15-1252",
                                "national", 2025)

    def test_the_shipped_bench_matches_the_bls_file(self):
        bench = offer.load_bench([BENCH])
        resp = read(BLS)
        for b, area in zip(bench, ("msa:41940", "national")):
            fresh = offer.bls_benchmark(resp, "15-1252", area, 2025)
            for k in ("p10", "p25", "p50", "p75", "p90", "mean", "url", "label"):
                self.assertEqual(b[k], fresh[k])

    def test_bls_cli_offline_writes_the_bench(self):
        d = tempfile.mkdtemp()
        try:
            out_path = os.path.join(d, "hunter", "offers", "bench.json")
            code, out, _ = run(["bls", "--soc", "15-1252", "--area", "msa:41940", "--offline", BLS, "--out", out_path])
            self.assertEqual(code, 0)
            self.assertEqual(read(out_path)["benchmarks"][0]["p50"], 213110)
            run(["bls", "--soc", "15-1252", "--area", "msa:41940", "--offline", BLS, "--out", out_path])
            self.assertEqual(len(read(out_path)["benchmarks"]), 1)  # same label replaced, not duplicated
        finally:
            shutil.rmtree(d)


class Benchmarks(unittest.TestCase):
    def test_no_source_no_number(self):
        d = tempfile.mkdtemp()
        try:
            p = os.path.join(d, "b.json")
            for bad in ({"label": "a friend said", "kind": "base", "p50": 250000},
                        {"label": "posting", "kind": "posting_range", "source": "the posting", "min": 1, "max": 2},
                        {"label": "x", "kind": "vibes", "source": "me", "url": "https://example.com"}):
                with open(p, "w") as fh:
                    json.dump({"benchmarks": [bad]}, fh)
                with self.assertRaises(offer.OfferError):
                    offer.load_bench([p])
        finally:
            shutil.rmtree(d)

    def test_position(self):
        sj = offer.load_bench([BENCH])[0]
        self.assertEqual(offer.position(185000, sj), "between the 25th and the median")
        self.assertEqual(offer.position(300000, sj), "above the 90th percentile")
        self.assertEqual(offer.position(100000, sj), "below the 10th percentile")
        rng = {"kind": "posting_range", "min": 150000, "max": 250000}
        self.assertEqual(offer.position(200000, rng), "50% of the way up the posted range")


class Counter(unittest.TestCase):
    def setUp(self):
        self.google = read(GOOGLE)
        self.bench = offer.load_bench([BENCH])

    def test_jordans_counter(self):
        c = offer.counter(self.google, self.bench, read(AMAZON), floor=180000)
        self.assertEqual(c["ask"], 213000)  # 15% cap on 185,000 is 212,750, rounded up
        self.assertEqual(c["middle"], 199000)
        self.assertIn("15%", c["capped_by"])
        self.assertEqual(sorted(e["value"] for e in c["evidence"]), [213110, 226080])
        self.assertFalse(c["below_floor"])
        self.assertIsNone(c["sign_on_ask"])  # the Amazon offer is lower in year 1
        self.assertEqual(c["gaps"], {"year1": -52750, "total": -91000})

    def test_the_script_only_uses_cited_numbers(self):
        c = offer.counter(self.google, self.bench, read(AMAZON), floor=180000)
        text = offer.script(c, self.google, me="Jordan Reyes")
        allowed = {"213,110", "226,080", "213,000", "2025", "75"}  # 75 = "75th percentile"
        found = set(re.findall(r"\d+(?:,\d{3})*", text))
        self.assertTrue(found <= allowed, found - allowed)
        self.assertIn("BLS wage data (OEWS, May 2025)", text)
        self.assertNotIn("Amazon", text)  # not shared unless the user says so
        self.assertNotIn("other offer", text)
        self.assertTrue(text.rstrip().endswith("Jordan"))

    def test_a_posted_range_caps_the_ask(self):
        # synthetic range for the test only, not a real posting
        rng = {"label": "test range", "kind": "posting_range", "source": "test", "url": "https://example.com/job",
               "min": 160000, "max": 200000}
        c = offer.counter(self.google, self.bench + [rng])
        self.assertEqual(c["ask"], 200000)
        self.assertEqual(c["capped_by"], "the top of the posted range")
        self.assertIn("sign-on", offer.script(c, self.google))

    def test_a_real_competing_base_is_not_capped(self):
        comp = {"company": "Other Co", "base": 230000}  # synthetic, for the test
        c = offer.counter(self.google, [], comp)
        self.assertEqual(c["ask"], 230000)
        self.assertIsNone(c["capped_by"])
        self.assertIn("I also have an offer with a base of $230,000", offer.script(c, self.google, share_competing=True))
        self.assertNotIn("I also have an offer", offer.script(c, self.google, share_competing=False))

    def test_no_evidence_no_number(self):
        c = offer.counter(dict(self.google, base=300000), self.bench)
        self.assertIsNone(c["ask"])
        text = offer.script(c, self.google)
        self.assertIn("flexibility", text)
        self.assertEqual(re.findall(r"\$\d", text), [])

    def test_floor(self):
        c = offer.counter(self.google, self.bench, floor=190000)
        self.assertTrue(c["below_floor"])
        self.assertIn("below your floor", offer.render_counter(c, self.google))

    def test_counter_cli(self):
        code, out, _ = run(["counter", GOOGLE, "--bench", BENCH, "--competing", AMAZON, "--floor", "180000",
                            "--me", "Jordan Reyes", "--profile", os.path.join(HERE, "missing.json")])
        self.assertEqual(code, 0)
        self.assertIn("Ask:    $213,000", out)
        self.assertIn("No outcome is guaranteed", out)


if __name__ == "__main__":
    unittest.main()
