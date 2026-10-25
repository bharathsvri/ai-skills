#!/usr/bin/env python3
"""Checks a cover letter before anyone reads it. Standard library only.

    python3 cover.py check hunter/covers/google-software-engineer.md \
        --company Google --role "Software Engineer" --team "Google Cloud, Infrastructure" \
        --resume hunter/resumes/google-software-engineer.md --pipeline hunter/pipeline.json
    python3 cover.py cliches            # the banned list

Each check is PASS, FAIL or WARN. Exit 0 when nothing FAILs.

  length        150 to 400 words (one page; recruiters skim)
  greeting      to a person or the team, never "To whom it may concern" or "Dear Sir or Madam"
  company       the company is named
  role          the role title is named (every word of it)
  team          the team or group is named, when --team is given (any one part of it)
  proof         at least one sentence with a number AND an action or result word: one concrete proof point
  cliches       none of the banned phrases (cliches list below)
  placeholders  nothing left like [Company], {role}, XXX or TODO
  other names   no OTHER company from your pipeline (a letter copied from another application)
  numbers       every number is in your resume (--resume): nothing invented
  reading       Flesch-Kincaid grade 12 or lower (WARN above)
  ask           the last paragraph asks for a next step (WARN if not)
  openers       fewer than half the sentences start with "I" (WARN)
"""

import argparse
import json
import os
import re
import sys

WORDS_MIN, WORDS_MAX = 150, 400
GRADE_MAX = 12.0

CLICHES = [
    "to whom it may concern", "dear sir or madam", "dear sir/madam", "i am writing to express my interest",
    "i am writing to apply", "please accept this letter", "i believe i would be a great fit",
    "i would be a great fit", "perfect fit", "perfect candidate", "ideal candidate", "dream job",
    "team player", "hard-working", "hardworking", "hard worker", "go-getter", "self-starter",
    "think outside the box", "outside the box", "synergy", "synergies", "results-driven",
    "detail-oriented", "detail oriented", "passionate about", "i am passionate", "proven track record",
    "track record of success", "fast-paced environment", "fast paced environment", "wear many hats",
    "hit the ground running", "dynamic individual", "highly motivated", "motivated individual",
    "excellent communication skills", "strong work ethic", "i am confident that", "thank you for your consideration",
    "leverage my skills", "add value", "value-add", "rockstar", "ninja", "guru", "best of breed",
    "in today's fast-paced", "i have always wanted to work", "since i was a child", "game changer", "game-changer",
]
PLACEHOLDER_RE = re.compile(r"\[[A-Z][^\]]{0,40}\]|\{\{?[a-z_ ]{1,30}\}?\}|<[A-Z][a-zA-Z ]{1,30}>|\bX{3,}\b|\bTODO\b|\bTBD\b|\[fill:[^\]]*\]")
NUM_RE = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)*")
ACTION_RE = re.compile(r"\b(built|rebuilt|rewrote|shipped|launched|led|cut|cutting|reduced|increased|lifted|raised|grew|"
                       r"saved|improved|doubled|halved|delivered|designed|created|wrote|ran|scaled|migrated|moved|"
                       r"won|sold|closed|drove|automated|fixed|dropped|lowered|serves|handles|"
                       r"up|down)\b", re.I)
ASK_RE = re.compile(r"\?|\b(chat|talk|conversation|discuss|interview|call|meet|coffee|hear from you|next steps?|speak)\b", re.I)
SIGNOFF_RE = re.compile(r"^\s*(thank you|thanks|best|sincerely|regards|kind regards|warmly|cheers|all the best|yours)\b", re.I)
GREETING_RE = re.compile(r"^\s*(dear|hi|hello|hey)\b[^\n]*", re.I | re.M)


class CoverError(Exception):
    pass


def words(text):
    return re.findall(r"[A-Za-z0-9][A-Za-z0-9'%$.,-]*", text)


def sentences(text):
    flat = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", flat)
    return [p.strip() for p in parts if len(words(p)) >= 3]


