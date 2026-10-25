#!/usr/bin/env python3
"""
swipe.py - rank the posts you collected by how far each one beat its own
account, then break every one down into hook, structure and format, and
write the swipe file the rest of the pack drafts from.

The one correction this script exists to make: raw numbers are not evidence.
An account with 900,000 followers doing 400,000 views had an ordinary
Tuesday. An account with 6,000 followers doing 400,000 views found something,
and that something is copyable. So everything here ranks on the OUTLIER
MULTIPLE: a post's views over its own account's median.

The median comes from the rows themselves, so collect each account's last
10-15 posts IN ORDER, the dull ones included. Hand-picking only the hits
inflates the median and hides the very outliers you came for. Accounts with
fewer than --min-posts rows are skipped, not ranked on noise. If you already
know an account's typical views, put it in a `median` column and that wins.

Views are the metric when a row has them (they are public on every post).
A row with no views falls back to likes, and the output says so.

Input is the TSV pull.py writes, with the numbers filled in by you:

    url  account  name  date  format  lines  words  views  likes  replies  reposts  hook  text

Usage
  python3 swipe.py swipe.tsv
  python3 swipe.py swipe.tsv --out ~/.claude/x/swipe.md
  python3 swipe.py swipe.tsv --min-posts 4 --json
"""

import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "x-post"))
try:
    import hookscore                                    # noqa: E402
    HOOKS = {h["id"]: h for h in json.load(open(os.path.join(HERE, "..", "x-post", "hooks.json"),
                                                  encoding="utf-8"))["hooks"]}
except Exception:                                       # x-viral copied on its own
    hookscore, HOOKS = None, {}

LIST_LINE = re.compile(r"^\s*(?:\d{1,2}[.)]|[-•*→>]|[\U0001F300-\U0001FAFF✅➡✔])\s*\S")


def num(v):
    v = (v or "").strip().lower().replace(",", "")
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([km]?)$", v)
    if not m:
        return None
    n = float(m.group(1)) * {"": 1, "k": 1e3, "m": 1e6}[m.group(2)]
    return int(n)


