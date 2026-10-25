#!/usr/bin/env python3
"""How well a resume matches one job description, with the formula in plain sight. Standard library only.

    python3 ats.py score  hunter/resumes/base.md --jd hunter/jobs/google-swe.md
    python3 ats.py compare before.md after.md --jd google-swe.md     # before/after + truth check
    python3 ats.py trace  before.md after.md                         # did the rewrite invent anything?
    python3 ats.py terms  --jd google-swe.md                         # what the posting asks for

THE SCORE (0 to 100)

    score = 50 x R + 20 x P + 20 x B + 10 x S, rounded half up

    R  minimum qualifications covered (0 to 1)
    P  preferred qualifications and responsibilities covered (0 to 1)
    B  bullet strength (0 to 1)
    S  sections and contact (0 to 1)

R and P: the posting is read line by line. Each line's known terms (terms.json) are
grouped: terms separated only by commas, slashes, "and" or "or" form a list; a list
with "or" (or "e.g.", "such as", "either") is a CHOICE and is covered when any one of
its terms is in the resume; every other term is required on its own. A line's
coverage is covered groups / groups, and R (or P) is the average over the lines that
contain at least one term. A term counts only in the posting's own wording ("Go" when
the posting says Go and you wrote Golang does not count: reword it); degrees count in
any form (a B.S. is a bachelor's degree). If the posting has no preferred or
responsibilities lines, R carries 70; if it has no sections at all, every line with a
term is a minimum qualification.

B: the average, over bullets under Experience and Projects, of three checks worth a
third each: the bullet contains a number (a digit), it opens with a strong verb (not
"Worked on", "Helped", "Responsible for"), and it is 8 to 30 words long.

S: a quarter each for an Experience section, an Education section, a Skills section,
and an email or phone number.

Real applicant tracking systems differ and do not publish their formulas. This one is
transparent and reproducible: it measures whether a recruiter scanning for the
posting's words will find them, and whether each bullet proves something.

THE TRUTH CHECK (trace): every number and every known term in the rewrite must already
be in the original (or in a notes file you pass with --facts). Anything new is listed
as INVENTED and the exit code is 1. Capitalized words that are new are listed to check.
"""

import argparse
import datetime
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TERMS = os.path.join(HERE, "terms.json")

WEIGHTS = {"R": 50, "P": 20, "B": 20, "S": 10}
BULLET_MIN, BULLET_MAX = 8, 30

STRONG_VERBS = set("""
accelerated achieved added analyzed architected authored automated benchmarked boosted built
championed coached consolidated converted created cut debugged decreased defined delivered deployed
designed developed diagnosed directed doubled drove earned eliminated enabled engineered established
expanded fixed formulated founded generated grew halved hired identified implemented improved
increased initiated instrumented integrated introduced invented launched led lifted lowered
maintained managed measured mentored merged migrated modeled modernized negotiated optimized
orchestrated organized overhauled owned oversaw partnered pioneered planned presented produced
programmed proposed prototyped published raised ran rebuilt recruited redesigned reduced refactored
released reorganized replaced researched resolved restructured revamped reviewed rewrote saved
scaled scoped secured shipped simplified slashed sold solved spearheaded sped standardized started
steered streamlined supervised taught tested trained tripled tuned unified upgraded validated won
wrote made set brought began chose found held kept sent spun took undertook upheld
""".split())
WEAK_VERBS = set("""
worked helped assisted participated responsible involved tasked duties handled contributed utilized
used was were did tried attended exposed familiarized learned supported aided
""".split())

SECTION_WORDS = [
    ("experience", ("experience", "employment", "work history", "career history", "professional background")),
    ("education", ("education", "academic")),
    ("skills", ("skills", "technologies", "technical skills", "tools", "tech stack", "competencies", "languages")),
    ("projects", ("projects",)),
    ("summary", ("summary", "objective", "profile", "about")),
    ("other", ("certifications", "certificates", "awards", "publications", "volunteer", "interests", "honors",
               "leadership", "activities")),
]

