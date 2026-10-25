#!/usr/bin/env python3
"""Mock interviews from a sourced question bank, and a STAR check on every answer. Standard library only.

    python3 star.py loop --company google                       # the rounds, with sources
    python3 star.py ask --company google --round behavioral --count 3 \
        --session hunter/interviews/google.json --today 2026-10-20
    python3 star.py check --text "At Brightline Labs our payments API..."
    python3 star.py log --session hunter/interviews/google.json --question google-behavioral-02 \
        --answer-file answer.txt --today 2026-10-20
    python3 star.py review --session hunter/interviews/google.json

THE STAR CHECK (one point each, 5 in all)

  S  Situation  context: where, when, which team or project ("At Brightline Labs last year...")
  T  Task       what YOU had to do or were asked to do ("My job was...", "I needed to...")
  A  Action     at least two things YOU did, said as "I + verb" ("I wrote...", "I ran...")
  R  Result     how it ended ("As a result...", "which cut...", an outcome verb near the end)
  N  Number     a number anywhere, best inside the result (Google's tips: accomplished X,
                as measured by Y, by doing Z; Amazon's prep page: include metrics)

It is a heuristic built from words, so read its notes as prompts, not a grade. It also
counts words (spoken: about 150 a minute; aim for 1 to 3 minutes) and flags answers
where "we" drowns out "I".

Questions come from questions.json in this folder. Each one is a practice prompt, and
its "basis" says whether the company's own page describes that round ("official", with
the URL) or candidates report it ("community"). No question is a leaked real question.
Google and NVIDIA say on their own hiring pages that AI tools are not allowed during
interviews: practice here, never during the real thing.
"""

import argparse
import datetime
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BANK = os.path.join(HERE, "questions.json")
WPM = 150

SITUATION_RE = re.compile(
    r"\b(when (i|we|our|the|my)|while|during|last (year|month|quarter|spring|summer|fall|autumn|winter|week)|"
    r"in (19|20)\d\d|our team|my team|the team|we were|we had|there was|there were|the company|our company|"
    r"a customer|our customers|the project|the situation|back in|a few (months|years) ago|my first)\b", re.I)
SITUATION_AT_RE = re.compile(r"\b(At|at) [A-Z][\w&.-]+")
TASK_RE = re.compile(
    r"\b(my (job|task|goal|role|responsibility|mandate|aim|challenge) (was|is|became)|"
    r"i was (responsible|asked|tasked|supposed|assigned|on the hook|the one)|i needed to|i had to|"
    r"we needed to|we had to|the goal was|the task was|the target was|i owned|i set out to|the problem was|"
    r"i wanted to|i was trying to|i decided to)\b", re.I)
I_VERB_RE = re.compile(r"\bI\s+(?:then\s+|also\s+|first\s+|quickly\s+|personally\s+|finally\s+|immediately\s+)?([a-z]+)")
IRREGULAR = set("""built wrote led ran made took set sent sat met spoke gave chose found drove rewrote rebuilt brought
began put cut split kept held told taught went got did shipped paired dug fought won sold bought broke rode
""".split())
NOT_ACTIONS = set("""needed wanted was were had felt thought believed hoped liked loved guessed realized knew
noticed wished expected assumed""".split())
RESULT_RE = re.compile(
    r"\b(as a result|the result|resulted in|result was|the outcome|in the end|ended up|by the end|afterwards|"
    r"since then|which (cut|reduced|increased|improved|saved|led|lifted|dropped|grew|doubled|halved|meant)|"
    r"that (cut|reduced|increased|improved|saved|lifted|dropped|meant)|so (that )?(we|the|our|it))\b", re.I)
OUTCOME_RE = re.compile(
    r"\b(cut|reduced|increased|improved|saved|lifted|dropped|fell|rose|grew|doubled|halved|tripled|shipped|"
    r"launched|delivered|won|hit|beat|passed|stopped|eliminated|recovered)\b", re.I)
