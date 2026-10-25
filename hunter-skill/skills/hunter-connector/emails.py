#!/usr/bin/env python3
"""Work-email candidates for hunter-connector. Standard library only.

Builds the likely work addresses for a person from their name and the
company's email domain, ranked by how common each corporate pattern is and,
much more strongly, by the pattern of any address the user already knows at
that company. Every candidate carries a confidence and the status "guessed".
Only an address the user found published on a public page (with its URL)
gets the status "published". Nothing here contacts a mail server: no SMTP
"verification" pings, which are unreliable and look like spam.

    python3 emails.py guess --name "Jordan Reyes" --domain example.com
    python3 emails.py guess --name "Maya C." --domain example.com
    python3 emails.py guess --name "Jordan Reyes" --domain example.com \\
        --known "Maya C. <maya.c@example.com>"
    python3 emails.py pattern --known "Jordan Reyes <jreyes@example.com>"

The base weights are rough priors for common corporate conventions, not
measured rates: first.last is the most common, then first, flast and so on.
One known address that fits a pattern lifts that pattern to 0.80, two or more
that agree to 0.90; the rest share what is left.
"""

import argparse
import json
import re
import sys
import unicodedata

# pattern -> prior weight (rough, see the docstring)
PATTERNS = [
    ("first.last", 0.36), ("first", 0.14), ("flast", 0.13), ("firstlast", 0.09),
    ("first_last", 0.05), ("firstl", 0.05), ("f.last", 0.04), ("last", 0.04),
    ("last.first", 0.03), ("lastf", 0.03), ("first-last", 0.02), ("first.l", 0.02),
]
NEEDS_LAST = {"first.last", "flast", "firstlast", "first_last", "f.last", "last", "last.first", "lastf", "first-last"}
TITLES = {"dr", "mr", "mrs", "ms", "mx", "prof", "sir"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "mba", "esq", "cpa", "pe"}
ROLE_ADDRESSES = {"careers", "jobs", "recruiting", "hr", "info", "hello", "contact", "talent", "press",
                  "support", "admin", "team", "noreply", "no-reply"}
EMAIL = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class EmailError(Exception):
    pass


def ascii_fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))


def parse_name(name):
    """'Dr. María García-López Jr.' -> {'first': 'maria', 'last': 'garcialopez', 'initial_only': False}."""
    raw = ascii_fold(name).replace("'", "").replace("’", "")
    tokens = [t for t in re.split(r"[\s,]+", raw.strip()) if t]
    tokens = [t for t in tokens if t.lower().strip(".") not in TITLES or len(tokens) <= 2]
    while len(tokens) > 2 and tokens[-1].lower().strip(".") in SUFFIXES:
        tokens.pop()
    if not tokens:
        raise EmailError("no name given")
    clean = lambda t: re.sub(r"[^a-z]", "", t.lower())
    first = clean(tokens[0])
    last_raw = tokens[-1] if len(tokens) > 1 else ""
    last = clean(last_raw)
    if not first:
        raise EmailError("could not read a first name from %r" % name)
    initial_only = len(last) <= 1
    return {"first": first, "last": last, "initial_only": initial_only,
            "last_initial": last[:1], "hyphenated": "-" in last_raw}


def local_part(pattern, n):
    f, l = n["first"], n["last"]
    li = n["last_initial"]
    return {
        "first.last": "%s.%s" % (f, l), "first": f, "flast": f[:1] + l, "firstlast": f + l,
        "first_last": "%s_%s" % (f, l), "firstl": f + li, "f.last": "%s.%s" % (f[:1], l),
        "last": l, "last.first": "%s.%s" % (l, f), "lastf": l + f[:1], "first-last": "%s-%s" % (f, l),
        "first.l": "%s.%s" % (f, li),
    }[pattern]


def parse_known(text):
    """'Jordan Reyes <jordan.reyes@example.com>' -> (name, email)."""
    m = re.match(r"^\s*(.+?)\s*<\s*([^>]+?)\s*>\s*$", text or "")
    if not m:
        raise EmailError("--known wants 'First Last <address>', got %r" % text)
    email = m.group(2).lower()
    if not EMAIL.match(email):
        raise EmailError("not an email address: %r" % m.group(2))
    return m.group(1), email


def patterns_for(name, email):
    """Which patterns produce this address for this name."""
    n = parse_name(name)
    local = email.split("@", 1)[0].lower()
    local = re.sub(r"\+.*$", "", local)
    hits = []
    for p, _ in PATTERNS:
        if p in NEEDS_LAST and n["initial_only"]:
            continue
        if local_part(p, n) == local:
            hits.append(p)
    return hits