JD_IGNORE = ("about the job", "about the role", "about us", "about the team", "about the company", "benefits",
             "salary", "compensation", "pay range", "equal opportunity", "perks", "location", "how to apply")
JD_PREFERRED = ("preferred qualifications", "preferred", "nice to have", "nice-to-have", "bonus points", "bonus",
                "pluses", "ideally", "it would be great if")
JD_MUST = ("minimum qualifications", "basic qualifications", "required qualifications", "requirements",
           "required", "what you'll need", "what you need", "what we're looking for", "must have", "must-have",
           "qualifications", "who you are", "you have", "you will need")
JD_RESP = ("responsibilities", "what you'll do", "what you will do", "your role", "the role", "duties",
           "day to day", "in this role")

CHOICE_WORDS = ("or", "e.g.", "eg", "such as", "either", "and/or", "one of", "any of")
NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
YEAR_RANGE_RE = re.compile(r"((?:19|20)\d\d)\s*(?:-|to|until|–)\s*((?:19|20)\d\d|present|current|now|today)", re.I)
YEARS_ASKED_RE = re.compile(r"(\d+)\+?\s+years?", re.I)
BULLET_RE = re.compile(r"^\s*(?:[-*•·▪]|\d+[.)])\s+(.*)$")


class AtsError(Exception):
    pass


# ---------------------------------------------------------------- terms

def norm_text(s):
    return (s or "").replace("’", "'").replace("‘", "'").replace(" ", " ")


def form_regex(form, case_sensitive):
    f = norm_text(form)
    parts = []
    for ch in f:
        if ch == "-":
            parts.append(r"[-\s]?")
        elif ch == " ":
            parts.append(r"\s+")
        else:
            parts.append(re.escape(ch))
    body = "".join(parts)
    if re.match(r"^[a-z]{4,}$", f):
        # one lowercase word: allow its inflections (debug, debugs, debugged, debugging)
        stem = f[:-1] if (f.endswith("e") or (f.endswith("s") and not f.endswith("ss"))) else f
        body = re.escape(stem) + "(?:e|s|es|ed|ing|[a-z]ed|[a-z]ing)?"
    elif len(f) > 2 and f[-1] == "s" and f[-2].isalpha():
        body = "".join(parts[:-1]) + "(?:s|es)?"  # plural or singular
    elif f[-1:].isalpha():
        body += "(?:s|es)?"
    pat = r"(?<![A-Za-z0-9_+#])" + body + r"(?![A-Za-z0-9_+#])"
    return re.compile(pat, 0 if case_sensitive else re.I)


def load_terms(path=TERMS, extra=None):
    terms = []
    for p in [path] + ([extra] if extra else []):
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        for t in data.get("terms", []):
            cs = set(t.get("case", []))
            terms.append({"term": t["term"], "match": t.get("match", "wording"),
                          "forms": [(f, form_regex(f, f in cs)) for f in t["forms"]]})
    return terms


def find_spans(text, terms):
    """Every term in a text, longest match first, no overlaps: [(start, end, term_index, form)]."""
    text = norm_text(text)
    cands = []
    for ti, t in enumerate(terms):
        for form, rx in t["forms"]:
            for m in rx.finditer(text):
                cands.append((m.start(), m.end(), ti, form))
    cands.sort(key=lambda c: (-(c[1] - c[0]), c[0], c[2]))
    taken, out = [], []
    for c in cands:
        if any(c[0] < e and s < c[1] for s, e in taken):
            continue
        taken.append((c[0], c[1]))
        out.append(c)
    out.sort(key=lambda c: (c[0], c[2]))
    return out


# ---------------------------------------------------------------- the posting

