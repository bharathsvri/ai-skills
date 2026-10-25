#!/usr/bin/env python3
"""
weights.py - print the engagement weights X's For You ranker is using right
now, read from X's own published source, with the date they were last
changed.

In January 2026 X open-sourced its current recommendation system at
github.com/xai-org/x-algorithm, and since August 2026 that repo carries the
production action weights in home-mixer/params/param.rs, kept in sync with
production by a scheduled job. They change. Two of them moved in the week
this script was written. So this reads the file live instead of pasting a
table into a README that will be wrong by next month. No X account, no key:
it reads a public GitHub file.

HOW TO READ THEM, in X's own words from the comments in that file: each
weight multiplies the PREDICTED PROBABILITY that a given viewer takes that
action, not a count of actions taken. So "a reply is worth 10 likes" is the
wrong reading, and the file says so. The useful reading is direction: which
actions the ranker is built to reward, and which ones it punishes hard.

Usage
  python3 weights.py
  python3 weights.py --json
  python3 weights.py --offline        # the snapshot below, clearly labelled
"""

import argparse
import json
import re
import sys
import urllib.request

REPO = "xai-org/x-algorithm"
PATH = "home-mixer/params/param.rs"
RAW = f"https://raw.githubusercontent.com/{REPO}/main/{PATH}"
COMMITS = f"https://api.github.com/repos/{REPO}/commits?path={PATH}&per_page=1"
UA = "x-agent-skill/1.0"

# What the weights mean in plain words. Anything not listed prints its code name.
LABELS = {
    "Favorite": "like",
    "Reply": "reply",
    "BidirectionalFollowReplyWeightBoost": "+ added to a reply between mutuals",
    "Retweet": "repost",
    "Quote": "quote",
    "Share": "share (any)",
    "ShareViaDm": "share by DM",
    "ShareViaCopyLink": "share by copying the link",
    "FollowAuthor": "follow the author",
    "Click": "click into the post",
    "OpenLink": "open a link",
    "ProfileClick": "click the profile",
    "PhotoExpand": "expand a photo",
    "VideoOpen": "open a video",
    "Dwell": "stop and read (dwell)",
    "ContClickDwellTime": "time spent after clicking in",
    "NotInterested": "\"not interested\"",
    "BlockAuthor": "block the author",
    "MuteAuthor": "mute the author",
    "Report": "report",
    "NotDwelled": "scroll straight past",
}

# Snapshot for --offline or when GitHub cannot be reached.
SNAPSHOT_DATE = "2026-09-29 (commit a707cc2)"
SNAPSHOT = {
    "Favorite": 0.5, "Reply": 5.0, "BidirectionalFollowReplyWeightBoost": 15.0, "Retweet": 1.0,
    "PhotoExpand": 0.05, "VideoOpen": 0.07, "Click": 0.3, "OpenLink": 0.2, "ProfileClick": 0.0,
    "Share": 2.0, "ShareViaDm": 5.0, "ShareViaCopyLink": 20.0, "Dwell": 0.05, "Quote": 5.0,
    "FollowAuthor": 4.0, "ContClickDwellTime": 0.4, "NotInterested": -47.52, "BlockAuthor": -31.2,
    "MuteAuthor": -58.8, "Report": -234.0, "NotDwelled": -0.02,
}

PARAM_RE = re.compile(r"param!\(\s*(\w+)\s*,\s*f64\s*,\s*\"[^\"]+\"\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", re.S)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode("utf-8")


def fetch():
    src = get(RAW)
    weights = {}
    for name, val in PARAM_RE.findall(src):
        if name.endswith("Weight") or name.endswith("WeightBoost"):
            key = name[:-6] if name.endswith("Weight") else name
            weights[key] = float(val)
    date = "unknown date"
    try:
        c = json.loads(get(COMMITS))[0]
        date = f"{c['commit']['committer']['date'][:10]} (commit {c['sha'][:7]})"
    except Exception:
        pass
    return weights, date


def render(weights, date, source, out=sys.stdout):
    like = weights.get("Favorite") or 0.5
    shown = {k: v for k, v in weights.items() if k in LABELS and v != 0}
    pos = sorted(((k, v) for k, v in shown.items() if v > 0), key=lambda kv: -kv[1])
    neg = sorted(((k, v) for k, v in shown.items() if v < 0), key=lambda kv: kv[1])
    print(f"\nX FOR YOU RANKER  ·  action weights  ·  {source}, last changed {date}")
    print("=" * 78)
    print("REWARDED" + " " * 34 + "weight   vs a like")
    for k, v in pos:
        print(f"  {LABELS[k]:<40} {v:>7g}   {v / like:>6.1f}x")
    print("\nPUNISHED")
    for k, v in neg:
        print(f"  {LABELS[k]:<40} {v:>7g}")
    print("-" * 78)
    print("  These multiply the PREDICTED probability of each action for each viewer, not")
    print("  counts. X's own comment in the file: reading the ratios as count equivalences")
    print("  is \"incorrect\". Read the direction: write things people reply to, quote and")
    print("  send to one person. Avoid what gets you muted or marked not interested.")
    print("  Source: github.com/" + REPO + "/blob/main/" + PATH + "\n")


def main():
    ap = argparse.ArgumentParser(description="X's current published ranking weights.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    if args.offline:
        weights, date, source = SNAPSHOT, SNAPSHOT_DATE, "offline snapshot"
    else:
        try:
            weights, date = fetch()
            source = "live from GitHub"
            if not weights:
                raise ValueError("no weights parsed; the file format may have changed")
        except Exception as e:
            print(f"could not read the live file ({e}). Showing the snapshot instead.", file=sys.stderr)
            weights, date, source = SNAPSHOT, SNAPSHOT_DATE, "offline snapshot"
    if args.json:
        print(json.dumps({"source": source, "date": date, "weights": weights}, indent=2))
    else:
        render(weights, date, source)


if __name__ == "__main__":
    main()
