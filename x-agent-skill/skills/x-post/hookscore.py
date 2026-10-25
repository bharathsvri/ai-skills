#!/usr/bin/env python3
"""
hookscore.py - score the first line of an X post on the five things strong
hooks have in common, name the formula it uses, and rank a batch of them.

What this is:  five local heuristics, computed on your machine from the text
alone. They measure properties that first lines which hold a scrolling thumb
tend to share: short enough to read in one glance, a concrete marker,
something at stake, the payload at the front rather than the back, and a
reader to aim it at. Plus the formula name from hooks.json, so a hook you
wrote and a hook you found are described in the same vocabulary.

What this is NOT:  a reach predictor. The same five-property panel, tested on
74 real short-form video hooks in the Instagram version of this pack,
separated real hooks from deliberately bad ones well (AUC 0.83) and a
creator's own hits from their own misses barely at all (AUC 0.56, where 0.50
is a coin flip). It has not been re-calibrated on X posts. So use it for what
it measured well: it catches labels, preambles, hooks with nothing concrete
in them and first lines that bury the point. It will not tell you which of
two decent hooks will travel. Your own analytics will (see /x-audit).

Each check returns 0 to 100. Higher is better.

Usage
  python3 hookscore.py hooks.txt              # one hook per line, ranked
  python3 hookscore.py --hook "I lost $18,000 on one missing clause."
  pbpaste | python3 hookscore.py -
  python3 hookscore.py hooks.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(HERE, "hooks.json")

WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")
NUMBER_RE = re.compile(
    r"\$\s?\d[\d,]*(?:\.\d+)?k?"                     # money
    r"|\b\d[\d,]*(?:\.\d+)?\s?"                      # a figure, with or
    r"(?:%|k\b|m\b|x\b|hrs?\b|hours?\b|mins?\b|minutes?\b"  # without a unit
    r"|days?\b|weeks?\b|months?\b|years?\b)?",
    re.IGNORECASE)
CAP_RE = re.compile(r"\b[A-Z][a-z]{2,}\b")
ACRONYM_RE = re.compile(r"\b(?:[A-Z]{2,6}|X)\b")   # AI, GPT, MRR, and X itself
# A capital at the start of a sentence is grammar, not a name, unless the word
# is not an ordinary one. "Here" and "You" are not concrete. "Claude" is.
COMMON = set("""
a about after again all also always an and another any are as at back be because been before
being best better both but by can could day did do does doing done down each even ever every
few first for from get gets getting go going good got had has have having he her here hers him
his how however i if in into is it its just keep know last less let like little look lot made
make many may me might more most much must my never new next no not now of off often on once
one only or other our out over own people really right said same say see she should since so
some something still such take than that the their them then there these they thing things
think this those though through time to today too two under until up us use used very was way
we well were what when where which while who why will with without would yes yet you your
""".split())
HASHTAG_RE = re.compile(r"(?:^|\s)#\w+")
MENTION_RE = re.compile(r"(?:^|\s)@\w+")
LINK_RE = re.compile(r"https?://\S+|\bwww\.\S+|\b[a-z0-9-]+\.(?:com|io|ai|co|dev|app|net|org|me|xyz|so|gg)\b(?:/\S*)?",
                     re.IGNORECASE)
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")

SPELLED_NUMBERS = {
    "zero", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "fifteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "billion", "dozen", "half", "twice", "triple",
}
MONEY_WORDS = {
    "dollars", "dollar", "bucks", "grand", "percent", "cents", "revenue",
    "profit", "salary", "mrr", "arr", "followers", "views", "impressions",
}

# Words that put something on the line.
STAKES = {
    "stop", "never", "wrong", "mistake", "mistakes", "lost", "lose", "losing",
    "cost", "costs", "broke", "broken", "failed", "failure", "fail", "nobody",
    "no", "not", "don't", "dont", "doesn't", "didn't", "can't", "won't",
    "quit", "quitting", "fired", "deleted", "delete", "killed", "kills", "kill",
    "replaced", "replaces", "cut", "beat", "free", "paid", "charged", "hired",
    "saved", "first", "banned", "illegal", "worst", "hate", "hated", "wasted",
    "waste", "scam", "lie", "lied", "lying", "truth", "secret", "hidden",
    "stole", "stolen", "before", "until", "instead", "but", "except", "unless",
    "problem", "risk", "warning", "regret", "wish", "should", "shouldn't",
    "still", "already", "only", "without", "versus", "vs", "actually",
    "hottest", "new", "overrated", "underrated", "dead", "shipped", "launched",
    "released", "announced", "introducing", "breaking", "leaked",
}

# Open loops: phrases that promise a payoff the reader has to keep going for.
LOOPS = re.compile(r"(?i)\bhere'?s (?:what|why|how|the|my)\b|\bwhat happened\b|\bturns out\b"
                   r"|\bthe (?:truth|reason|part|catch)\b|\bnobody\b"
                   r"|\beveryone (?:says|thinks|tells)\b|\bmost people\b|\bunpopular opinion\b"
                   r"|\bused to\b[^.!?]*[.!?]?[^.!?]*\bnow\b|\bago\b[^.!?]*[.!?]?[^.!?]*\btoday\b")

# Openers that spend the line saying nothing.
WEAK_OPENERS = [
    "so", "ok", "okay", "hey", "hi", "hello", "guys", "yo", "alright",
    "gm", "welcome", "today", "basically", "honestly", "look", "listen",
    "just", "let", "lets", "let's", "i wanted", "i want", "one of",
    "have you", "did you", "do you", "are you", "in this", "in today",
    "the thing", "a lot", "there is", "there are", "this is", "it is",
    "as a", "when it", "if you've", "you know", "thread", "a thread",
    "quick thread", "new thread", "friendly reminder", "reminder",
]

IMPERATIVES = {
    "stop", "steal", "copy", "delete", "try", "watch", "read", "save",
    "use", "build", "make", "write", "send", "take", "start", "quit",
    "never", "always", "don't", "dont", "do", "put", "run", "check",
    "bookmark", "unfollow", "mute", "go",
}

DEALBREAKERS = [
    (re.compile(r"(?i)^\s*(?:a\s+)?(?:(?:mega|short|quick|long|new)\s+)?thread\b|^\s*🧵"),
     "Opens on the word \"thread\". That is packaging. Put the payoff in line 1 and let X's own UI say it is a thread."),
    (re.compile(r"(?i)^\s*(?:stop scrolling|don'?t scroll)"),
     "Opens with \"stop scrolling\". Asking for attention proves you have not earned it."),
    (re.compile(r"(?i)\b(?:in (?:this|today'?s) (?:thread|post|video)|i'?m going to (?:show|teach|walk) you|i'?ll show you how)\b"),
     "Preamble. Delete it and open on the payoff."),
    (re.compile(r"(?i)^\s*(?:hey |hi |gm\b|good morning\b|what'?s up |welcome )"),
     "Greeting. Nobody opened X to be greeted."),
    (re.compile(r"^\s*\(?\d+\s*/\s*(?:\d+|n)\)?\s"),
     "Opens on a thread counter. \"1/12\" in front of the hook spends the most expensive characters you have on a page number."),
    (LINK_RE,
     "Link in the hook. Put it in a reply. It costs 23 characters here and it gives the reader a way to leave."),
    (HASHTAG_RE,
     "Hashtag in the hook. On X a hashtag is a link out of your own post."),
]


def clamp(n):
    return max(0.0, min(100.0, n))


def propers(text):
    """Capitalised words that are names, not sentence starts."""
    found = set()
    for m in CAP_RE.finditer(text):
        before = text[:m.start()].rstrip()
        sentence_start = not before or before[-1] in ".!?:\n\"“("
        if sentence_start and m.group(0).lower() in COMMON:
            continue
        found.add(m.group(0))
    found.update(ACRONYM_RE.findall(text))
    return found


def words(text):
    # "$18,000" is one word when it is read, so it is one word here too.
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def first_line(post):
    """The hook of a post is its first non-empty line."""
    for line in post.splitlines():
        if line.strip():
            return line.strip()
    return post.strip()


# ----------------------------------------------------------------- formulas

def load_formulas(path=HOOKS):
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    by_id = {h["id"]: h for h in d["hooks"]}
    order = d.get("classify_order") or sorted(by_id)
    return [(by_id[i]["id"], by_id[i]["name"], re.compile(by_id[i]["match"], re.IGNORECASE))
            for i in order if i in by_id]


FORMULAS = load_formulas()


def classify(hook, formulas=None):
    """Name the formula a hook uses. Returns (id, name) or (None, 'unclassified')."""
    formulas = FORMULAS if formulas is None else formulas
    if not formulas:
        return None, "unclassified"
    for fid, name, pattern in formulas:
        if pattern.search(hook):
            return fid, name
    return None, "unclassified"


# ------------------------------------------------------------------- checks

def check_length(text):
    """A hook has to land in one glance. On a phone that is about one line."""
    w = words(text)
    n = len(w)
    chars = len(text.strip())
    if 4 <= n <= 14:
        score = 100.0
    elif n < 4:
        score = clamp(100 - (4 - n) * 20)
    else:
        score = clamp(100 - (n - 14) * 9)
    if chars > 110:                      # wraps to a third line on a phone
        score -= 12
    return clamp(score), f"{n} words, {chars} chars (want 4-14 words, under 110 chars)"


def check_specificity(text):
    """One concrete thing beats three abstract ones."""
    nums = [n.strip() for n in NUMBER_RE.findall(text) if n.strip()]
    names = propers(text)
    low = [w.lower().strip("'’") for w in words(text)]
    spelled = [w for w in low if w in SPELLED_NUMBERS or w in MONEY_WORDS]
    hits = len(nums) + len(names) + len(spelled)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = ", ".join(nums[:2] + sorted(names)[:2] + spelled[:2])
    return score, (f"{hits} concrete marker(s)" + (f": {found}" if found else
                   " - no number, no name, nothing checkable"))


def check_stakes(text):
    """Tension, cost, negation, novelty. Something the reader might miss."""
    w = [x.lower().strip("'’") for x in words(text)]
    markers = sorted({x for x in w if x in STAKES})
    if re.search(r"\$\s?\d", text):
        markers.append("a price")
    if LOOPS.search(text):
        markers.append("an open loop")
    if text.rstrip().endswith("?") and re.search(r"(?i)\byou(?:r|'d|'re|'ve)?\b", text):
        markers.append("a question only the reader can answer")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    detail = f"{n} tension marker(s)" + (f": {', '.join(markers[:4])}" if markers else
                                         " - nothing is at stake in this line")
    return clamp(score), detail


def check_frontload(text):
    """The interesting word cannot be in position nine."""
    w = words(text)
    if not w:
        return 0.0, "empty"
    low = [x.lower().strip("'’") for x in w]
    opener = " ".join(low[:2])
    penalty, hit_opener = 0, None
    for weak in WEAK_OPENERS:
        if opener.startswith(weak + " ") or opener == weak or low[0] == weak:
            penalty, hit_opener = 30, weak
            break
    payload = None
    names = propers(text)
    if text.rstrip().endswith("?") and low[0] in {"what", "which", "who", "why", "how", "when", "where"}:
        payload = 0                      # a question leads with its own payload
    for i, token in enumerate(low):
        if payload is not None:
            break
        if (token in STAKES or token in SPELLED_NUMBERS or token in MONEY_WORDS
                or NUMBER_RE.match(w[i]) or w[i] in names):
            payload = i
    if payload is None:
        base, where = 30.0, "no payload word anywhere in the line"
    elif payload <= 3:
        base, where = 100.0, f"payload at word {payload + 1}"
    elif payload <= 6:
        base, where = 70.0, f"payload at word {payload + 1}, could move forward"
    else:
        base, where = 40.0, f"payload at word {payload + 1}, too late"
    detail = where + (f"; weak opener \"{hit_opener}\"" if hit_opener else "")
    return clamp(base - penalty), detail


def check_address(text):
    """Aimed at one reader, or floating in the air."""
    low = text.lower()
    w = [x.lower().strip("'’") for x in words(text)]
    if re.search(r"\b(you|your|you're|youre|yourself)\b", low):
        return 100.0, "speaks to the reader"
    if w and w[0] in IMPERATIVES:
        return 90.0, f"imperative opener (\"{w[0]}\")"
    if re.search(r"\b(i|i'm|im|my|me|we|our)\b", low):
        return 75.0, "first person, no reader named"
    if len(w) <= 10:
        # "The hottest new programming language is English" names nobody
        # and does not need to. A short declarative is its own address.
        return 70.0, "short declarative, no reader named"
    return 35.0, "third person, nobody in the room"


CHECKS = ["LENGTH", "SPECIFICITY", "STAKES", "FRONTLOAD", "ADDRESS"]


def run(text):
    text = first_line(text)
    results = {
        "LENGTH": check_length(text),
        "SPECIFICITY": check_specificity(text),
        "STAKES": check_stakes(text),
        "FRONTLOAD": check_frontload(text),
        "ADDRESS": check_address(text),
    }
    flags = [msg for pattern, msg in DEALBREAKERS if pattern.search(text)]
    scores = [results[c][0] for c in CHECKS]
    # The weakest property caps the hook, same logic as detect.py: one bad
    # property is enough for the thumb to keep moving.
    overall = clamp(statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15)
    verdict = "STRONG" if overall >= 70 and min(scores) >= 55 and not flags else (
        "OK" if overall >= 50 else "WEAK")
    return results, overall, verdict, flags


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_one(text, results, overall, verdict, flags, out=sys.stdout):
    line = first_line(text)
    fid, fname = classify(line)
    print("\nHOOK SCORE", file=out)
    print("=" * 62, file=out)
    print(f"  \"{line}\"", file=out)
    print(f"  formula: {('#' + str(fid) + ' ') if fid else ''}{fname}\n", file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HOOK SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    for f in flags:
        print(f"\n  DEALBREAKER  {f}", file=out)
    if verdict != "STRONG":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest property: {weakest}. Fix that one and re-run.", file=out)
    print("", file=out)


def render_table(rows, out=sys.stdout):
    print("\nHOOK RANKING\n" + "=" * 78, file=out)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 60 else r["hook"][:57] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<7} {hook}", file=out)
        tag = f"#{r['formula_id']} {r['formula']}" if r["formula_id"] else r["formula"]
        print(f"        {tag}  ·  weakest: {r['weakest']} "
              f"({r['checks'][r['weakest']]['score']:.0f})", file=out)
        for f in r["flags"]:
            print(f"        dealbreaker: {f}", file=out)
    print("\nPost the top one. If the top one is under 50, none of these is the hook.\n",
          file=out)


def score_payload(line):
    results, overall, verdict, flags = run(line)
    fid, fname = classify(first_line(line))
    return {
        "hook": first_line(line),
        "formula_id": fid,
        "formula": fname,
        "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
        "weakest": min(CHECKS, key=lambda c: results[c][0]),
        "flags": flags,
        "score": round(overall, 1),
        "verdict": verdict,
    }


def main():
    ap = argparse.ArgumentParser(description="Score the first line of an X post.")
    ap.add_argument("input", nargs="?", default="-", help="file with one hook per line, or -")
    ap.add_argument("--hook", help="score a single hook given on the command line")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("nothing to score", file=sys.stderr)
        sys.exit(2)

    payload = [score_payload(l) for l in lines]
    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return
    if len(payload) == 1:
        results, overall, verdict, flags = run(lines[0])
        render_one(lines[0], results, overall, verdict, flags)
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))
    sys.exit(0 if max(p["score"] for p in payload) >= 70 else 1)


if __name__ == "__main__":
    main()