def _heading_kind(line):
    s = norm_text(line).strip()
    s = re.sub(r"^#+\s*", "", s).strip().strip("*").strip()
    head = s.split(":", 1)[0].strip().lower() if ":" in s else s.lower()
    rest = s.split(":", 1)[1].strip() if ":" in s else ""
    if not head or len(head.split()) > 6:
        return None, None
    head = head.rstrip(".")
    for kind, words in (("ignore", JD_IGNORE), ("preferred", JD_PREFERRED), ("must", JD_MUST),
                        ("responsibilities", JD_RESP)):
        for w in words:
            if head == w or head.startswith(w + " ") or head.endswith(" " + w):
                if ":" not in s and len(head.split()) > 4:
                    return None, None
                return kind, rest
    return None, None


def parse_jd(text):
    sections = {"must": [], "preferred": [], "responsibilities": [], "ignore": [], "header": []}
    current = "header"
    found = False
    for raw in norm_text(text).splitlines():
        if not raw.strip() or raw.strip().startswith("<!--"):
            continue
        kind, rest = _heading_kind(raw)
        if kind:
            current, found = kind, True
            if rest:
                sections[current].append(rest)
            continue
        m = BULLET_RE.match(raw)
        line = (m.group(1) if m else raw).strip()
        if line:
            sections[current].append(line)
    if not found:
        sections["must"], sections["header"] = sections["header"], []
    return sections


def line_groups(line, terms):
    """Split one requirement line into groups: a CHOICE group is covered by any one term."""
    spans = find_spans(line, terms)
    if not spans:
        return []
    groups = []
    run = [spans[0]]
    run_seps = []

    def close(run, seps):
        names = []
        for s in run:
            if s[2] not in names:
                names.append(s[2])
        choice = any(re.search(r"(^|\W)(%s)(\W|$)" % "|".join(re.escape(w) for w in CHOICE_WORDS), x, re.I)
                     for x in seps) if len(names) > 1 else False
        if choice:
            groups.append({"choice": True, "terms": names})
        else:
            for n in names:
                groups.append({"choice": False, "terms": [n]})

    for prev, cur in zip(spans, spans[1:]):
        between = line[prev[1]:cur[0]]
        filler = re.sub(r"(?i)\b(and/or|and|or|e\.g\.|eg|such as|either|including|like|one of|any of)\b", " ", between)
        filler = re.sub(r"[\s,/;()]+", "", filler)
        if filler == "":
            run.append(cur)
            run_seps.append(between)
        else:
            close(run, run_seps)
            run, run_seps = [cur], []
    close(run, run_seps)
    return groups


def requirements(jd_text, terms):
    """The posting as requirement lines with term groups, and the posting's own forms of each term."""
    sec = parse_jd(jd_text)
    jd_forms = {}
    out = {"must": [], "preferred": []}
    for name, target in (("must", "must"), ("preferred", "preferred"), ("responsibilities", "preferred")):
        for line in sec[name]:
            for s in find_spans(line, terms):
                jd_forms.setdefault(s[2], set()).add(s[3])
            groups = line_groups(line, terms)
            out[target].append({"line": line, "section": name, "groups": groups})
    return out, jd_forms, sec


# ---------------------------------------------------------------- the resume

def _section_of(line):
    s = norm_text(line).strip()
    md = re.match(r"^#{1,6}\s+(.+)$", s)
    text = (md.group(1) if md else s).strip().strip("*").strip().rstrip(":").strip()
    low = text.lower()
    if not text or len(text.split()) > 5:
        return None
    is_heading = bool(md) or (text.isupper() and any(c.isalpha() for c in text)) or s.endswith(":") \
        or any(low == w for _, ws in SECTION_WORDS for w in ws)
    if not is_heading:
        return None
    for name, words in SECTION_WORDS:
        for w in words:
            if low == w or low.endswith(" " + w) or low.startswith(w + " ") or low.startswith(w + "&"):
                return name
    return "other" if (md or text.isupper()) else None


def parse_resume(text):
    text = norm_text(text)
    sections = {"header": []}
    bullets = []
    current = "header"
    for raw in text.splitlines():
        if not raw.strip():
            continue
        sec = _section_of(raw)
        if sec:
            current = sec
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(raw.strip())
        m = BULLET_RE.match(raw)
        if m and current in ("experience", "projects"):
            bullets.append({"section": current, "text": m.group(1).strip()})
    contact = {"email": bool(EMAIL_RE.search(text)), "phone": bool(PHONE_RE.search(text))}
    return {"sections": sections, "bullets": bullets, "contact": contact}


