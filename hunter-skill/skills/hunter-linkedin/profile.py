#!/usr/bin/env python3
"""LinkedIn profile checker for hunter-linkedin. Standard library only.

Checks a LinkedIn profile draft (headline, About, skills, experience) against
LinkedIn's field limits and against the keywords of a target job description,
and prints a before/after report. It never touches LinkedIn: the user pastes
the text into their own profile.

    python3 profile.py keywords --job hunter/jd/google-swe.txt
    python3 profile.py check --linkedin hunter/linkedin.json --job hunter/jd/google-swe.txt
    python3 profile.py compare --linkedin hunter/linkedin.json --job hunter/jd/google-swe.txt
    python3 profile.py limits

hunter/linkedin.json holds {"current": {...}, "draft": {...}}, each with
"headline", "about", "skills" (list) and "experience" ([{"title", "company",
"description"}]). Limits and their sources are in limits.json.

Keyword coverage = the weight of job-description keywords found anywhere on
the profile / the weight of all of them. Weights: 3 for terms in the required
or minimum qualifications, 2 for the body of the posting, 1 for preferred or
bonus items. A term counts once, at its highest weight.
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIMITS = os.path.join(HERE, "limits.json")
WEIGHTS = {"must": 3, "body": 2, "nice": 1}

# (display name, patterns). Patterns of 3 characters or fewer that start with a
# capital letter are matched case-sensitively ("Go" is a language, "go" is a verb).
VOCAB = [
    ("Go", ["Go", "golang"]), ("Python", ["python"]), ("Java", ["java"]), ("C++", ["c++"]),
    ("Rust", ["rust"]), ("JavaScript", ["javascript"]), ("TypeScript", ["typescript"]),
    ("Kotlin", ["kotlin"]), ("Swift", ["swift"]), ("Scala", ["scala"]), ("Ruby", ["ruby"]),
    ("SQL", ["sql"]),
    ("Distributed systems", ["distributed systems", "distributed system"]),
    ("System design", ["system design", "systems design"]),
    ("Data structures", ["data structures"]), ("Algorithms", ["algorithms"]),
    ("APIs", ["apis", "api", "rest", "restful"]), ("gRPC", ["grpc"]), ("GraphQL", ["graphql"]),
    ("Microservices", ["microservices"]), ("Backend", ["backend", "back-end"]),
    ("Frontend", ["frontend", "front-end"]), ("Full-stack", ["full-stack", "full stack"]),
    ("Kubernetes", ["kubernetes", "k8s"]), ("Docker", ["docker"]),
    ("Containers", ["containers", "containerization"]), ("Terraform", ["terraform"]),
    ("Google Cloud", ["google cloud", "gcp"]), ("AWS", ["aws", "amazon web services"]),
    ("Azure", ["azure"]), ("Kafka", ["kafka"]), ("PostgreSQL", ["postgresql", "postgres"]),
    ("MySQL", ["mysql"]), ("Redis", ["redis"]), ("Spark", ["spark"]), ("BigQuery", ["bigquery"]),
    ("Machine learning", ["machine learning", "ML"]),
    ("ML infrastructure", ["ml infrastructure", "machine learning infrastructure", "ml infra"]),
    ("Deep learning", ["deep learning"]), ("LLMs", ["llm", "llms", "large language models"]),
    ("CUDA", ["cuda"]), ("PyTorch", ["pytorch"]), ("TensorFlow", ["tensorflow"]),
    ("Observability", ["observability", "monitoring"]), ("SRE", ["sre", "site reliability"]),
    ("Reliability", ["reliability", "reliable"]), ("Scalability", ["scalability", "large-scale", "at scale"]),
    ("Performance", ["performance", "latency"]), ("On-call", ["on-call", "on call"]),
    ("Design reviews", ["design reviews", "design review"]), ("Code review", ["code review", "code reviews"]),
    ("CI/CD", ["ci/cd", "continuous integration"]), ("Testing", ["testing", "unit tests"]),
    ("Linux", ["linux"]), ("Networking", ["networking"]), ("Security", ["security"]),
    ("Infrastructure", ["infrastructure"]), ("Mentoring", ["mentoring", "mentorship"]),
    ("Technical leadership", ["technical leadership", "tech lead"]),
]
MUST = re.compile(r"(minimum|basic|required|requirements|must have|you should have|what you('|’)ll need|"
                  r"qualifications)", re.I)
NICE = re.compile(r"(preferred|bonus|nice to have|nice-to-have|pluses|a plus)", re.I)
DEFAULT_HEADLINE = re.compile(r"^[^|·,]{2,60}\s+at\s+[^|·,]{2,60}$", re.I)


class ProfileError(Exception):
    pass


def load_json(path, default=None):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def read_text(path):
    if not path or not os.path.isfile(path):
        raise ProfileError("no file %s" % path)
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _rx(pattern):
    if len(pattern) <= 3 and pattern[:1].isupper():
        return re.compile(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9+#])" % re.escape(pattern))
    return re.compile(r"(?<![a-z0-9])%s(?![a-z0-9+#])" % re.escape(pattern.lower()), re.I)


COMPILED = [(name, [_rx(p) for p in pats]) for name, pats in VOCAB]


def terms_in(text):
    """Vocabulary terms that appear in text."""
    return [name for name, rxs in COMPILED if any(r.search(text or "") for r in rxs)]


def zones(text):
    """Split a job description into (zone, line) with zone in must, body, nice."""
    zone, out = "body", []
    for line in (text or "").splitlines():
        stripped = line.strip().strip("-*• ").strip()
        is_heading = stripped and len(stripped) < 60 and not re.match(r"^[-*•]", line.strip()) and \
            (stripped.endswith(":") or stripped.istitle() or len(stripped.split()) <= 4)
        if is_heading:
            if NICE.search(stripped):
                zone = "nice"
                continue
            if MUST.search(stripped):
                zone = "must"
                continue
            if re.search(r"responsibilit|about|what you('|’)ll do|the role|the job", stripped, re.I):
                zone = "body"
                continue
        out.append((zone, line))
    return out


def keywords(jd):
    """[{term, weight, zone, count}] from a job description, heaviest first."""
    found = {}
    for zone, line in zones(jd):
        for name in terms_in(line):
            k = found.setdefault(name, {"term": name, "weight": 0, "zone": zone, "count": 0})
            k["count"] += 1
            if WEIGHTS[zone] > k["weight"]:
                k["weight"], k["zone"] = WEIGHTS[zone], zone
    order = {name: i for i, (name, _) in enumerate(VOCAB)}
    return sorted(found.values(), key=lambda k: (-k["weight"], -k["count"], order[k["term"]]))


def fields(profile):
    exp = profile.get("experience") or []
    return {
        "headline": profile.get("headline") or "",
        "about": profile.get("about") or "",
        "skills": "\n".join(profile.get("skills") or []),
        "experience": "\n".join("%s\n%s" % (e.get("title", ""), e.get("description", "")) for e in exp),
    }


def coverage(profile, kws):
    f = fields(profile)
    per = []
    for k in kws:
        where = [name for name, text in f.items() if k["term"] in terms_in(text)]
        per.append(dict(k, where=where))
    total = sum(k["weight"] for k in per) or 1
    got = sum(k["weight"] for k in per if k["where"])
    must = [k for k in per if k["zone"] == "must"]
    return {
        "score": int(round(100.0 * got / total)),
        "must_covered": sum(1 for k in must if k["where"]),
        "must_total": len(must),
        "missing_must": [k["term"] for k in must if not k["where"]],
        "missing_other": [k["term"] for k in per if k["zone"] != "must" and not k["where"]],
        "not_in_skills": [k["term"] for k in per if k["zone"] != "nice" and k["where"] and "skills" not in k["where"]],
        "terms": per,
    }


def limit_checks(profile, limits):
    L = limits["fields"]
    out = []

    def add(field, value, n):
        lim = L[field]
        ok = n <= lim["max"]
        src = lim.get("source") or "reported limit (the editor's counter is the authority)"
        out.append({"field": field, "value": n, "max": lim["max"], "unit": lim["unit"], "ok": ok, "source": src})

    add("headline", None, len(profile.get("headline") or ""))
    add("about", None, len(profile.get("about") or ""))
    add("skills", None, len(profile.get("skills") or []))
    for e in profile.get("experience") or []:
        add("position_title", None, len(e.get("title") or ""))
        add("position_description", None, len(e.get("description") or ""))
    return out


def advice(profile, cov, kws):
    """Plain-English warnings about the draft itself."""
    tips = []
    head = (profile.get("headline") or "").strip()
    if not head:
        tips.append("Headline is empty.")
    elif DEFAULT_HEADLINE.match(head):
        tips.append("Headline reads like the default \"title at company\": add what you build and your strongest "
                    "skills from the posting.")
    top = [k["term"] for k in kws if k["zone"] == "must"][:3]
    in_head = [t for t in top if t in terms_in(head)]
    if top and not in_head:
        tips.append("None of the top required terms (%s) is in the headline." % ", ".join(top))
    about = (profile.get("about") or "").strip()
    if not about:
        tips.append("About is empty: write a short story of what you build, with one or two real results.")
    elif len(about) < 600:
        tips.append("About is short (%d characters): there is room for one more real result." % len(about))
    elif not re.search(r"\d", about):
        tips.append("About has no numbers: add one result you can prove.")
    skills = profile.get("skills") or []
    if len(skills) < 5:
        tips.append("Only %d skills listed." % len(skills))
    low = [s.lower() for s in skills]
    dups = sorted(set(s for s in low if low.count(s) > 1))
    if dups:
        tips.append("Duplicate skills: %s." % ", ".join(dups))
    for e in profile.get("experience") or []:
        if e.get("description") and not re.search(r"\d", e["description"]):
            tips.append("%s at %s has no numbers: add a result you can prove." % (e.get("title"), e.get("company")))
    if cov["not_in_skills"]:
        tips.append("On the profile but not in Skills (add them if true): %s." % ", ".join(cov["not_in_skills"][:8]))
    if cov["missing_must"]:
        tips.append("Required by the posting and missing everywhere: %s. Add only what the user really has." %
                    ", ".join(cov["missing_must"]))
    return tips


def unproven(draft, truth_text, current=None):
    """Terms the draft claims that no truth source (resume, profile skills, current profile) mentions."""
    claimed = set(terms_in("\n".join(fields(draft).values())))
    known = set(terms_in(truth_text or ""))
    if current:
        known |= set(terms_in("\n".join(fields(current).values())))
    return sorted(claimed - known, key=lambda t: [n for n, _ in VOCAB].index(t))


def truth_text(profile_path, resume_path):
    parts = []
    prof = load_json(profile_path) or {}
    parts += prof.get("skills") or []
    parts += [prof.get("current", {}).get("title", "")] if isinstance(prof.get("current"), dict) else []
    if resume_path and os.path.isfile(resume_path):
        parts.append(read_text(resume_path))
    return "\n".join(p for p in parts if p)


def report(profile, jd, limits, truth=None, current=None):
    kws = keywords(jd)
    cov = coverage(profile, kws)
    checks = limit_checks(profile, limits)
    out = {"coverage": cov["score"], "must_covered": cov["must_covered"], "must_total": cov["must_total"],
           "missing_must": cov["missing_must"], "missing_other": cov["missing_other"],
           "limits": checks, "advice": advice(profile, cov, kws),
           "lengths": {"headline": len(profile.get("headline") or ""), "about": len(profile.get("about") or ""),
                       "skills": len(profile.get("skills") or [])},
           "terms": cov["terms"]}
    if truth is not None:
        out["confirm"] = unproven(profile, truth, current)
    return out


def render_check(name, rep):
    lines = ["%s profile vs the job description: keyword coverage %d%%, required terms %d/%d." % (
        name, rep["coverage"], rep["must_covered"], rep["must_total"])]
    for c in rep["limits"]:
        lines.append("  %-4s %-21s %5s / %s %s  (%s)" % ("ok" if c["ok"] else "OVER", c["field"],
                                                      "{:,}".format(c["value"]), "{:,}".format(c["max"]),
                                                      c["unit"], c["source"]))
    for t in rep["advice"]:
        lines.append("  - " + t)
    if rep.get("confirm"):
        lines.append("  - Confirm these are true before publishing (not in the resume, profile skills or current "
                     "LinkedIn): %s." % ", ".join(rep["confirm"]))
    return lines


def render_compare(before, after):
    rows = [("Headline characters", before["lengths"]["headline"], after["lengths"]["headline"]),
            ("About characters", before["lengths"]["about"], after["lengths"]["about"]),
            ("Skills", before["lengths"]["skills"], after["lengths"]["skills"]),
            ("Keyword coverage", "%d%%" % before["coverage"], "%d%%" % after["coverage"]),
            ("Required terms", "%d/%d" % (before["must_covered"], before["must_total"]),
             "%d/%d" % (after["must_covered"], after["must_total"]))]
    lines = ["%-22s %10s %10s" % ("", "before", "after")]
    for label, b, a in rows:
        fmt = lambda v: "{:,}".format(v) if isinstance(v, int) else v
        lines.append("%-22s %10s %10s" % (label, fmt(b), fmt(a)))
    had = {k["term"] for k in before["terms"] if k["where"]}
    has = {k["term"] for k in after["terms"] if k["where"]}
    order = [k["term"] for k in after["terms"]]
    gained = [t for t in order if t in has - had]
    lost = [t for t in order if t in had - has]
    lines.append("Gained: %s" % (", ".join(gained) or "nothing"))
    if lost:
        lines.append("Lost: %s" % ", ".join(lost))
    lines.append("Still missing: %s" % (", ".join(after["missing_must"] + after["missing_other"]) or "nothing"))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="LinkedIn profile check: field limits and job keyword coverage.")
    sub = ap.add_subparsers(dest="cmd")
    k = sub.add_parser("keywords", help="keywords of a job description, weighted")
    k.add_argument("--job", required=True)
    k.add_argument("--top", type=int, default=30)
    k.add_argument("--json", action="store_true")
    for name in ("check", "compare"):
        p = sub.add_parser(name, help="check the draft" if name == "check" else "before/after report")
        p.add_argument("--linkedin", default="hunter/linkedin.json")
        p.add_argument("--job", required=True, help="the job description as a text file")
        p.add_argument("--profile", default="hunter/profile.json", help="truth source: your skills")
        p.add_argument("--resume", help="truth source: your resume as text or markdown")
        p.add_argument("--limits", default=LIMITS)
        p.add_argument("--json", action="store_true")
        if name == "check":
            p.add_argument("--which", default="draft", choices=["draft", "current"])
    lm = sub.add_parser("limits", help="LinkedIn field limits and where each comes from")
    lm.add_argument("--limits", default=LIMITS)
    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2

    if args.cmd == "limits":
        doc = load_json(args.limits)
        for name, f in doc["fields"].items():
            print("%-21s %6s %-10s %s" % (name, "{:,}".format(f["max"]), f["unit"],
                                          f.get("source") or "reported: the editor's counter is the authority"))
        print("Automation: %s (%s)" % (doc["automation"]["rule"], doc["automation"]["source"]))
        return 0

    try:
        jd = read_text(args.job)
    except ProfileError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    if args.cmd == "keywords":
        kws = keywords(jd)[:args.top]
        if args.json:
            print(json.dumps(kws, indent=2))
        else:
            for x in kws:
                print("%-22s weight %d  (%s, %dx)" % (x["term"], x["weight"], x["zone"], x["count"]))
        return 0 if kws else 1

    doc = load_json(args.linkedin)
    if not doc:
        print("error: no %s. Copy skills/hunter-linkedin/linkedin.example.json there and paste the user's "
              "real profile into \"current\"." % args.linkedin, file=sys.stderr)
        return 2
    limits = load_json(args.limits)
    truth = truth_text(args.profile, args.resume)
    current = doc.get("current") or {}
    if args.cmd == "check":
        prof = doc.get(args.which) or {}
        rep = report(prof, jd, limits, truth, current if args.which == "draft" else None)
        if args.json:
            print(json.dumps(rep, indent=2))
        else:
            print("\n".join(render_check(args.which.capitalize(), rep)))
        return 0 if all(c["ok"] for c in rep["limits"]) else 1

    before = report(current, jd, limits)
    after = report(doc.get("draft") or {}, jd, limits, truth, current)
    if args.json:
        print(json.dumps({"before": before, "after": after}, indent=2))
    else:
        print("\n".join(render_compare(before, after)))
        print("")
        print("\n".join(render_check("Draft", after)))
        print("Paste the draft into LinkedIn yourself. Nothing here logs in to LinkedIn or edits your profile.")
    return 0 if all(c["ok"] for c in after["limits"]) else 1


if __name__ == "__main__":
    sys.exit(main())