NUMBER_RE = re.compile(
    r"(?<![A-Za-z])\d|\b(percent|half|halved|double|doubled|twice|triple|tripled|dozen|hundred|thousand|million|"
    r"billion|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety)\b", re.I)


class StarError(Exception):
    pass


# ---------------------------------------------------------------- the check

def sentences(text):
    flat = re.sub(r"\s+", " ", text or "").strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", flat) if s.strip()]


def i_actions(text):
    out = []
    for m in I_VERB_RE.finditer(text or ""):
        v = m.group(1).lower()
        if v in NOT_ACTIONS:
            continue
        if v in IRREGULAR or (v.endswith("ed") and len(v) > 3):
            out.append(m.group(0))
    return out


def check(text, mode="spoken"):
    text = text or ""
    sents = sentences(text)
    n = len(re.findall(r"\b[\w'%$-]+\b", text))
    found = {}

    sit = [s for s in sents[:3] if SITUATION_RE.search(s) or SITUATION_AT_RE.search(s)]
    if not sit:
        sit = [s for s in sents if SITUATION_RE.search(s) or SITUATION_AT_RE.search(s)]
    found["S"] = sit[0] if sit else None
    task = [s for s in sents if TASK_RE.search(s)]
    found["T"] = task[0] if task else None
    acts = i_actions(text)
    found["A"] = acts if len(acts) >= 2 else None
    tail = sents[max(0, int(len(sents) * 0.6)):] if sents else []
    res = [s for s in sents if RESULT_RE.search(s)] or [s for s in tail if OUTCOME_RE.search(s)]
    found["R"] = res[-1] if res else None
    digits = [s for s in sents if re.search(r"(?<![A-Za-z])\d", s)]
    words_n = [s for s in sents if NUMBER_RE.search(s)]
    if found["R"] and found["R"] in digits:
        found["N"] = found["R"]
    else:
        found["N"] = (digits or words_n or [None])[0]

    i_count = len(re.findall(r"\bI\b", text))
    we_count = len(re.findall(r"\bwe\b", text, re.I))
    notes = []
    if not found["S"]:
        notes.append("Situation: open with where and when (At <company>, last year, our team...).")
    if not found["T"]:
        notes.append("Task: say what YOU had to do (My job was..., I needed to...).")
    if not found["A"]:
        notes.append("Action: name at least two things you did, as 'I + verb' (I wrote..., I ran...).")
    if not found["R"]:
        notes.append("Result: end with what happened (As a result..., which cut...).")
    if not found["N"]:
        notes.append("Number: add one measure (how much, how many, how fast). Only a true one.")
    elif found["R"] and not NUMBER_RE.search(found["R"]):
        notes.append("Put the number in the result sentence: accomplished X, as measured by Y.")
    if we_count > max(2, 2 * i_count):
        notes.append('"we" %d times, "I" %d times: say what YOU did.' % (we_count, i_count))
    minutes = n / float(WPM)
    if mode == "spoken":
        if n < 150:
            notes.append("%d words (about %.1f minutes spoken): short; aim for 1 to 3 minutes (add the why behind one action)." % (n, minutes))
        elif n > 450:
            notes.append("%d words (about %.1f minutes spoken): too long; cut the setup, keep the actions." % (n, minutes))
    else:
        if n > 300:
            notes.append("%d words: long for a written answer; aim under 300." % n)
    score = sum(1 for k in "STARN" if found[k])
    return {"score": score, "of": 5, "found": found, "words": n, "minutes": round(minutes, 1),
            "i": i_count, "we": we_count, "notes": notes}


def render_check(res):
    names = {"S": "Situation", "T": "Task", "A": "Action", "R": "Result", "N": "Number"}
    out = ["STAR %d/5   %d words, about %.1f minutes spoken" % (res["score"], res["words"], res["minutes"])]
    for k in "STARN":
        v = res["found"][k]
        if isinstance(v, list):
            v = "; ".join(v[:3])
        mark = "yes" if v else "MISSING"
        out.append("  %s %-9s %s%s" % (k, names[k], mark, (": " + (v if len(v) <= 90 else v[:87] + "...")) if v else ""))
    for n in res["notes"]:
        out.append("  - " + n)
    return "\n".join(out)