def first_word(text):
    m = re.match(r"[^A-Za-z]*([A-Za-z]+)", text or "")
    return m.group(1).lower() if m else ""


def check_bullet(text):
    words = re.findall(r"\S+", text)
    fw = first_word(text)
    two = " ".join(w.lower() for w in re.findall(r"[A-Za-z]+", text)[:2])
    weak = fw in WEAK_VERBS or two in ("in charge", "worked on", "helped with")
    strong = (not weak) and (fw in STRONG_VERBS or (fw.endswith("ed") and len(fw) >= 5))
    has_num = bool(re.search(r"(?<![A-Za-z])\d", text))  # k8s and p99 are names, not numbers
    length_ok = BULLET_MIN <= len(words) <= BULLET_MAX
    notes = []
    if not has_num:
        notes.append("no number: how much, how many, how fast?")
    if not strong:
        notes.append('weak opening "%s": start with what you did (Built, Cut, Led, Shipped)' % (
            " ".join(re.findall(r"\S+", text)[:2]) if weak else (re.findall(r"\S+", text) or [""])[0]))
    if len(words) < BULLET_MIN:
        notes.append("%d words: too short to show the result" % len(words))
    if len(words) > BULLET_MAX:
        notes.append("%d words: too long, one achievement per bullet" % len(words))
    return {"number": has_num, "verb": strong, "length": length_ok, "words": len(words),
            "points": (has_num + strong + length_ok) / 3.0, "notes": notes}


def years_in(resume, today):
    exp = "\n".join(resume["sections"].get("experience", []))
    total = 0.0
    for a, b in YEAR_RANGE_RE.findall(exp):
        end = today.year if not b[:1].isdigit() else int(b)
        total += max(0, end - int(a))
    return total


# ---------------------------------------------------------------- scoring

def round_half_up(x):
    return int(x + 0.5)


def _term_present(term, resume_spans, jd_forms_for_term, resume_text):
    """('yes' | 'reword' | 'no', what the resume says)."""
    hits = [s for s in resume_spans if s[2] == term["_i"]]
    if not hits:
        return "no", None
    if term["match"] == "meaning":
        return "yes", resume_text[hits[0][0]:hits[0][1]]
    rxs = [rx for f, rx in term["forms"] if f in jd_forms_for_term]
    for s in hits:
        piece = resume_text[s[0]:s[1]]
        if any(rx.search(piece) for rx in rxs):
            return "yes", piece
    return "reword", resume_text[hits[0][0]:hits[0][1]]


