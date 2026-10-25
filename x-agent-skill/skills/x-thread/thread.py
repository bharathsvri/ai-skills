#!/usr/bin/env python3
"""
thread.py - cut a long draft into an X thread that fits, post by post, and
lint the five places threads usually fail.

It never cuts where it does not have to. Posts break at your own separators
first (a line that is just ---), then at paragraphs, then at sentences. Only a
single sentence longer than a whole post gets split between words, and when
that happens it is flagged, because a post that starts mid-sentence reads
like a mistake.

Every post is measured the way X measures it (links 23, emoji 2, see
../x-post/count.py), so "fits" here means fits in the composer.

Usage
  python3 thread.py draft.txt
  python3 thread.py draft.txt --number          # add 1/7, 2/7 ... (counted)
  python3 thread.py draft.txt --pack            # merge short paragraphs
  python3 thread.py draft.txt --json
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "x-post"))
try:
    from count import weighted, find_urls, LABEL_RE     # noqa: E402
except Exception:                                        # x-thread copied on its own
    LABEL_RE = re.compile(r"(?i)^\s*(?:a\s+)?thread\b|^\s*🧵")

    def weighted(text):
        return len(text), {}, None

    def find_urls(text):
        return [(m.start(), m.end(), m.group(0))
                for m in re.finditer(r"https?://\S+", text)]

LIMIT = 280
SENT_RE = re.compile(r"[^.!?\n]+(?:[.!?]+[\"')\]]*|$)\s*")
SEP_RE = re.compile(r"(?m)^\s*-{3,}\s*$")
ASK_RE = re.compile(r"(?i)\?|\b(?:follow|bookmark|repost|reply|comment|dm me|subscribe|join|grab|get the|"
                    r"link (?:is )?(?:below|in the reply)|try it|steal)\b")


def w(text):
    return weighted(text)[0]


def split_sentences(par):
    parts = [s.strip() for s in SENT_RE.findall(par) if s.strip()]
    return parts or [par.strip()]


def split_words(sentence, limit):
    out, cur = [], ""
    for word in sentence.split():
        trial = (cur + " " + word).strip()
        if w(trial) <= limit:
            cur = trial
        else:
            if cur:
                out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def fit(par, limit):
    """One paragraph into as few posts as fit, breaking at sentences.
    Returns [(text, split_mid_sentence)]."""
    if w(par) <= limit:
        return [(par, False)]
    posts, cur = [], ""
    for sent in split_sentences(par):
        trial = (cur + " " + sent).strip()
        if w(trial) <= limit:
            cur = trial
            continue
        if cur:
            posts.append((cur, False))
            cur = ""
        if w(sent) <= limit:
            cur = sent
        else:
            pieces = split_words(sent, limit)
            posts += [(p, True) for p in pieces[:-1]]
            cur = pieces[-1]
    if cur:
        posts.append((cur, False))
    return posts


def build(text, limit=LIMIT, number=False, pack=False):
    text = text.strip()
    reserve = 7 if number else 0              # "\n\n12/15" is 7 weighted characters
    budget = limit - reserve
    if SEP_RE.search(text):
        blocks = [b.strip() for b in SEP_RE.split(text) if b.strip()]
        explicit = True
    else:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
        explicit = False
    posts = []
    for b in blocks:
        if explicit and w(b) <= budget:
            posts.append((b, False))
        else:
            posts += fit(b, budget)
    if pack and not explicit:
        merged = []
        for p, cut in posts:
            if merged and not cut and not merged[-1][1] and w(merged[-1][0] + "\n\n" + p) <= budget:
                merged[-1] = (merged[-1][0] + "\n\n" + p, False)
            else:
                merged.append((p, cut))
        posts = merged
    n = len(posts)
    out = []
    for i, (p, cut) in enumerate(posts, 1):
        body = f"{p}\n\n{i}/{n}" if number else p
        out.append({"n": i, "text": body, "weighted": w(body), "split_mid_sentence": cut})
    return out, explicit


def lint(posts, limit=LIMIT):
    checks = []

    def add(status, name, msg):
        checks.append({"status": status, "check": name, "detail": msg})

    n = len(posts)
    if n < 3:
        add("WARN", "LENGTH", f"{n} post(s). That is a post, not a thread. Use /x-post, or a single "
            "long post if you have Premium.")
    elif n > 15:
        add("WARN", "LENGTH", f"{n} posts. Past about 15, fewer people reach the end than read post 2. "
            "Cut, or split it into two threads a week apart.")
    else:
        add("PASS", "LENGTH", f"{n} posts")

    over = [p["n"] for p in posts if p["weighted"] > limit]
    if over:
        add("FAIL", "FITS", f"post(s) {over} are over {limit}. X will not post them.")
    else:
        add("PASS", "FITS", f"every post is {limit} or under")

    hook = posts[0]["text"].strip().splitlines()[0] if posts else ""
    if LABEL_RE.search(hook):
        add("WARN", "POST 1", "opens on \"thread\". Post 1 is the only one most people read. Put the "
            "payoff in it and let X's own UI say it is a thread.")
    elif w(hook) > 110:
        add("WARN", "POST 1", f"first line is {w(hook)} characters. It has to land in one glance.")
    else:
        add("PASS", "POST 1", f"first line {w(hook)} characters. Score it: "
            "python3 ../x-post/hookscore.py --hook \"...\"")

    cuts = [p["n"] for p in posts if p["split_mid_sentence"]]
    if cuts:
        add("WARN", "BREAKS", f"post(s) {cuts} end mid-sentence because one sentence is longer than a "
            "post. Rewrite that sentence in two.")
    else:
        add("PASS", "BREAKS", "every post ends on a sentence")

    mid_links = [p["n"] for p in posts[:-1] if find_urls(p["text"])]
    if mid_links:
        add("NOTE", "LINKS", f"link(s) in post(s) {mid_links}. A link before the last post is an exit "
            "before the payoff. Move it to the end unless the link IS the point.")
    else:
        add("PASS", "LINKS", "none before the last post")

    if posts and not ASK_RE.search(posts[-1]["text"]):
        add("NOTE", "LAST POST", "no ask. The last post is the one people screenshot and the one they "
            "act on: a recap, then one next step. One.")
    else:
        add("PASS", "LAST POST", "has an ask")

    heavy = [p for p in posts if p["weighted"] > limit * 0.85]
    if n >= 4 and len(heavy) > n * 0.6:
        add("NOTE", "PACE", f"{len(heavy)} of {n} posts are within 15% of the limit. Threads that get "
            "read to the end have short posts in them. One idea per post, then stop.")
    return checks


def render(posts, checks, out=sys.stdout):
    total = sum(p["weighted"] for p in posts)
    print(f"\nTHREAD  ·  {len(posts)} posts  ·  {total:,} weighted characters", file=out)
    print("=" * 62, file=out)
    for p in posts:
        mark = "  ! split mid-sentence" if p["split_mid_sentence"] else ""
        print(f"\n[{p['n']}/{len(posts)}]  {p['weighted']}/{LIMIT}{mark}", file=out)
        print(p["text"], file=out)
    print("\n" + "-" * 62, file=out)
    for c in checks:
        print(f"  {c['status']:<5} {c['check']:<10} {c['detail']}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Cut a draft into an X thread that fits.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("--number", action="store_true", help="append i/n to each post")
    ap.add_argument("--pack", action="store_true", help="merge short paragraphs into one post")
    ap.add_argument("--limit", type=int, default=LIMIT)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    if not raw.strip():
        print("nothing to thread", file=sys.stderr)
        sys.exit(2)
    posts, _ = build(raw, args.limit, args.number, args.pack)
    checks = lint(posts, args.limit)
    if args.json:
        print(json.dumps({"posts": posts, "checks": checks}, indent=2, ensure_ascii=False))
    else:
        render(posts, checks)
    sys.exit(1 if any(c["status"] == "FAIL" for c in checks) else 0)


if __name__ == "__main__":
    main()
