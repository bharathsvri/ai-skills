#!/usr/bin/env python3
"""
audit.py - read your own X analytics export and say what actually worked,
with the sample size attached to every claim.

The only honest source of what works for an account is that account. Every
rule in every X guide, including the ones in this pack, is a prior. Your last
30 posts are the evidence.

Input: the CSV from Account analytics -> Export (x.com/i/account_analytics,
a Premium feature), or the older analytics.twitter.com export, or a sheet you
made by hand. Columns are matched loosely, so "Impressions", "impressions"
and "Post impressions" all work. The minimum is post text plus impressions,
plus at least one of likes / replies / reposts / engagements.

What it computes per post, and why not raw impressions: impressions are
mostly a function of how many people already follow you. These are not.

  engagement rate   engagements / impressions
  replies per 1k    replies per 1,000 impressions. The conversation signal.
  shares per 1k     reposts + shares per 1,000. The travel signal.
  bookmarks per 1k  the "I will use this" signal
  follows per 1k    whether the post made anyone want more of you

Replies you wrote on other people's posts are in the same export. They are
counted and set aside, so a week of good replying does not drown the posts.

Usage
  python3 audit.py account_analytics_content.csv
  python3 audit.py export.csv --min-impressions 200 --json
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "x-post"))
try:
    from hookscore import classify, first_line          # noqa: E402
except Exception:
    classify = None

    def first_line(t):
        return (t or "").strip().splitlines()[0] if (t or "").strip() else ""

FIELDS = {
    "text":        ["post text", "tweet text", "text", "content"],
    "link":        ["post link", "tweet permalink", "permalink", "url", "link"],
    "date":        ["date", "time", "created at", "created"],
    "impressions": ["impressions", "views"],
    "engagements": ["engagements"],
    "likes":       ["likes", "favorites"],
    "replies":     ["replies"],
    "reposts":     ["reposts", "retweets"],
    "bookmarks":   ["bookmarks"],
    "shares":      ["shares"],
    "follows":     ["new follows", "follows"],
    "visits":      ["profile visits", "user profile clicks"],
}
DATE_FORMATS = ["%a, %b %d, %Y", "%Y-%m-%d %H:%M %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%b %d, %Y", "%d/%m/%Y"]
TCO = re.compile(r"https?://t\.co/\S+|https?://\S+")


def map_columns(header):
    norm = [re.sub(r"[^a-z0-9 ]", "", h.lower()).strip() for h in header]
    out = {}
    for field, names in FIELDS.items():
        for name in names:                 # exact first, then contains
            if name in norm:
                out[field] = norm.index(name)
                break
        else:
            for i, h in enumerate(norm):
                if any(h.startswith(n) or h.endswith(n) for n in names) and i not in out.values():
                    out[field] = i
                    break
    return out


def to_num(v):
    v = (v or "").strip().replace(",", "")
    try:
        return float(v)
    except ValueError:
        return None


def parse_date(v):
    v = (v or "").strip()
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(v, f)
        except ValueError:
            continue
    return None


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return [], {}
    cols = map_columns(rows[0])
    posts = []
    for raw in rows[1:]:
        get = lambda f: raw[cols[f]] if f in cols and cols[f] < len(raw) else ""
        p = {f: to_num(get(f)) for f in FIELDS if f not in ("text", "link", "date")}
        p["text"], p["link"], p["date"] = get("text"), get("link"), parse_date(get("date"))
        if p["impressions"]:
            posts.append(p)
    return posts, cols


def derive(p):
    imp = p["impressions"]
    parts = [p.get(k) or 0 for k in ("likes", "replies", "reposts", "bookmarks", "shares")]
    eng = p["engagements"] if p.get("engagements") is not None else sum(parts)
    p["er"] = eng / imp
    per1k = lambda v: (v or 0) * 1000 / imp
    p["replies_1k"] = per1k(p.get("replies"))
    p["shares_1k"] = per1k((p.get("reposts") or 0) + (p.get("shares") or 0))
    p["bookmarks_1k"] = per1k(p.get("bookmarks"))
    p["follows_1k"] = per1k(p.get("follows"))
    hook = first_line(p["text"])
    p["hook"] = hook
    p["formula"] = classify(hook)[1] if classify else "unclassified"
    body = TCO.sub("", p["text"]).strip()
    p["has_tco"] = "has a link or media" if TCO.search(p["text"]) else "text only"
    n = len(body)
    p["length"] = ("under 100" if n < 100 else "100-199" if n < 200 else "200-280" if n <= 280
                   else "long (280+)")
    p["weekday"] = p["date"].strftime("%a") if p["date"] else None
    return p


def groups(posts, key):
    out = {}
    for p in posts:
        k = p.get(key)
        if k is not None:
            out.setdefault(k, []).append(p)
    return out


def findings(posts, key, label):
    """Groups whose mean engagement rate is far from everything else's."""
    res = []
    for k, items in groups(posts, key).items():
        rest = [p for p in posts if p.get(key) != k]
        if len(items) < 3 or len(rest) < 3:
            continue
        a, b = statistics.mean(p["er"] for p in items), statistics.mean(p["er"] for p in rest)
        if b == 0:
            continue
        ratio = a / b
        if ratio >= 1.4 or ratio <= 0.7:
            res.append({"dimension": label, "group": str(k), "n": len(items), "mean_er": a,
                        "rest_er": b, "ratio": ratio})
    if len(groups(posts, key)) == 2 and len(res) == 2:
        res = [max(res, key=lambda f: f["ratio"])]       # two groups are one finding, not two
    return res