def syllables(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    groups = re.findall(r"[aeiouy]{1,2}", w)
    return max(1, len(groups))


def reading(text):
    sents = sentences(text) or [text]
    ws = [w for w in re.findall(r"[A-Za-z]+", text)]
    if not ws:
        return {"grade": 0.0, "ease": 100.0, "words_per_sentence": 0.0}
    syl = sum(syllables(w) for w in ws)
    wps = len(ws) / float(len(sents))
    spw = syl / float(len(ws))
    grade = 0.39 * wps + 11.8 * spw - 15.59
    ease = 206.835 - 1.015 * wps - 84.6 * spw
    return {"grade": round(grade, 1), "ease": round(ease, 1), "words_per_sentence": round(wps, 1)}


def body_of(text):
    """The letter without a markdown title line, a subject line or HTML comments."""
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    lines = [l for l in text.splitlines() if not re.match(r"^\s*(#|subject:)", l, re.I)]
    return "\n".join(lines).strip()


def paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def mentions(text, name):
    return re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", text, re.I) is not None


def other_companies(pipeline_path, company):
    if not pipeline_path or not os.path.exists(pipeline_path):
        return []
    with open(pipeline_path, encoding="utf-8") as fh:
        data = json.load(fh)
    names = []
    for r in data.get("roles", []):
        c = (r.get("company") or "").strip()
        if c and c.lower() != (company or "").lower() and c not in names:
            names.append(c)
    return names


def check(text, company=None, role=None, team=None, resume_text=None, others=None):
    body = body_of(text)
    low = body.lower()
    results = []

    def add(name, status, detail):
        results.append({"check": name, "status": status, "detail": detail})

    n = len(words(body))
    if n < WORDS_MIN:
        add("length", "FAIL", "%d words: too thin to be specific (aim for %d to %d)" % (n, WORDS_MIN, WORDS_MAX))
    elif n > WORDS_MAX:
        add("length", "FAIL", "%d words: over one page of reading (aim for %d to %d)" % (n, WORDS_MIN, WORDS_MAX))
    else:
        add("length", "PASS", "%d words" % n)

    g = GREETING_RE.search(body)
    first = (body.splitlines() or [""])[0].strip().lower()
    if "to whom it may concern" in low or "dear sir or madam" in low or "dear sir/madam" in low:
        add("greeting", "FAIL", "generic greeting: use the hiring manager's name or the team")
    elif g:
        add("greeting", "PASS", g.group(0).strip())
    else:
        add("greeting", "WARN", 'no greeting found (e.g. "Hi Maya," or "Dear Google Cloud team,"); first line: %s' % first[:60])

    if company:
        add("company", "PASS" if mentions(body, company) else "FAIL",
            "names %s" % company if mentions(body, company) else "never names %s" % company)
    if role:
        rwords = [w for w in re.findall(r"[A-Za-z0-9+#]+", role) if len(w) > 2 or w.isupper()]
        missing = [w for w in rwords if not mentions(body, w)]
        if not missing and re.search(re.escape(role), body, re.I):
            add("role", "PASS", "names the %s role" % role)
        elif not missing:
            add("role", "PASS", "names the role's words (%s)" % ", ".join(rwords))
        else:
            add("role", "FAIL", "the role title is not named (missing: %s)" % ", ".join(missing))
    if team:
        parts = [p.strip() for p in re.split(r"[,/;]", team) if p.strip()]
        hit = [p for p in parts if mentions(body, p)]
        add("team", "PASS" if hit else "FAIL", ("names " + ", ".join(hit)) if hit else "never names the team (%s)" % team)

    proofs = [s for s in sentences(body) if NUM_RE.search(s) and ACTION_RE.search(s)]
    proofs.sort(key=lambda s: 0 if re.search(r"\d\s*%|\$\s*\d|\d+x\b", s) else 1)
    if proofs:
        add("proof", "PASS", "%d proof point(s), e.g. %s" % (len(proofs), proofs[0][:90]))
    else:
        add("proof", "FAIL", "no sentence with a number and what you did: add one concrete result from your resume")

    found = [c for c in CLICHES if c in low]
    add("cliches", "FAIL" if found else "PASS", ("cut: " + "; ".join('"%s"' % c for c in found)) if found else "none")

    ph = sorted(set(m.group(0) for m in PLACEHOLDER_RE.finditer(body)))
    add("placeholders", "FAIL" if ph else "PASS", ("left in: " + ", ".join(ph)) if ph else "none")

    if others:
        named = [o for o in others if mentions(body, o)]
        add("other names", "FAIL" if named else "PASS",
            ("names %s: copied from another letter?" % ", ".join(named)) if named else "no other company named")

    if resume_text is not None:
        have = set(x.replace(",", "") for x in NUM_RE.findall(resume_text))
        nums = [x.replace(",", "") for x in NUM_RE.findall(body)]
        new = sorted(set(x for x in nums if x not in have), key=lambda x: (len(x), x))
        add("numbers", "FAIL" if new else "PASS",
            ("not in your resume, confirm or cut: " + ", ".join(new)) if new else "every number is in the resume")

    r = reading(body)
    add("reading", "WARN" if r["grade"] > GRADE_MAX else "PASS",
        "grade %.1f (Flesch-Kincaid), %.1f words a sentence" % (r["grade"], r["words_per_sentence"]))

    paras = paragraphs(body)
    closing = [p for p in paras if not SIGNOFF_RE.match(p) or len(words(p)) > 8]
    last = closing[-1] if closing else ""
    add("ask", "PASS" if ASK_RE.search(last) else "WARN",
        "ends with a next step" if ASK_RE.search(last) else "the last paragraph does not ask for anything (a chat, a call?)")

    sents = sentences(body)
    i_starts = sum(1 for s in sents if re.match(r"^I\b", s))
    if sents and i_starts * 2 >= len(sents):
        add("openers", "WARN", '%d of %d sentences start with "I"' % (i_starts, len(sents)))
    else:
        add("openers", "PASS", '%d of %d sentences start with "I"' % (i_starts, len(sents)))

    fails = sum(1 for x in results if x["status"] == "FAIL")
    warns = sum(1 for x in results if x["status"] == "WARN")
    return {"ready": fails == 0, "fails": fails, "warns": warns, "words": n, "reading": r, "checks": results}


def render(res, path=""):
    head = "READY" if res["ready"] else "FIX %d THING%s" % (res["fails"], "" if res["fails"] == 1 else "S")
    out = ["Cover letter check%s: %s" % ((" (%s)" % path) if path else "", head)]
    for c in res["checks"]:
        out.append("  %-4s  %-13s %s" % (c["status"], c["check"], c["detail"]))
    return "\n".join(out)


def _read(path):
    if not os.path.exists(path):
        raise CoverError("no file at %s" % path)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None):
    p = argparse.ArgumentParser(description="Check a cover letter: specific, true, short, no cliches.")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("check", help="run every check (exit 1 if any FAILs)")
    sp.add_argument("letter")
    sp.add_argument("--company")
    sp.add_argument("--role")
    sp.add_argument("--team")
    sp.add_argument("--resume", help="the tailored resume: every number in the letter must be in it")
    sp.add_argument("--pipeline", help="hunter/pipeline.json: flags other companies named by mistake")
    sp.add_argument("--other", help="comma-separated company names that must not appear")
    sp.add_argument("--json", action="store_true")
    sub.add_parser("cliches", help="print the banned phrases")
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    if a.cmd == "cliches":
        print("\n".join(CLICHES))
        return 0
    try:
        others = other_companies(a.pipeline, a.company)
        if a.other:
            others += [o.strip() for o in a.other.split(",") if o.strip() and o.strip() not in others]
        res = check(_read(a.letter), a.company, a.role, a.team,
                    _read(a.resume) if a.resume else None, others)
    except (CoverError, ValueError) as e:
        print("cover: " + str(e), file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if a.json else render(res, os.path.basename(a.letter)))
    return 0 if res["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