def score(resume_text, jd_text, terms, today=None):
    for i, t in enumerate(terms):
        t["_i"] = i
    reqs, jd_forms, sec = requirements(jd_text, terms)
    rtext = norm_text(resume_text)
    rspans = find_spans(rtext, terms)
    resume = parse_resume(resume_text)

    status = {}
    for ti in jd_forms:
        status[ti] = _term_present(terms[ti], rspans, sorted(jd_forms[ti]), rtext)

    def cover(lines):
        vals, rows = [], []
        for ln in lines:
            if not ln["groups"]:
                rows.append({"line": ln["line"], "section": ln["section"], "coverage": None, "groups": []})
                continue
            covered = 0
            gout = []
            for g in ln["groups"]:
                states = [(terms[t]["term"],) + status[t] for t in g["terms"]]
                ok = any(s[1] == "yes" for s in states)
                covered += 1 if ok else 0
                gout.append({"choice": g["choice"], "covered": ok,
                             "terms": [{"term": s[0], "status": s[1], "resume_says": s[2]} for s in states]})
            cov = covered / float(len(ln["groups"]))
            vals.append(cov)
            rows.append({"line": ln["line"], "section": ln["section"], "coverage": cov, "groups": gout})
        return (sum(vals) / len(vals) if vals else None), rows

    R, must_rows = cover(reqs["must"])
    P, pref_rows = cover(reqs["preferred"])
    weights = dict(WEIGHTS)
    if P is None and R is not None:
        weights["R"], weights["P"] = WEIGHTS["R"] + WEIGHTS["P"], 0
        P = 0.0
    if R is None and P is not None:
        R, P = P, 0.0
        must_rows, pref_rows = pref_rows, []
        weights["R"], weights["P"] = WEIGHTS["R"] + WEIGHTS["P"], 0
    if R is None:
        raise AtsError("no known terms in the job description: add the posting's skills with --terms extra.json")

    checks = [dict(b, **check_bullet(b["text"])) for b in resume["bullets"]]
    B = sum(c["points"] for c in checks) / len(checks) if checks else 0.0
    secs = resume["sections"]
    s_parts = {"experience": "experience" in secs, "education": "education" in secs, "skills": "skills" in secs,
               "contact": resume["contact"]["email"] or resume["contact"]["phone"]}
    S = sum(1 for v in s_parts.values() if v) / 4.0

    parts = {"R": R, "P": P, "B": B, "S": S}
    raw = sum(weights[k] * parts[k] for k in parts)
    total = round_half_up(raw + 1e-9)

    reword, missing = [], []
    seen = set()
    for rows in (must_rows, pref_rows):
        for row in rows:
            for g in row["groups"]:
                if g["covered"]:
                    continue
                for t in g["terms"]:
                    if t["term"] in seen:
                        continue
                    seen.add(t["term"])
                    if t["status"] == "reword":
                        reword.append({"term": t["term"], "you_wrote": t["resume_says"],
                                       "posting_says": sorted(jd_forms[[i for i, x in enumerate(terms) if x["term"] == t["term"]][0]])[0],
                                       "where": row["section"]})
                    else:
                        missing.append({"term": t["term"], "where": row["section"], "choice": g["choice"]})
    asked = [int(n) for ln in reqs["must"] for n in YEARS_ASKED_RE.findall(ln["line"])]
    out = {
        "score": total,
        "raw": round(raw, 2),
        "formula": "score = 50 x R + 20 x P + 20 x B + 10 x S, rounded half up",
        "weights": weights,
        "parts": {k: round(v, 4) for k, v in parts.items()},
        "points": {k: round(weights[k] * parts[k], 2) for k in parts},
        "must": must_rows,
        "preferred": pref_rows,
        "reword": reword,
        "missing": missing,
        "bullets": checks,
        "sections": s_parts,
    }
    if today is not None:
        out["years"] = {"resume": years_in(resume, today), "asked": max(asked) if asked else None}
    return out


# ---------------------------------------------------------------- truth check

def numbers(text):
    return set(n.replace(",", "") for n in NUM_RE.findall(norm_text(text)))


def trace(before, after, terms, facts=""):
    """What the rewrite says that the original (plus facts) does not."""
    source = before + "\n" + (facts or "")
    new_numbers = sorted(numbers(after) - numbers(source), key=lambda x: (len(x), x))
    src_terms = {s[2] for s in find_spans(source, terms)}
    aft_terms = {s[2] for s in find_spans(after, terms)}
    new_terms = sorted(terms[i]["term"] for i in aft_terms - src_terms)
    src_words = set(w.lower().rstrip(".'") for w in re.findall(r"[A-Za-z][A-Za-z'+#.-]*", norm_text(source)))
    names = []
    for line in norm_text(after).splitlines():
        if _section_of(line):
            continue  # a section heading, not a claim
        m = BULLET_RE.match(line)
        body = m.group(1) if m else re.sub(r"^#+\s*", "", line.strip())
        covered = [(sp[0], sp[1]) for sp in find_spans(body, terms)]
        for sent in re.finditer(r"[^.!?:|\u00b7]+", body):
            toks = list(re.finditer(r"[A-Za-z][A-Za-z'+#-]*", sent.group(0)))
            for n, tm in enumerate(toks):
                start = sent.start() + tm.start()
                if any(a <= start < b for a, b in covered):
                    continue  # a known term: the term check above covers it
                t = tm.group(0).rstrip("'")
                low = t.lower()
                if n == 0 and (low in STRONG_VERBS or low in WEAK_VERBS or low.endswith("ed")):
                    continue  # a bullet's opening verb is a rewording, not a new fact
                if t[:1].isupper() and low not in src_words and low.rstrip("s") not in src_words:
                    if t not in names:
                        names.append(t)
    return {"invented_numbers": new_numbers, "invented_terms": new_terms, "new_names": names,
            "clean": not new_numbers and not new_terms}


