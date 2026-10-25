"""Tests for the BUILD skill tools (stdlib unittest, no network beyond 127.0.0.1).

Run from skills/build:  python3 -m unittest discover -s tools -p "test_*.py"
"""
import contextlib
import io
import json
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import contrast  # noqa: E402
import serve  # noqa: E402
import sitecheck  # noqa: E402


def png(w, h, noise=False):
    """A real, decodable PNG (grayscale; random pixels when noise=True)."""
    rng = random.Random(7)
    rows = b"".join(b"\x00" + (bytes(rng.getrandbits(8) for _ in range(w)) if noise else b"\x00" * w)
                    for _ in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))


def write(root, rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode("utf-8"))


GOOD_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="A fixture page.">
<meta property="og:image" content="https://example.com/share.png">
<link rel="icon" href="/favicon.svg">
</head>
"""


def build_bad_site(root, external):
    write(root, "index.html", GOOD_HEAD.format(title="Home").replace(
        '<meta name="description" content="A fixture page.">\n', "").replace(
        'content="https://example.com/share.png"', 'content="/img/hero.png"') + """<body>
<link rel="stylesheet" href="/css/site.css">
<link rel="stylesheet" href="/css/missing.css">
<h1>Home</h1>
<nav><a href="/about.html">About</a> <a href="/nope.html">Gone</a> <a href="#pricing">Pricing</a>
<a href="#">Soon</a> <a href="/about.html#team">Team</a> <a href="/about.html#nobody">Nobody</a>
<a href="/zoom.html">Zoom</a> <a href="EXT/dead">Partner</a></nav>
<img src="/img/hero.png" width="4" height="3">
<img src="/img/heavy.png" alt="Heavy">
<img src="/img/wide.png" alt="Wide" width="100" height="50">
<img src="/img/missing.png" alt="Missing" width="10" height="10">
<img src="EXT/ok.png" alt="Partner logo" width="4" height="3">
<section id="dup">A</section><section id="dup">B</section>
<a href="/docs/"><svg viewBox="0 0 10 10"><path d="M0 0h1"/></svg></a>
<button><svg viewBox="0 0 10 10"><path d="M0 0h1"/></svg></button>
<button aria-label="Close menu"><svg viewBox="0 0 10 10"></svg></button>
<form action="/subscribe"><input type="email" placeholder="Email"><button>Join</button></form>
<label>Name <input type="text" name="n"></label>
<label for="phone">Phone</label><input id="phone" type="tel">
<p>Lorem ipsum dolor sit amet.</p>
<script src="/js/app.js"></script>
<script src="/js/missing.js"></script>
</body></html>
""".replace("EXT/", external))
    write(root, "about.html", "<html><head></head><body>\n<h2 id=\"team\">Team</h2>\n"
                              "<a href=\"/deep1.html\">Deeper</a>\n</body></html>\n")
    write(root, "zoom.html", GOOD_HEAD.format(title="Zoom").replace(
        "initial-scale=1", "initial-scale=1, maximum-scale=1, user-scalable=no").replace(
        "</head>", '<meta name="robots" content="noindex">\n</head>') + "<body><h1>Zoom</h1></body></html>")
    write(root, "deep1.html", GOOD_HEAD.format(title="D1") + '<body><h1>D1</h1><a href="/deep2.html">n</a></body></html>')
    write(root, "deep2.html", GOOD_HEAD.format(title="D2") + '<body><h1>D2</h1><a href="/deep3.html">n</a></body></html>')
    write(root, "deep3.html", GOOD_HEAD.format(title="D3") + '<body><h1>D3</h1><a href="/deep4.html">n</a></body></html>')
    write(root, "css/site.css", '@font-face { font-family: X; src: url("/fonts/x.woff2"); }\n'
                                ".hero { background: url(../img/hero.png); }\n")
    write(root, "js/app.js", "console.log('ok');\n")
    write(root, "favicon.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
    write(root, "img/hero.png", png(4, 3))
    write(root, "img/heavy.png", png(260, 260, noise=True))   # ~66 KB, over a 50 KB budget
    write(root, "img/wide.png", png(2000, 1000))              # tiny file, far too many pixels


def build_good_site(root):
    for name, title, link in (("index.html", "Home", "/about.html"), ("about.html", "About", "/")):
        write(root, name, GOOD_HEAD.format(title=title) + """<body>