# ---------------------------------------------------------------- the bank

def load_bank(path=BANK):
    with open(path, encoding="utf-8") as fh:
        bank = json.load(fh)
    srcs = bank.get("sources", {})
    for q in bank.get("questions", []):
        if q.get("source") not in srcs:
            raise StarError("question %s cites unknown source %r" % (q.get("id"), q.get("source")))
    return bank


def company_key(name):
    k = re.sub(r"[^a-z]", "", (name or "").lower())
    return k or "any"


def pick(bank, company, round_=None, count=3, exclude=(), include_any=False, seed=None):
    key = company_key(company)
    qs = [q for q in bank["questions"] if q["company"] == key or (include_any and q["company"] == "any")]
    if not qs and key not in bank.get("companies", {}):
        qs = [q for q in bank["questions"] if q["company"] == "any"]
    if round_:
        qs = [q for q in qs if q["round"] == round_]
    qs = [q for q in qs if q["id"] not in set(exclude)]
    if seed is not None:
        qs = list(qs)
        random.Random(seed).shuffle(qs)
    return qs[:count]


def label(bank, q):
    src = bank["sources"][q["source"]]
    if q["basis"] == "official":
        return "official: %s says %s rounds cover this (%s)" % (src["publisher"], q["round"], src["url"])
    return "community-reported, not confirmed by the company"


# ---------------------------------------------------------------- sessions

def today_from(arg):
    if not arg:
        return datetime.date.today()
    try:
        return datetime.date(*[int(x) for x in arg.split("-")])
    except (ValueError, TypeError):
        raise StarError("--today must be YYYY-MM-DD, got %r" % arg)


def load_session(path, company=None, today=None):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return {"company": company_key(company) if company else None, "started": today.isoformat() if today else None,
            "asked": [], "attempts": []}