# ---------------------------------------------------------------- reports

def _pct(x):
    return "%.2f" % x


def render(res, label=""):
    w, p, pts = res["weights"], res["parts"], res["points"]
    out = ["ATS match: %d / 100%s" % (res["score"], ("   " + label) if label else ""), "",
           "Formula: " + res["formula"]]
    names = {"R": "minimum qualifications covered", "P": "preferred + responsibilities covered",
             "B": "bullet strength", "S": "sections and contact"}
    for k in ("R", "P", "B", "S"):
        out.append("  %s  %-38s %s x %-2d = %5.2f" % (k, names[k], _pct(p[k]), w[k], pts[k]))
    out.append("  total %.2f, rounded %d" % (res["raw"], res["score"]))

    def rows(title, items):
        out.append("")
        out.append(title)
        for r in items:
            if r["coverage"] is None:
                continue
            mark = "x" if r["coverage"] == 1 else ("~" if r["coverage"] > 0 else " ")
            out.append("  [%s] %s" % (mark, r["line"]))
            for g in r["groups"]:
                if g["covered"]:
                    continue
                desc = " or ".join(t["term"] for t in g["terms"]) if g["choice"] else g["terms"][0]["term"]
                why = []
                for t in g["terms"]:
                    if t["status"] == "reword":
                        why.append('you wrote "%s"' % t["resume_says"])
                out.append("        missing %s%s" % (desc, (": " + "; ".join(why)) if why else ""))

    rows("Minimum qualifications", res["must"])
    if res["preferred"]:
        rows("Preferred qualifications and responsibilities", res["preferred"])
    if res["reword"]:
        out.append("")
        out.append("Reword (you have it, say it the posting's way):")
        for r in res["reword"]:
            out.append('  "%s" -> "%s"' % (r["you_wrote"], r["posting_says"]))
    if res["missing"]:
        out.append("")
        out.append("Missing (add only if it is true; otherwise leave it out and cover it in the cover letter or interview):")
        out.append("  " + ", ".join(m["term"] for m in res["missing"]))
    out.append("")
    out.append("Bullets (number, strong verb, %d to %d words):" % (BULLET_MIN, BULLET_MAX))
    if not res["bullets"]:
        out.append("  none found under Experience or Projects: one line per achievement, starting with - ")
    for i, b in enumerate(res["bullets"], 1):
        flag = "ok" if b["points"] == 1 else "; ".join(b["notes"])
        text = b["text"] if len(b["text"]) <= 70 else b["text"][:67] + "..."
        out.append("  %2d. %s\n      %s" % (i, text, flag))
    s = res["sections"]
    out.append("")
    out.append("Sections: " + ", ".join("%s %s" % (k, "yes" if v else "MISSING") for k, v in s.items()))
    if res.get("years") and res["years"]["asked"]:
        y = res["years"]
        out.append("Years: the posting asks for %d; the experience dates add up to about %d (information, not scored)." % (
            y["asked"], int(y["resume"])))
    return "\n".join(out)


def render_trace(t):
    if t["clean"]:
        out = ["Truth check: CLEAN. Every number and skill in the rewrite is in the original."]
    else:
        out = ["Truth check: INVENTED content. Remove it or confirm it with the user and add it to the original first."]
        if t["invented_numbers"]:
            out.append("  numbers not in the original: " + ", ".join(t["invented_numbers"]))
        if t["invented_terms"]:
            out.append("  skills or terms not in the original: " + ", ".join(t["invented_terms"]))
    if t["new_names"]:
        out.append("  new capitalized words to double-check: " + ", ".join(t["new_names"]))
    return "\n".join(out)


