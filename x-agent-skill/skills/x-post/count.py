#!/usr/bin/env python3
"""
count.py - count a post the way X counts it, and lint the six things worth
linting before you post.

X does not count characters. It counts WEIGHTED characters, using the rules
in its open-source twitter-text library (config v3):

  - every link is 23, however long it is, because X wraps it in t.co
  - every emoji is 2, including the ones built from several code points
    (a family, a flag, a skin tone), which would otherwise count 4 to 11
  - Latin, Greek, Cyrillic, Arabic, Hebrew, Devanagari and most general
    punctuation are 1. That includes em dashes and curly quotes.
  - everything else is 2: Chinese, Japanese, Korean, most symbols, and the
    ellipsis character "…", which costs more than the three dots it replaces
  - the text is NFC-normalised first

A standard account gets 280 weighted characters. X Premium gets 25,000, but
the timeline shows about the first 280 and hides the rest behind "Show more",
so a long post still lives or dies on its first 280.

Link detection is an approximation: links with http(s):// always count, bare
domains count when they end in a common TLD. twitter-text knows every TLD in
existence; this script knows about sixty. If you write "tool.museum" without
the https://, check it in the composer.

Usage
  python3 count.py post.txt
  python3 count.py post.txt --premium
  pbpaste | python3 count.py -
  python3 count.py post.txt --json
"""

import argparse
import json
import re
import sys
import textwrap
import unicodedata

LIMIT = 280
PREMIUM_LIMIT = 25000
FOLD = 280               # roughly where the timeline cuts a long post to "Show more"
URL_WEIGHT = 23
HASHTAG_LIMIT = 1

# twitter-text v3: code points in these ranges weigh 1, everything else 2.
LIGHT_RANGES = [(0, 4351), (8192, 8205), (8208, 8223), (8242, 8247)]

_TLDS = ("com|net|org|io|ai|co|dev|app|me|xyz|gg|so|tv|us|uk|ca|de|fr|es|it|nl|se|no|au|nz|in|"
         "jp|ly|sh|to|fm|info|biz|edu|gov|news|blog|site|tech|studio|design|link|page|pro|"
         "store|shop|club|live|world|today|online|space|cloud|run|build|ink|is|am|be|cc|ws")
URL_RE = re.compile(
    r"https?://[^\s<>\"]+"
    r"|(?<![@\w.-])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" + _TLDS + r")\b(?::\d+)?(?:/[^\s<>\"]*)?",
    re.IGNORECASE)
TRAILING = ".,!?:;)]}'\""

_PICTO = "\U0001F000-\U0001FAFF☀-➿⌀-⏿⬀-⯿←-⇿〰〽㊗㊙©®™ℹ"
_MOD = "\U0001F3FB-\U0001F3FF"
EMOJI_RE = re.compile(
    "[\U0001F1E6-\U0001F1FF]{2}"                                     # flags
    "|[0-9#*]️?⃣"                                          # keycaps
    "|\U0001F3F4[\U000E0020-\U000E007E]+\U000E007F"                  # England etc.
    f"|[{_PICTO}]️?[{_MOD}]?(?:‍[{_PICTO}]️?[{_MOD}]?)*")

HASHTAG_RE = re.compile(r"(?:^|(?<=\s))#[A-Za-z0-9_]+")
MENTION_RE = re.compile(r"(?:^|(?<=[\s(]))@[A-Za-z0-9_]{1,15}\b")
BAIT_RE = re.compile(r"(?i)\b(?:thoughts|agree|am i wrong|who else)\?\s*$|\b(?:rt|repost|retweet|like) if\b"
                     r"|\bfollow (?:me )?for more\b")
LABEL_RE = re.compile(r"(?i)^\s*(?:a\s+)?(?:(?:mega|short|quick|long|new)\s+)?(?:thread|🧵)\b|^\s*🧵")


def _light(cp):
    return any(a <= cp <= b for a, b in LIGHT_RANGES)


def find_urls(text):
    out = []
    for m in URL_RE.finditer(text):
        url = m.group(0).rstrip(TRAILING)
        out.append((m.start(), m.start() + len(url), url))
    return out


def weighted(text):
    """Return (weighted_length, detail, cut) where cut is the character index
    at which the post first exceeds LIMIT (None if it fits)."""
    text = unicodedata.normalize("NFC", text)
    urls = find_urls(text)
    total, i, cut = 0, 0, None
    emoji_n, heavy = 0, []
    url_at = {a: (b, u) for a, b, u in urls}
    while i < len(text):
        if i in url_at:
            end, _ = url_at[i]
            total += URL_WEIGHT
            i = end
        else:
            m = EMOJI_RE.match(text, i)
            if m and m.end() > i:
                total += 2
                emoji_n += 1
                i = m.end()
            else:
                cp = ord(text[i])
                w = 1 if _light(cp) else 2
                if w == 2:
                    heavy.append(text[i])
                total += w
                i += 1
        if cut is None and total > LIMIT:
            cut = i - 1
    return total, {"urls": [u for _, _, u in urls], "emoji": emoji_n, "heavy": heavy}, cut