<main><h1>{t}</h1><p>Real words.</p><a href="{l}">Next</a>
<img src="/img/a.png" alt="A square" width="4" height="3"></main></body></html>
""".format(t=title, l=link))
    write(root, "favicon.svg", '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"/>')
    write(root, "img/a.png", png(4, 3))


class SiteCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="buildtest-")
        cls.ext_root = os.path.join(cls.tmp, "external")
        write(cls.ext_root, "ok.png", png(4, 3))
        cls.ext_server, cls.ext_url = serve.start(cls.ext_root)
        cls.bad = os.path.join(cls.tmp, "bad")
        build_bad_site(cls.bad, cls.ext_url)
        cls.good = os.path.join(cls.tmp, "good")
        build_good_site(cls.good)
        cls.server, cls.url = serve.start(cls.bad)
        cls.report = cls.run_check(cls.url, max_image_kb=50)

    @classmethod
    def tearDownClass(cls):
        serve.stop(cls.server)
        serve.stop(cls.ext_server)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def run_check(target, **kw):
        return sitecheck.check_site(target, sitecheck.Options(**kw))

    def rules(self, report=None):
        return [f["rule"] for f in (report or self.report)["findings"]]

    def find(self, rule, needle="", report=None):
        return [f for f in (report or self.report)["findings"]
                if f["rule"] == rule and needle in (f["url"] + " " + f["page"] + " " + f["detail"])]

    def test_planted_errors_are_found(self):
        self.assertTrue(self.find("broken-link", "/nope.html"))
        self.assertTrue(self.find("broken-anchor", "pricing"))
        self.assertTrue(self.find("broken-anchor", "nobody"))
        self.assertFalse(self.find("broken-anchor", "team"), "existing #team must not be flagged")
        for missing in ("/css/missing.css", "/img/missing.png", "/js/missing.js", "/fonts/x.woff2"):
            self.assertTrue(self.find("broken-asset", missing), missing)
        for rule in ("missing-title", "missing-viewport", "missing-lang", "missing-doctype"):
            self.assertTrue(self.find(rule, "/about.html"), rule)
        self.assertTrue(self.find("zoom-disabled", "/zoom.html"))
        self.assertTrue(self.find("img-missing-alt", "/img/hero.png"))
        self.assertTrue(self.find("duplicate-id", 'id="dup"'))
        self.assertEqual(len(self.find("unlabeled-field")), 1, "only the placeholder-only field is unlabeled")
        self.assertEqual(len(self.find("unnamed-button")), 1, "aria-label button is named")
        self.assertTrue(self.find("unnamed-link"))

    def test_planted_warnings_are_found(self):
        self.assertTrue(self.find("missing-description", "/about.html"))
        self.assertTrue(self.find("img-missing-size", "/img/heavy.png"))
        self.assertTrue(self.find("image-heavy", "/img/heavy.png"))
        self.assertFalse(self.find("image-heavy", "/img/wide.png"))
        self.assertTrue(self.find("image-oversized", "/img/wide.png"))
        self.assertTrue(self.find("placeholder-link"))
        self.assertTrue(self.find("lorem-ipsum"))
        self.assertTrue(self.find("noindex", "/zoom.html"))
        self.assertTrue(self.find("relative-og-image"))
        self.assertTrue(self.find("missing-h1", "/about.html"))
        self.assertTrue(self.find("missing-charset", "/about.html"))

    def test_existing_things_are_not_flagged(self):
        for ok in ("/js/app.js", "/img/hero.png", "/favicon.svg", "/about.html", "/css/site.css"):
            bad = [f for f in self.report["findings"] if f["rule"] in ("broken-asset", "broken-link")
                   and f["url"].endswith(ok)]
            self.assertFalse(bad, ok)
        self.assertNotIn("missing-favicon", self.rules())

    def test_external_only_with_flag(self):
        self.assertNotIn("external-link", self.rules())
        self.assertGreaterEqual(self.report["stats"]["external_skipped"], 2)
        rep = self.run_check(self.url, external=True)
        self.assertTrue(self.find("external-link", "/dead", rep))
        self.assertFalse(self.find("external-asset", "ok.png", rep))

    def test_depth_and_limit(self):
        self.assertFalse(self.find("broken-link", "/deep4.html"), "deep3 is past depth 3")
        deeper = self.run_check(self.url, depth=4)
        self.assertTrue(self.find("broken-link", "/deep4.html", deeper))
        self.assertEqual(self.run_check(self.url, depth=0)["stats"]["pages"], 1)
        self.assertEqual(self.run_check(self.url, limit=2)["stats"]["pages"], 2)

    def test_ignore_and_exclude(self):
        rep = self.run_check(self.url, ignore={"lorem-ipsum"}, exclude=["nope"])
        self.assertNotIn("lorem-ipsum", self.rules(rep))
        self.assertFalse(self.find("broken-link", "/nope.html", rep))

    def test_clean_site_passes_strict(self):
        rep = self.run_check(self.good, strict=True)
        self.assertEqual(rep["findings"], [], rep["findings"])
        self.assertEqual(rep["summary"]["result"], "pass")

    def test_mixed_content_and_local_urls(self):
        html = ('<!doctype html><html lang="en"><head><title>t</title></head><body>'
                '<img src="http://example.com/a.png" alt="a" width="1" height="1">'
                '<form action="http://example.com/f"></form>'
                '<a href="http://localhost:3000/">dev</a></body></html>')
        res = sitecheck.analyze(html, "https://example.com/", site_is_local=False)
        rules = [f.rule for f in res.findings]
        self.assertEqual(rules.count("mixed-content"), 2)
        self.assertIn("local-url", rules)

    def test_helpers(self):
        self.assertEqual(sitecheck.parse_srcset("a.png 1x, b.png 2x,c.png"), ["a.png", "b.png", "c.png"])
        self.assertEqual(sitecheck.image_size(png(37, 21)), (37, 21))
        self.assertEqual(sitecheck.normalize("HTTP://Example.COM:80/a b#x"), "http://example.com/a%20b")

    def test_cli_json_and_exit_codes(self):
        cli = [sys.executable, os.path.join(HERE, "sitecheck.py")]
        bad = subprocess.run(cli + [self.bad, "--json"], capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 1, bad.stderr)
        data = json.loads(bad.stdout)
        self.assertGreater(data["summary"]["errors"], 0)
        self.assertTrue(all({"severity", "rule", "url", "line", "fix"} <= set(f) for f in data["findings"]))
        good = subprocess.run(cli + [self.good], capture_output=True, text=True, timeout=60)
        self.assertEqual(good.returncode, 0, good.stdout)
        self.assertIn("PASS", good.stdout)
        down = subprocess.run(cli + ["http://127.0.0.1:9/"], capture_output=True, text=True, timeout=60)
        self.assertEqual(down.returncode, 2)
        self.assertEqual(subprocess.run(cli + ["--list-rules"], capture_output=True).returncode, 0)


class ServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="servetest-")
        write(cls.tmp, "index.html", "<h1>home</h1>")
        write(cls.tmp, "about.html", "<h1>about</h1>")
        write(cls.tmp, "404.html", "<h1>custom 404</h1>")
        write(cls.tmp, "app.mjs", "export {}")
        write(cls.tmp, "font.woff2", b"wOF2")
        write(cls.tmp, "docs/index.html", "docs")
        write(cls.tmp, "video.mp4", b"0123456789")
        cls.plain, cls.url = serve.start(cls.tmp)
        cls.fancy, cls.furl = serve.start(cls.tmp, spa=True, clean_urls=True)

    @classmethod
    def tearDownClass(cls):
        serve.stop(cls.plain)
        serve.stop(cls.fancy)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, url, headers=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {})) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers), e.read()

    def test_basics(self):
        status, headers, body = self.get(self.url)
        self.assertEqual((status, body), (200, b"<h1>home</h1>"))
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(self.get(self.url + "app.mjs")[1]["Content-Type"], "text/javascript")
        self.assertEqual(self.get(self.url + "font.woff2")[1]["Content-Type"], "font/woff2")
        self.assertEqual(self.get(self.url + "docs")[2], b"docs")  # redirect to docs/ followed

    def test_host_style_404_and_modes(self):
        status, _, body = self.get(self.url + "nope")
        self.assertEqual((status, body), (404, b"<h1>custom 404</h1>"))
        self.assertEqual(self.get(self.furl + "about")[2], b"<h1>about</h1>")      # clean URL
        self.assertEqual(self.get(self.furl + "app/route")[2], b"<h1>home</h1>")   # SPA fallback
        self.assertEqual(self.get(self.furl + "missing.png")[0], 404)             # assets still 404

    def test_range_requests(self):
        status, headers, body = self.get(self.url + "video.mp4", {"Range": "bytes=2-5"})
        self.assertEqual((status, body), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")


class ContrastTest(unittest.TestCase):
    def test_ratios_and_parsing(self):
        p = contrast.parse_color
        self.assertAlmostEqual(contrast.ratio(p("#000"), p("white")), 21.0, places=2)
        self.assertAlmostEqual(contrast.ratio(p("#777777"), p("#fff")), 4.48, places=2)
        self.assertEqual(contrast.to_hex(p("rgb(255 0 0)")), "#ff0000")
        self.assertEqual(contrast.to_hex(p("hsl(120, 100%, 25%)")), "#008000")
        self.assertEqual(contrast.to_hex(p("oklch(62.8% 0.2577 29.23)")), "#ff0000")

    def test_suggestion_passes(self):
        hexed, r = contrast.suggest(contrast.parse_color("#999"), contrast.parse_color("#fff"), 4.5)
        self.assertGreaterEqual(contrast.ratio(contrast.parse_color(hexed), contrast.parse_color("#fff")), 4.5)

    def test_css_tokens_and_exit_code(self):
        css = (":root { --ink: #111; --paper: #fff; --muted: #aaa; }\n"
               "@media (prefers-color-scheme: dark) { :root { --ink: #eee; --paper: #111; } }")
        self.assertEqual(contrast.read_vars(css, dark=True)["--paper"], "#111")
        with tempfile.NamedTemporaryFile("w", suffix=".css", delete=False) as fh:
            fh.write(css)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                ok = contrast.main(["--css", fh.name, "--pair", "ink:paper", "--json"])
                bad = contrast.main(["--css", fh.name, "--pair", "muted:paper", "--json"])
            self.assertEqual((ok, bad), (0, 1))
        finally:
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()
