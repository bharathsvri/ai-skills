#!/usr/bin/env python3
"""
pull.py - turn a list of X post URLs you chose into a swipe sheet, with the
exact text, line breaks, author, date and format filled in, and the four
number columns left for you.

It uses X's documented oEmbed API (publish.x.com/oembed), the endpoint that
exists so websites can embed a public post from its URL. No login, no key,
no cookies, nothing about you is sent. One request per post, one post per
second, and a hard cap per run.

What it deliberately does NOT do:

  - find posts. You pick them, by opening the account and copying the links.
    X's Terms prohibit crawling or scraping "in any form, for any purpose"
    without written consent, so there is no timeline walker, no search, no
    follower list and no loop here, and there should not be.
  - fetch counts. oEmbed does not carry views or likes, and the endpoints
    that do are undocumented. Views are public on every post, so you read
    them off the screen and type them in. It is 30 numbers.

Usage
  python3 pull.py urls.txt > swipe.tsv          # one URL per line
  python3 pull.py https://x.com/a/status/1 https://x.com/b/status/2
  python3 pull.py urls.txt --max 60

Then open swipe.tsv, fill in views (and likes, replies, reposts if you have
them), and run swipe.py on it.
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ENDPOINT = "https://publish.x.com/oembed"
UA = "x-agent-skill/1.0 (+https://github.com/Jakeschincariol/x-agent-skill)"
STATUS_RE = re.compile(r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status(?:es)?/(\d+)")
COLUMNS = ["url", "account", "name", "date", "format", "lines", "words", "views", "likes",
           "replies", "reposts", "hook", "text"]


def parse_urls(items):
    out, seen = [], set()
    for item in items:
        for m in STATUS_RE.finditer(item):
            handle, pid = m.group(1), m.group(2)
            if pid not in seen:
                seen.add(pid)
                out.append(f"https://x.com/{handle}/status/{pid}")
    return out


def fetch(url, timeout=15):
    q = urllib.parse.urlencode({"url": url, "omit_script": "true", "dnt": "true"})
    req = urllib.request.Request(f"{ENDPOINT}?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_embed(d, url):
    """oEmbed html -> text with its real line breaks, plus what the markup
    says about media, truncation and links."""
    block = d.get("html", "")
    m = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
    inner = m.group(1) if m else ""
    media = bool(re.search(r">pic\.(?:twitter|x)\.com/", inner))
    inner = re.sub(r"<a[^>]*>pic\.(?:twitter|x)\.com/[^<]*</a>", "", inner)
    links = re.findall(r'<a href="(https://t\.co/[^"]+)"', inner)
    inner = re.sub(r"<br\s*/?>", "\n", inner)
    inner = re.sub(r"<a[^>]*>([^<]*)</a>", r"\1", inner)
    text = html.unescape(re.sub(r"<[^>]+>", "", inner)).strip()
    truncated = text.endswith("…")
    date = ""
    dm = re.search(r"<a href=\"[^\"]+/status/\d+[^\"]*\">([^<]+)</a>\s*</blockquote>", block)
    if dm:
        date = html.unescape(dm.group(1))
    handle = STATUS_RE.search(d.get("url", url)).group(1)
    if truncated:
        fmt = "long"                      # a Premium long post, cut by the embed
    elif media:
        fmt = "media"                     # image or video; the embed does not say which
    elif links:
        fmt = "link"
    else:
        fmt = "text"
    lines = [l for l in text.splitlines() if l.strip()]
    hook = lines[0].strip() if lines else ""
    return {
        "url": d.get("url", url),
        "account": "@" + handle,
        "name": d.get("author_name", ""),
        "date": date,
        "format": fmt,
        "lines": len(lines),
        "words": len(re.findall(r"\S+", text)),
        "views": "", "likes": "", "replies": "", "reposts": "",
        "hook": hook,
        "text": text,
    }


def tsv_cell(v):
    return str(v).replace("\t", " ").replace("\r", "").replace("\n", " ⏎ ")


def main():
    ap = argparse.ArgumentParser(description="X post URLs -> a swipe sheet via X's oEmbed API.")
    ap.add_argument("inputs", nargs="*", help="URLs, or a file of URLs, or - for stdin")
    ap.add_argument("--max", type=int, default=100, help="hard cap per run (default 100)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests (min 1)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    items = []
    for i in args.inputs or ["-"]:
        if i == "-":
            items.append(sys.stdin.read())
        elif STATUS_RE.search(i):
            items.append(i)
        else:
            items.append(open(i, encoding="utf-8").read())
    urls = parse_urls(items)
    if not urls:
        print("no x.com/.../status/... URLs found", file=sys.stderr)
        sys.exit(2)
    if len(urls) > args.max:
        print(f"{len(urls)} URLs, capped at {args.max}. This reads posts you picked; it is not a "
              "crawler. Run it again on the rest if you mean it.", file=sys.stderr)
        urls = urls[:args.max]

    rows, failed = [], []
    for i, url in enumerate(urls):
        if i:
            time.sleep(max(1.0, args.delay))
        try:
            rows.append(parse_embed(fetch(url), url))
            print(f"  {i + 1:>3}/{len(urls)}  {rows[-1]['account']:<17} {rows[-1]['hook'][:48]}",
                  file=sys.stderr)
        except urllib.error.HTTPError as e:
            reason = {404: "deleted, private, or protected", 403: "not embeddable"}.get(e.code, f"HTTP {e.code}")
            failed.append((url, reason))
            print(f"  {i + 1:>3}/{len(urls)}  skipped: {reason}  {url}", file=sys.stderr)
        except Exception as e:                               # network, JSON
            failed.append((url, str(e)[:60]))
            print(f"  {i + 1:>3}/{len(urls)}  skipped: {str(e)[:60]}  {url}", file=sys.stderr)

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        print("\t".join(COLUMNS))
        for r in rows:
            print("\t".join(tsv_cell(r[c]) for c in COLUMNS))
    print(f"\n{len(rows)} pulled, {len(failed)} skipped. Now fill in the views column from the posts "
          "themselves, then run swipe.py.", file=sys.stderr)


if __name__ == "__main__":
    main()