def visible_prefix(text, budget):
    """The longest prefix of text that fits in `budget` weighted characters."""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if weighted(text[:mid])[0] <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def analyse(text, premium=False):
    text = unicodedata.normalize("NFC", text.strip())
    limit = PREMIUM_LIMIT if premium else LIMIT
    total, detail, _ = weighted(text)
    checks = []

    def add(status, name, msg):
        checks.append({"status": status, "check": name, "detail": msg})

    over = total - limit
    if over > 0:
        add("FAIL", "LENGTH", f"{total} / {limit}, {over} over. X will not let you post it.")
    elif total > LIMIT:
        add("WARN", "LENGTH", f"{total} / {limit} (Premium long post). The timeline shows about the "
            f"first {FOLD}, then \"Show more\". Everything that matters goes above the fold.")
    else:
        add("PASS", "LENGTH", f"{total} / {limit}, {limit - total} left")

    hook = first_line(text)
    hw = weighted(hook)[0]
    if LABEL_RE.search(hook):
        add("WARN", "FIRST LINE", "opens on \"thread\". That is packaging, not a hook. Lead with the payoff.")
    elif hw > 110:
        add("WARN", "FIRST LINE", f"{hw} characters. It wraps to a third line on a phone before the point lands.")
    else:
        add("PASS", "FIRST LINE", f"{hw} characters, reads in one glance")

    urls = detail["urls"]
    if urls:
        in_hook = any(u in hook for u in urls)
        add("WARN" if in_hook else "NOTE", "LINKS",
            f"{len(urls)} link(s), {URL_WEIGHT} characters each. "
            + ("One is in the first line, which hands the reader a way out before the post lands. "
               if in_hook else "")
            + "X says it no longer down-ranks link posts (July 2026). An independent analysis in "
              "January 2026 still measured fewer views on them. Your own /x-audit will tell you which "
              "is true for you.")
    else:
        add("PASS", "LINKS", "none")

    tags = HASHTAG_RE.findall(text)
    if len(tags) > HASHTAG_LIMIT:
        add("WARN", "HASHTAGS", f"{len(tags)}: {' '.join(tags[:5])}. Each is a link out of your own post. "
            "Elon Musk, Dec 2024: the system doesn't need them anymore. Keep one, or none.")
    else:
        add("PASS", "HASHTAGS", f"{len(tags)}" + (f": {tags[0]}" if tags else ""))

    mentions = MENTION_RE.findall(text)
    late = []
    if total > LIMIT and mentions:
        head = visible_prefix(text, LIMIT)
        late = [m for m in mentions if m not in head]
    if late:
        add("WARN", "MENTIONS", f"{' '.join(late)} sits past character {LIMIT}. X does not notify a "
            "mention that far into a long post. Move it up if you want them to see it.")
    else:
        add("PASS", "MENTIONS", f"{len(mentions)}")

    if BAIT_RE.search(text):
        add("WARN", "ENDING", "ends on reflex bait (\"Thoughts?\", \"RT if\"). Ask a question only this "
            "post could ask, or end on the last true sentence.")
    else:
        add("PASS", "ENDING", "no reflex bait")

    em = text.count("—")
    if em:
        add("WARN", "EM DASH", f"{em}. Run it through /x-human before it goes anywhere.")

    return {
        "weighted": total,
        "limit": limit,
        "fits": total <= limit,
        "urls": urls,
        "emoji": detail["emoji"],
        "double_weight_chars": len(detail["heavy"]),
        "fold": visible_prefix(text, FOLD) if total > FOLD else None,
        "checks": checks,
    }


def render(text, a, out=sys.stdout, width=52):
    text = text.strip()
    print("\n  WHAT FITS" if a["weighted"] > a["limit"] else "\n  WHAT THE TIMELINE SHOWS", file=out)
    print("  +" + "-" * (width + 2) + "+", file=out)
    shown = a["fold"] if a["fold"] is not None else text
    lines = []
    for raw in shown.split("\n"):
        lines.extend(textwrap.wrap(raw, width) or [""])
    for line in lines[:14]:
        print(f"  | {line:<{width}} |", file=out)
    if len(lines) > 14:
        print(f"  | {'...':<{width}} |", file=out)
    if a["weighted"] > a["limit"] or (a["limit"] == LIMIT and a["fold"] is not None):
        tail = f"cut here, {a['weighted'] - a['limit']} over"
    elif a["fold"] is not None:
        tail = "Show more"
    else:
        tail = f"{a['weighted']}/{a['limit']}"
    print("  +" + "-" * (width + 2 - len(tail) - 2) + f" {tail} " + "+", file=out)
    extras = []
    if a["urls"]:
        extras.append(f"{len(a['urls'])} link(s) at {URL_WEIGHT}")
    if a["emoji"]:
        extras.append(f"{a['emoji']} emoji at 2")
    if a["double_weight_chars"]:
        extras.append(f"{a['double_weight_chars']} other double-weight character(s)")
    if extras:
        print("  counted as: " + ", ".join(extras), file=out)
    print("", file=out)
    for c in a["checks"]:
        print(f"  {c['status']:<5} {c['check']:<11} {c['detail']}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Count and lint an X post the way X counts it.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("--premium", action="store_true", help="use the 25,000 Premium limit")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    if not raw.strip():
        print("nothing to count", file=sys.stderr)
        sys.exit(2)
    a = analyse(raw, premium=args.premium)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(raw, a)
    sys.exit(0 if a["fits"] else 1)


if __name__ == "__main__":
    main()