def learn(known, domain=None):
    """From known (name, email) pairs -> ({pattern: count}, notes)."""
    counts, notes = {}, []
    for name, email in known:
        dom = email.split("@", 1)[1]
        if domain and dom != domain.lower():
            notes.append("%s is at %s, not %s: not used" % (email, dom, domain))
            continue
        if email.split("@", 1)[0] in ROLE_ADDRESSES:
            notes.append("%s is a shared inbox, not a person: not used" % email)
            continue
        hits = patterns_for(name, email)
        if not hits:
            notes.append("%s fits none of the common patterns for %s" % (email, name))
            continue
        for p in hits:
            counts[p] = counts.get(p, 0) + 1.0 / len(hits)
    return counts, notes


def label(conf):
    return "high" if conf >= 0.7 else ("medium" if conf >= 0.3 else "low")


def guess(name, domain, known=(), found=None, found_source=None):
    """Ranked candidates: [{email, pattern, confidence, label, status, why}]."""
    domain = (domain or "").lower().strip().lstrip("@")
    if not re.match(r"^[a-z0-9.\-]+\.[a-z]{2,}$", domain):
        raise EmailError("--domain wants the company's email domain, like example.com")
    n = parse_name(name)
    counts, notes = learn(known, domain)
    weights = {p: w for p, w in PATTERNS}
    learned = None
    if counts:
        top = max(counts.values())
        best = sorted(p for p, c in counts.items() if c == top)
        support = int(round(sum(counts.values())))
        share = 0.90 if support >= 2 and len(best) == 1 else 0.80
        if len(best) > 1:
            share = 0.80 / len(best) * len(best)
        rest = sum(w for p, w in PATTERNS if p not in best) or 1.0
        weights = {p: (share / len(best) if p in best else (1.0 - share) * w / rest) for p, w in PATTERNS}
        learned = best
    out = []
    usable = [p for p, _ in PATTERNS if not (p in NEEDS_LAST and n["initial_only"])]
    # no renormalising when only an initial is known: the likeliest patterns need the
    # full last name, so the ones left keep their small absolute weights
    for p in usable:
        conf = round(weights[p], 2)
        why = "common pattern %s" % p
        if learned and p in learned:
            n_known = max(1, int(round(counts[p])))
            why = "pattern %s learned from %d known address%s at %s" % (p, n_known, "" if n_known == 1 else "es", domain)
            if len(learned) > 1:
                why += " (known addresses disagree)"
        out.append({"email": "%s@%s" % (local_part(p, n), domain), "pattern": p, "confidence": conf,
                    "label": label(conf), "status": "guessed", "why": why})
    if n["initial_only"]:
        notes.append("only a last initial is known: patterns that need the full last name (first.last, flast, "
                     "...) are left out. Get the full name from their public profile first.")
    if found:
        f = found.lower().strip()
        if not EMAIL.match(f) or not f.endswith("@" + domain):
            raise EmailError("--found must be an address at %s" % domain)
        if not found_source or not re.match(r"^https?://", found_source):
            raise EmailError("--found needs --found-source: the public URL where the address is published")
        out = [c for c in out if c["email"] != f]
        out.insert(0, {"email": f, "pattern": (patterns_for(name, f) or ["published"])[0], "confidence": 1.0,
                       "label": "published", "status": "published", "why": "published at %s" % found_source})
    out.sort(key=lambda c: (-c["confidence"], c["email"]))
    seen, uniq = set(), []
    for c in out:
        if c["email"] not in seen:
            seen.add(c["email"])
            uniq.append(c)
    return {"name": name, "domain": domain, "candidates": uniq, "learned": learned, "notes": notes}


def render(res, top=6):
    lines = ["Likely addresses for %s at %s (guesses ranked by pattern; none is verified):" % (res["name"], res["domain"])]
    for c in res["candidates"][:top]:
        lines.append("  %-34s %4.2f  %-9s %s" % (c["email"], c["confidence"], c["label"], c["why"]))
    for n in res["notes"]:
        lines.append("note: %s" % n)
    lines.append("A guess is a guess: it becomes certain only when the address is published or the person replies.")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Likely work-email addresses, each with a confidence. No mail server is contacted.")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("guess", help="ranked candidates for one person")
    g.add_argument("--name", required=True)
    g.add_argument("--domain", required=True)
    g.add_argument("--known", action="append", default=[], help="'First Last <address>' you already know there")
    g.add_argument("--found", help="an address you found published on a public page")
    g.add_argument("--found-source", help="the URL where it is published")
    g.add_argument("--top", type=int, default=6)
    g.add_argument("--json", action="store_true")
    p = sub.add_parser("pattern", help="which pattern known addresses use")
    p.add_argument("--known", action="append", required=True)
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2
    try:
        known = [parse_known(k) for k in args.known]
        if args.cmd == "pattern":
            counts, notes = learn(known)
            for p_, c in sorted(counts.items(), key=lambda x: -x[1]):
                print("%-12s fits %g known address%s" % (p_, c, "" if c == 1 else "es"))
            for n in notes:
                print("note: %s" % n)
            return 0 if counts else 1
        res = guess(args.name, args.domain, known, args.found, args.found_source)
    except EmailError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        sys.stdout.write(render(res, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