def _read(path):
    if not path or not os.path.exists(path):
        raise AtsError("no file at %s" % path)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def build_parser():
    p = argparse.ArgumentParser(description="Resume vs job description: a 0-100 match with its formula, and a truth check.")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("score", help="score one resume against a job description")
    sp.add_argument("resume")
    sp.add_argument("--jd", required=True)
    sp.add_argument("--terms", help="extra terms JSON (same shape as terms.json)")
    sp.add_argument("--today", help="YYYY-MM-DD, only for the years line (default: the computer's date)")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("compare", help="before and after scores plus the truth check")
    sp.add_argument("before")
    sp.add_argument("after")
    sp.add_argument("--jd", required=True)
    sp.add_argument("--facts", help="notes the user confirmed (numbers, tools) that the rewrite may use")
    sp.add_argument("--terms")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("trace", help="did the rewrite invent numbers or skills? (exit 1 if so)")
    sp.add_argument("before")
    sp.add_argument("after")
    sp.add_argument("--facts")
    sp.add_argument("--terms")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("terms", help="what the posting asks for, line by line")
    sp.add_argument("--jd", required=True)
    sp.add_argument("--terms")
    sp.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    try:
        terms = load_terms(TERMS, a.terms)
        if a.cmd == "score":
            today = datetime.date(*[int(x) for x in a.today.split("-")]) if a.today else datetime.date.today()
            res = score(_read(a.resume), _read(a.jd), terms, today)
            print(json.dumps(res, indent=2) if a.json else render(res, os.path.basename(a.resume)))
            return 0
        if a.cmd == "compare":
            before, after = _read(a.before), _read(a.after)
            facts = _read(a.facts) if a.facts else ""
            r1 = score(before, _read(a.jd), terms)
            r2 = score(after, _read(a.jd), terms)
            t = trace(before, after, terms, facts)
            if a.json:
                print(json.dumps({"before": r1["score"], "after": r2["score"], "before_parts": r1["parts"],
                                  "after_parts": r2["parts"], "trace": t}, indent=2))
            else:
                print("Before %d -> after %d" % (r1["score"], r2["score"]))
                for k in ("R", "P", "B", "S"):
                    print("  %s  %.2f -> %.2f" % (k, r1["parts"][k], r2["parts"][k]))
                print("")
                print(render_trace(t))
                print("")
                print(render(r2, os.path.basename(a.after)))
            return 0 if t["clean"] else 1
        if a.cmd == "trace":
            facts = _read(a.facts) if a.facts else ""
            t = trace(_read(a.before), _read(a.after), terms, facts)
            print(json.dumps(t, indent=2) if a.json else render_trace(t))
            return 0 if t["clean"] else 1
        if a.cmd == "terms":
            for i, t in enumerate(terms):
                t["_i"] = i
            reqs, jd_forms, sec = requirements(_read(a.jd), terms)
            if a.json:
                print(json.dumps({k: [{"line": l["line"], "section": l["section"],
                                       "groups": [{"choice": g["choice"], "terms": [terms[x]["term"] for x in g["terms"]]}
                                                  for g in l["groups"]]} for l in v] for k, v in reqs.items()}, indent=2))
            else:
                for k, title in (("must", "Minimum qualifications"), ("preferred", "Preferred and responsibilities")):
                    print(title)
                    for l in reqs[k]:
                        gs = ["(%s)" % " or ".join(terms[x]["term"] for x in g["terms"]) if g["choice"]
                              else terms[g["terms"][0]]["term"] for g in l["groups"]]
                        print("  - %s\n      terms: %s" % (l["line"], ", ".join(gs) if gs else "none known"))
                    print("")
            return 0
    except AtsError as e:
        print("ats: " + str(e), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