def confidence(n):
    return "solid" if n >= 10 else "moderate" if n >= 5 else "weak"


def pct(v):
    return f"{v * 100:.1f}%"


def main():
    ap = argparse.ArgumentParser(description="Audit an X analytics export.")
    ap.add_argument("input", help="CSV export")
    ap.add_argument("--min-impressions", type=int, default=None,
                    help="ignore posts under this many impressions when ranking (default: 10th percentile, min 50)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows, cols = read(args.input)
    if not rows:
        print("no rows with impressions. Is this the content export (one row per post)?", file=sys.stderr)
        sys.exit(2)
    missing = [f for f in ("text", "impressions") if f not in cols]
    if missing:
        print(f"could not find column(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

    rows = [derive(p) for p in rows]
    replies_out = [p for p in rows if p["text"].lstrip().startswith("@")]
    posts = [p for p in rows if not p["text"].lstrip().startswith("@")]
    if not posts:
        print("every row is a reply. Nothing to audit as posts.", file=sys.stderr)
        sys.exit(2)
    imps = sorted(p["impressions"] for p in posts)
    floor = args.min_impressions if args.min_impressions is not None else max(
        50, imps[len(imps) // 10] if len(imps) >= 10 else 50)
    ranked = sorted([p for p in posts if p["impressions"] >= floor], key=lambda p: -p["er"])

    dims = [("formula", "hook formula"), ("length", "length"), ("has_tco", "format")]
    found = []
    for key, label in dims:
        found += findings(ranked, key, label)
    found.sort(key=lambda f: -abs(f["ratio"] - 1) * min(f["n"], 10))
    days = findings(ranked, "weekday", "day of week")

    dates = [p["date"] for p in posts if p["date"]]
    span = f"{min(dates):%b %d} - {max(dates):%b %d}" if dates else "dates unread"

    if args.json:
        clean = lambda p: {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in p.items()}
        print(json.dumps({"posts": len(posts), "replies_set_aside": len(replies_out),
                          "floor": floor, "ranked": [clean(p) for p in ranked],
                          "findings": found, "day_of_week": days}, indent=2, default=str))
        return

    print(f"\nAUDIT  ·  {len(posts)} posts  ·  {span}  ·  {len(replies_out)} replies set aside")
    print("=" * 78)
    print(f"ranked by engagement rate, posts under {floor:,.0f} impressions left out as noise\n")

    def row(p):
        hook = p["hook"] if len(p["hook"]) <= 44 else p["hook"][:41] + "..."
        return (f"  {pct(p['er']):>6}  {p['replies_1k']:5.1f} rep/1k  {p['shares_1k']:5.1f} shr/1k  "
                f"{p['impressions']:>8,.0f} imp  \"{hook}\"")

    k = min(5, max(1, len(ranked) // 3))
    print("TOP BY ENGAGEMENT RATE")
    for p in ranked[:k]:
        print(row(p))
    print("\nBOTTOM")
    for p in ranked[-k:]:
        print(row(p))

    most_seen = max(posts, key=lambda p: p["impressions"])
    if ranked and most_seen is not ranked[0]:
        rank = next((i for i, p in enumerate(ranked, 1) if p is most_seen), None)
        where = f"#{rank} of {len(ranked)}" if rank else "below the noise floor"
        print(f"\n  Your most-seen post ranks {where} by engagement rate. Reach and resonance are not "
              "the same number.")

    print("\nWHAT THE DATA SAYS")
    if len(ranked) < 12:
        print(f"  {len(ranked)} posts is too few to find a pattern. Post 20 more and run this again. "
              "Anything printed below is a hint, not a finding.")
    if not found:
        print("  Nothing separates cleanly. No hook formula, length or link/media group is 1.4x above or "
              "below the rest with 3+ posts. That is a real answer: your topic and your first line matter "
              "more than any format lever here.")
    for i, f in enumerate(found[:4], 1):
        direction = "above" if f["ratio"] > 1 else "below"
        print(f"  {i}. {f['dimension']} = {f['group']}: {pct(f['mean_er'])} vs {pct(f['rest_er'])} for "
              f"everything else ({f['ratio']:.1f}x, {direction}). n={f['n']}, {confidence(f['n'])}.")
    if days and not found:
        f = max(days, key=lambda d: abs(d["ratio"] - 1))
        print(f"  Day of week: {f['group']} at {f['ratio']:.1f}x, n={f['n']}. Checked last on purpose. "
              "It is almost never the cause, and it is where people want it to be.")
    elif not days:
        print("  Day of week shows nothing. Stop optimising it.")
    if replies_out:
        rimp = sum(p["impressions"] for p in replies_out)
        pimp = sum(p["impressions"] for p in posts)
        print(f"\n  Replies: {len(replies_out)} of them earned {rimp:,.0f} impressions, "
              f"{rimp / max(pimp, 1) * 100:.0f}% of what your posts earned.")
    print("")


if __name__ == "__main__":
    main()