def read_rows(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    cols = [c.strip().lower() for c in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        cells = line.split("\t") + [""] * len(cols)
        r = dict(zip(cols, (c.strip() for c in cells)))
        r["text"] = (r.get("text") or r.get("hook") or "").replace(" ⏎ ", "\n").replace("⏎", "\n")
        for k in ("views", "likes", "replies", "reposts", "median", "followers"):
            r[k] = num(r.get(k))
        r["metric_name"] = "views" if r["views"] else ("likes" if r["likes"] else None)
        r["metric"] = r["views"] or r["likes"]
        if r["metric"] and (r.get("hook") or r["text"]):
            rows.append(r)
    return rows


def hook_of(r):
    hook = (r.get("hook") or "").strip()
    if not hook:
        hook = next((l.strip() for l in r["text"].splitlines() if l.strip()), "")
    if len(hook) > 140:                        # one long paragraph: the hook is its first sentence
        m = re.match(r"(.+?[.!?])(?:\s|$)", hook)
        if m:
            hook = m.group(1)
    return hook


def structure_of(r):
    lines = [l for l in r["text"].splitlines() if l.strip()]
    listy = sum(1 for l in lines if LIST_LINE.match(l))
    fmt = (r.get("format") or "").lower()
    if fmt == "thread":
        return "thread"
    if fmt == "long" or len(r["text"]) > 280:
        return "long post"
    if listy >= 3:
        return f"list ({listy} items)"
    if len(lines) <= 1:
        return "one line" if len(r["text"].split()) <= 20 else "one paragraph"
    return f"{len(lines)} short lines"


def analyse(rows, min_posts):
    by_acct = {}
    for r in rows:
        by_acct.setdefault(r.get("account", "?"), []).append(r)
    ranked, skipped = [], []
    for acct, items in by_acct.items():
        explicit = [r["median"] for r in items if r.get("median")]
        if explicit:
            base = explicit[0]
        elif len(items) >= min_posts:
            # median within the metric each row actually has
            base = None
        else:
            skipped.append((acct, len(items)))
            continue
        for r in items:
            b = base
            if b is None:
                same = [x["metric"] for x in items if x["metric_name"] == r["metric_name"]]
                if len(same) < min_posts:
                    skipped.append((acct + f" ({r['metric_name']})", len(same)))
                    continue
                b = statistics.median(same)
            r["baseline"] = b
            r["outlier"] = round(r["metric"] / b, 2) if b else None
            r["hook_line"] = hook_of(r)
            if hookscore:
                p = hookscore.score_payload(r["hook_line"])
                r["formula_id"], r["formula"] = p["formula_id"], p["formula"]
                r["hook_score"] = p["score"]
            else:
                r["formula_id"], r["formula"], r["hook_score"] = None, "unclassified", None
            r["structure"] = structure_of(r)
            r["format"] = r.get("format") or "text"
            r["reply_ratio"] = (round(r["replies"] / r["likes"], 3)
                                if r.get("replies") is not None and r.get("likes") else None)
            ranked.append(r)
    ranked.sort(key=lambda r: -(r["outlier"] or 0))
    third = max(1, len(ranked) // 3)
    top, bottom = ranked[:third], ranked[-third:]

    def tally(items, key):
        out = {}
        for r in items:
            out[r[key]] = out.get(r[key], 0) + 1
        return sorted(out.items(), key=lambda kv: -kv[1])

    def med(items, f, digits=1):
        vals = [f(r) for r in items if f(r) is not None]
        return round(statistics.median(vals), digits) if vals else None

    words = lambda r: len(r["hook_line"].split())
    return {
        "n": len(ranked),
        "accounts": len({r.get("account") for r in ranked}),
        "metrics": sorted({r["metric_name"] for r in ranked}),
        "posts": ranked,
        "skipped": skipped,
        "top": {"formulas": tally(top, "formula"), "formats": tally(top, "format"),
                "structures": tally(top, "structure"), "hook_words": med(top, words),
                "reply_ratio": med(top, lambda r: r["reply_ratio"], 3)},
        "bottom": {"formulas": tally(bottom, "formula"), "formats": tally(bottom, "format"),
                   "structures": tally(bottom, "structure"), "hook_words": med(bottom, words),
                   "reply_ratio": med(bottom, lambda r: r["reply_ratio"], 3)},
        "unclassified": [r["hook_line"] for r in ranked if r["formula"] == "unclassified"],
    }


def fmt_tally(t, k=3):
    return ", ".join(f"{name} x{c}" for name, c in t[:k]) or "-"


def render(a, out=sys.stdout):
    head = (f"SWIPE FILE  ·  {a['n']} posts  ·  {a['accounts']} accounts  ·  "
            f"multiple over each account's own median {'/'.join(a['metrics'])}")
    print("\n" + head, file=out)
    print("=" * max(len(head), 78), file=out)
    for r in a["posts"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "  ?"
        fid = f"#{r['formula_id']:<2}" if r["formula_id"] else "-  "
        print(f"  {mult:>6}  {fid} {r['formula'][:20]:<20} {r['structure'][:15]:<15} "
              f"{r['format']:<6} {r.get('account', '')[:16]:<16} {r['metric']:>9,} {r['metric_name']}",
              file=out)
        hook = r["hook_line"] if len(r["hook_line"]) <= 92 else r["hook_line"][:89] + "..."
        print(f"          \"{hook}\"", file=out)
    print("-" * max(len(head), 78), file=out)
    t, b = a["top"], a["bottom"]
    print("TOP THIRD vs BOTTOM THIRD", file=out)
    print(f"  hook       top: {fmt_tally(t['formulas'])}", file=out)
    print(f"             bottom: {fmt_tally(b['formulas'])}", file=out)
    print(f"  structure  top: {fmt_tally(t['structures'])}   bottom: {fmt_tally(b['structures'])}", file=out)
    print(f"  format     top: {fmt_tally(t['formats'])}   bottom: {fmt_tally(b['formats'])}", file=out)
    print(f"  hook words top: {t['hook_words']}   bottom: {b['hook_words']}", file=out)
    if t["reply_ratio"] is not None and b["reply_ratio"] is not None:
        print(f"  replies per like   top: {t['reply_ratio']}   bottom: {b['reply_ratio']}", file=out)
    if a["unclassified"]:
        print(f"\n  UNCLASSIFIED ({len(a['unclassified'])}). Read these by hand. Either noise, or a "
              "formula hooks.json does not have yet:", file=out)
        for h in a["unclassified"][:8]:
            print(f"    \"{h[:90]}\"", file=out)
    if a["skipped"]:
        print("\n  SKIPPED (too few posts to know the account's normal): "
              + ", ".join(f"{acct} ({n})" for acct, n in a["skipped"]), file=out)
    print(f"\n  {a['n']} posts is {'a sample worth reading' if a['n'] >= 40 else 'a first look, not a finding'}."
          " Forty across six accounts shows you something; twelve shows you nothing.\n", file=out)


def to_markdown(a):
    lines = ["# Swipe file", "",
             f"{a['n']} posts across {a['accounts']} accounts, ranked by multiple over each "
             "account's own median. Copy the shape, never the words.", ""]
    for r in a["posts"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "?"
        h = HOOKS.get(r["formula_id"], {})
        lines += [f"## {mult}  {r['formula']}  ·  {r.get('account', '')}",
                  f"- {r['metric_name']}: {r['metric']:,}  (account median {r['baseline']:,.0f})",
                  f"- hook: \"{r['hook_line']}\"",
                  f"- structure: {r['structure']}  ·  format: {r['format']}",
                  f"- source: {r.get('url', '')}"]
        if h:
            lines.append(f"- shape to reuse: {h['template']}")
        lines += ["- your version: ", ""]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Rank collected X posts by outlier multiple.")
    ap.add_argument("input", nargs="?", default="-", help="TSV from pull.py, or - for stdin")
    ap.add_argument("--min-posts", type=int, default=5,
                    help="posts needed per account to trust its median (default 5)")
    ap.add_argument("--out", help="also write the swipe file as markdown here")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.input)
    if not rows:
        print("no usable rows. Fill in the views (or likes) column first.", file=sys.stderr)
        sys.exit(2)
    a = analyse(rows, args.min_posts)
    if not a["posts"]:
        print(f"every account had fewer than {args.min_posts} posts. Collect each account's last "
              "10-15 posts, in order, and run it again.", file=sys.stderr)
        sys.exit(2)
    if hookscore is None:
        print("note: ../x-post/hookscore.py not found, formulas not named.", file=sys.stderr)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False, default=str))
    else:
        render(a)
    if args.out:
        path = os.path.expanduser(args.out)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        open(path, "w", encoding="utf-8").write(to_markdown(a))
        print(f"wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