def save_session(path, s):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(s, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def review(session, bank=None):
    atts = session.get("attempts", [])
    if not atts:
        return {"attempts": 0}
    missing = {}
    for a in atts:
        for k in "STARN":
            if not a["check"]["found"].get(k):
                missing[k] = missing.get(k, 0) + 1
    best = {}
    for a in atts:
        q = a["question_id"]
        best[q] = max(best.get(q, 0), a["check"]["score"])
    avg = sum(a["check"]["score"] for a in atts) / float(len(atts))
    out = {"attempts": len(atts), "questions": len(best), "average": round(avg, 2),
           "missing_most": sorted(missing.items(), key=lambda kv: (-kv[1], kv[0])),
           "below_4": sorted(q for q, s in best.items() if s < 4)}
    if bank and session.get("company"):
        done = set(best)
        out["not_practiced"] = [q["id"] for q in bank["questions"] if q["company"] == session["company"] and q["id"] not in done]
    return out


# ---------------------------------------------------------------- CLI

def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def main(argv=None):
    p = argparse.ArgumentParser(description="Mock interviews from a sourced question bank, with a STAR check.")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("loop", help="the company's interview rounds, with sources")
    sp.add_argument("--company", required=True)
    sp = sub.add_parser("ask", help="pick practice questions")
    sp.add_argument("--company", required=True)
    sp.add_argument("--round")
    sp.add_argument("--count", type=int, default=3)
    sp.add_argument("--include-any", action="store_true", help="also draw from the general questions")
    sp.add_argument("--seed", type=int, help="shuffle with this seed (same seed, same questions)")
    sp.add_argument("--session", help="session file: skips questions already answered and records what was asked")
    sp.add_argument("--today")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("check", help="STAR check one answer")
    sp.add_argument("--text")
    sp.add_argument("--file")
    sp.add_argument("--written", action="store_true", help="a written answer (application form), not spoken")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("log", help="check an answer and add it to the session log")
    sp.add_argument("--session", required=True)
    sp.add_argument("--question", required=True, help="question id from questions.json")
    sp.add_argument("--text")
    sp.add_argument("--answer-file")
    sp.add_argument("--today")
    sp = sub.add_parser("review", help="what the session shows: weak spots and what is left")
    sp.add_argument("--session", required=True)
    sp.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    try:
        if a.cmd == "check":
            text = read_text(a.file) if a.file else a.text
            if not text:
                raise StarError("give --text or --file")
            res = check(text, "written" if a.written else "spoken")
            print(json.dumps(res, indent=2) if a.json else render_check(res))
            return 0
        bank = load_bank()
        if a.cmd == "loop":
            key = company_key(a.company)
            c = bank["companies"].get(key)
            if not c:
                print("No sourced loop for %s. Use /hunter-research for the company's own careers pages; "
                      "general questions: star.py ask --company any" % a.company)
                return 1
            print("%s interview loop (from questions.json, checked %s)" % (c["name"], bank["as_of"]))
            for r in c["loop"]:
                src = bank["sources"][r["source"]]
                tag = "official, %s" % src["url"] if r["basis"] == "official" else "community-reported"
                print("  %-22s %s\n  %-22s [%s]%s" % (r["round"], r["what"], "", tag,
                                                      (" Note: " + r["note"]) if r.get("note") else ""))
            print("Rule: " + c["rules"])
            return 0
        if a.cmd == "ask":
            today = today_from(a.today)
            sess = load_session(a.session, a.company, today) if a.session else None
            done = [x["question_id"] for x in sess["attempts"]] if sess else []
            qs = pick(bank, a.company, a.round, a.count, done, a.include_any, a.seed)
            if not qs:
                print("No questions left for %s%s. star.py review shows how it went." % (
                    a.company, (" / " + a.round) if a.round else ""))
                return 1
            if a.json:
                print(json.dumps([dict(q, label=label(bank, q)) for q in qs], indent=2))
            else:
                for i, q in enumerate(qs, 1):
                    print("%d. [%s] %s\n   (%s, %s; %s)" % (i, q["id"], q["question"], q["round"], q["tests"], label(bank, q)))
            if sess is not None:
                for q in qs:
                    if q["id"] not in sess["asked"]:
                        sess["asked"].append(q["id"])
                save_session(a.session, sess)
            return 0
        if a.cmd == "log":
            today = today_from(a.today)
            text = read_text(a.answer_file) if a.answer_file else a.text
            if not text:
                raise StarError("give --text or --answer-file")
            q = next((q for q in bank["questions"] if q["id"] == a.question), None)
            if not q:
                raise StarError("no question %r in questions.json" % a.question)
            sess = load_session(a.session, q["company"], today)
            res = check(text)
            sess.setdefault("attempts", []).append({"date": today.isoformat(), "question_id": q["id"],
                                                    "question": q["question"], "answer": text.strip(), "check": res})
            save_session(a.session, sess)
            print(render_check(res))
            print("Logged attempt %d in %s" % (len(sess["attempts"]), a.session))
            return 0
        if a.cmd == "review":
            sess = load_session(a.session)
            r = review(sess, bank)
            if a.json:
                print(json.dumps(r, indent=2))
            elif not r["attempts"]:
                print("No answers logged yet.")
            else:
                names = {"S": "Situation", "T": "Task", "A": "Action", "R": "Result", "N": "Number"}
                print("%d answers to %d questions, average STAR %.2f / 5" % (r["attempts"], r["questions"], r["average"]))
                if r["missing_most"]:
                    print("Most often missing: " + ", ".join("%s (%d)" % (names[k], n) for k, n in r["missing_most"]))
                if r["below_4"]:
                    print("Redo (best under 4/5): " + ", ".join(r["below_4"]))
                if r.get("not_practiced"):
                    print("Not practiced yet: %d questions (star.py ask --session ...)" % len(r["not_practiced"]))
            return 0
    except (StarError, OSError, ValueError) as e:
        print("star: " + str(e), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
