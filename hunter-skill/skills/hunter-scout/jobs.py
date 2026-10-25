#!/usr/bin/env python3
"""Job Scout for hunter-scout. Standard library only.

Pulls open roles from public job boards that need no login, filters them to
the user's target titles and places, scores each one 0-100 against
hunter/profile.json with the reasons, and writes hunter/jobs.json.

    python3 jobs.py search                         # dream companies from hunter/profile.json
    python3 jobs.py search --company Stripe --company Discord --days 30
    python3 jobs.py search --all --remote          # every automatic board in boards.json
    python3 jobs.py pick discord-senior-software-engineer-ads-8697883002
    python3 jobs.py boards                         # what is automatic, what is manual and why
    python3 jobs.py check --company Ramp           # re-verify a board token live

Sources (public JSON, one request per board plus a few job details):
  Greenhouse  https://boards-api.greenhouse.io/v1/boards/<token>/jobs
  Lever       https://api.lever.co/v0/postings/<token>?mode=json
  Ashby       https://api.ashbyhq.com/posting-api/job-board/<token>?includeCompensation=true
  Workday     POST https://<host>/wday/cxs/<tenant>/<site>/jobs  (NVIDIA)
  Eightfold   https://<host>/api/apply/v2/jobs?domain=<domain>&query=...  (Netflix)
Google, Meta and Amazon have no feed this tool may read (robots.txt or terms);
`boards` prints the manual route for each.

Fit score (0-100) = title 35 + skills 30 + location 15 + seniority 10
+ pay 5 + freshness 5. The formula is in score() and every point comes with
a reason. Offline: --offline DIR reads <type>-<token>.json files (tests).
"""

import argparse
import datetime as _dt
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BOARDS = os.path.join(HERE, "boards.json")
UA = "hunter-skill/1.0 (job scout; +https://github.com/Jakeschincariol/hunter-skill)"
AUTO = ("greenhouse", "lever", "ashby", "workday", "eightfold")
EMDASH, ENDASH = chr(0x2014), chr(0x2013)  # built from code points: the repo has no literal em dash

GH_LIST = "https://boards-api.greenhouse.io/v1/boards/%s/jobs"
GH_JOB = "https://boards-api.greenhouse.io/v1/boards/%s/jobs/%s"
GH_BOARD = "https://boards-api.greenhouse.io/v1/boards/%s"
LEVER = "https://api.lever.co/v0/postings/%s?mode=json"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true"
WORKDAY = "https://%s/wday/cxs/%s/%s/jobs"
EIGHTFOLD = "https://%s/api/apply/v2/jobs?domain=%s&query=%s&start=%d&num=%d"

TITLE_ALIASES = {
    "software engineer": ["software development engineer", "software engineering", "sde", "swe",
                          "software developer"],
    "backend engineer": ["back-end engineer", "backend software engineer", "server engineer"],
    "frontend engineer": ["front-end engineer", "frontend software engineer"],
    "machine learning engineer": ["ml engineer", "deep learning engineer"],
    "infrastructure engineer": ["platform engineer", "site reliability engineer", "sre"],
}
SKILL_ALIASES = {
    "go": ["golang"], "javascript": ["js"], "typescript": ["ts"], "kubernetes": ["k8s"],
    "postgresql": ["postgres"], "machine learning": ["ml"], "google cloud": ["gcp"],
    "aws": ["amazon web services"], "apis": ["api", "rest"], "distributed systems": ["distributed system"],
    "c++": ["cpp"],
}
US_STATES = ("alabama alaska arizona arkansas california colorado connecticut delaware florida georgia "
             "hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts "
             "michigan minnesota mississippi missouri montana nebraska nevada ohio oklahoma oregon "
             "pennsylvania tennessee texas utah vermont virginia washington wisconsin wyoming").split()
US_CODES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
            "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
NON_US = ("europe", "emea", "apac", "united kingdom", "london", "uk", "ireland", "dublin", "india",
          "bengaluru", "bangalore", "hyderabad", "israel", "poland", "warsaw", "germany", "berlin",
          "canada", "toronto", "singapore", "japan", "tokyo", "netherlands", "amsterdam", "france",
          "paris", "spain", "madrid", "brazil", "mexico", "australia", "sydney", "korea", "taiwan",
          "china", "vietnam", "switzerland", "zurich", "sweden", "lisbon", "portugal")
AREAS = {
    "san francisco bay area": ["san francisco", "bay area", "mountain view", "palo alto", "menlo park",
                               "sunnyvale", "san jose", "santa clara", "los gatos", "oakland",
                               "redwood city", "san mateo", "south san francisco", "cupertino", "foster city"],
    "new york": ["new york", "nyc", "brooklyn"],
    "seattle": ["seattle", "bellevue", "redmond", "kirkland"],
    "los angeles": ["los angeles", "santa monica", "culver city", "playa vista"],
}


class ScoutError(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def load_json(path, default=None):
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def save_json(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def slug(text, limit=48):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(s) > limit:
        s = s[:limit].rsplit("-", 1)[0]
    return s


def clean_title(t):
    t = (t or "").replace(EMDASH, "-").replace(ENDASH, "-")
    return re.sub(r"\s+", " ", t).strip()


def html_text(s):
    """HTML (possibly escaped twice, as Greenhouse sends it) -> plain text."""
    s = html.unescape(s or "")
    if "&lt;" in s or "&amp;" in s:
        s = html.unescape(s)
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("\xa0", " ")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def parse_day(value):
    """'2026-10-15' or an ISO stamp -> date (the date as published, no time zone math)."""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def epoch_day(value, millis=False):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if millis:
        v /= 1000.0
    return _dt.datetime.fromtimestamp(v, tz=_dt.timezone.utc).date()


def money(token):
    t = token.replace(",", "").replace(" ", "").lower()
    mult = 1000 if t.endswith("k") else 1
    t = t.rstrip("k")
    try:
        return int(round(float(t) * mult))
    except ValueError:
        return None


MONEY = r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?\s?[kK]?)"
PAY_RANGE = re.compile(MONEY + r"\s*(?:USD)?\s*(?:-|" + ENDASH + "|" + EMDASH + r"|to)\s*" + MONEY, re.I)


def pay_from_text(text):
    """First '$196,000 to $245,000' style range in a posting, or None."""
    m = PAY_RANGE.search(text or "")
    if not m:
        return None
    lo, hi = money(m.group(1)), money(m.group(2))
    if not lo or not hi or hi < lo:
        return None
    tail = (text or "")[m.end():m.end() + 30].lower()
    period = "year"
    if hi < 1000 or "hour" in tail or "/hr" in tail:
        period = "hour"
    return {"min": lo, "max": hi, "currency": "USD", "period": period}


def annual(pay):
    if not pay:
        return None
    mult = {"year": 1, "month": 12, "hour": 2080}.get(pay.get("period"), 1)
    return pay["max"] * mult


def fmt_money(n, currency="USD"):
    sign = {"USD": "$", "GBP": "\u00a3", "EUR": "\u20ac"}.get(currency or "USD")
    return (sign or (currency + " ")) + "{:,}".format(int(n))


def fmt_pay(pay):
    per = "" if pay.get("period") == "year" else " a " + pay.get("period", "year")
    return "%s to %s%s" % (fmt_money(pay["min"], pay.get("currency")), fmt_money(pay["max"], pay.get("currency")), per)


# ---------------------------------------------------------------- fetching

class Fetcher(object):
    """Polite HTTP: identifies itself, pauses between calls. Offline reads files."""

    def __init__(self, offline=None, pause=0.5, timeout=40):
        self.offline = offline
        self.pause = pause
        self.timeout = timeout
        self.calls = 0
        self._last = 0.0

    def get(self, url, name, body=None):
        if self.offline:
            path = os.path.join(self.offline, name)
            if not os.path.isfile(path):
                raise ScoutError("offline: no file %s" % name)
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)
        self._last = time.time()
        self.calls += 1
        headers = {"User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "gzip"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
        except urllib.error.HTTPError as exc:
            raise ScoutError("HTTP %s for %s" % (exc.code, url))
        except urllib.error.URLError as exc:
            raise ScoutError("could not reach %s: %s" % (url, exc.reason))
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            raise ScoutError("not JSON from %s" % url)


# ---------------------------------------------------------------- normalizers

def _job(board, source_id, title, location, url, posted, text="", remote=False, pay=None, note=None):
    company = board["company"]
    sid = re.sub(r"[^a-z0-9]", "", str(source_id).lower())
    job = {
        "id": "%s-%s-%s" % (slug(company, 20), slug(clean_title(title), 40), sid if len(sid) <= 10 else sid[-8:]),
        "company": company,
        "title": clean_title(title),
        "location": re.sub(r"\s+", " ", location or "").strip() or "not listed",
        "url": url,
        "source": board["type"],
        "posted": posted.isoformat() if posted else None,
        "remote": bool(remote),
        "pay": pay,
        "_text": text or "",
        "_sid": str(source_id),
    }
    if note:
        job["posted_note"] = note
    return job


def from_greenhouse(board, data):
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        offices = ", ".join(o.get("name", "") for o in j.get("offices", []) if o.get("name"))
        text = html_text(j.get("content", ""))
        remote = "remote" in (loc + " " + offices).lower()
        out.append(_job(board, j.get("id"), j.get("title"), loc, j.get("absolute_url"),
                        parse_day(j.get("first_published") or j.get("updated_at")), text, remote,
                        pay_from_text(text)))
    return out


def from_lever(board, data):
    out = []
    for p in data if isinstance(data, list) else []:
        cat = p.get("categories") or {}
        text = "\n".join(p.get(k) or "" for k in ("descriptionPlain", "descriptionBodyPlain", "additionalPlain"))
        for lst in p.get("lists") or []:
            text += "\n" + lst.get("text", "") + "\n" + html_text(lst.get("content", ""))
        pay = None
        rng = p.get("salaryRange")
        if rng and rng.get("min") and rng.get("max"):
            pay = {"min": rng["min"], "max": rng["max"], "currency": rng.get("currency", "USD"),
                   "period": "year" if "year" in str(rng.get("interval", "year")) else "hour"}
        pay = pay or pay_from_text(text)
        remote = p.get("workplaceType") == "remote" or "remote" in (cat.get("location") or "").lower()
        out.append(_job(board, p.get("id"), p.get("text"), cat.get("location"), p.get("hostedUrl"),
                        epoch_day(p.get("createdAt"), millis=True), text, remote, pay))
    return out


def from_ashby(board, data):
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        pay = None
        for comp in (j.get("compensation") or {}).get("summaryComponents", []) or []:
            if comp.get("compensationType") == "Salary" and comp.get("minValue") and comp.get("maxValue"):
                interval = str(comp.get("interval", "1 YEAR")).upper()
                pay = {"min": comp["minValue"], "max": comp["maxValue"],
                       "currency": comp.get("currencyCode") or "USD",
                       "period": "month" if "MONTH" in interval else ("hour" if "HOUR" in interval else "year")}
        loc = j.get("location") or ""
        extra = [s.get("location") for s in j.get("secondaryLocations") or [] if s.get("location")]
        if extra:
            loc += " (+%d more)" % len(extra)
        remote = (j.get("workplaceType") or "").lower() == "remote"
        text = j.get("descriptionPlain") or html_text(j.get("descriptionHtml", ""))
        out.append(_job(board, j.get("id"), j.get("title"), loc, j.get("jobUrl"),
                        parse_day(j.get("publishedAt")), text, remote, pay or pay_from_text(text)))
    return out


def workday_posted(text, today):
    """'Posted Today' / 'Posted Yesterday' / 'Posted 7 Days Ago' / 'Posted 30+ Days Ago'."""
    t = (text or "").lower()
    if "today" in t:
        return today, None
    if "yesterday" in t:
        return today - _dt.timedelta(days=1), None
    m = re.search(r"(\d+)(\+?)\s*days?", t)
    if m:
        days = int(m.group(1))
        return today - _dt.timedelta(days=days), ("%s+ days ago" % days if m.group(2) else None)
    return None, None


def from_workday(board, data, today):
    out = []
    base = "https://%s/%s" % (board["host"], board["site"])
    for p in data.get("jobPostings", []):
        path = p.get("externalPath") or ""
        sid = (p.get("bulletFields") or [path.rsplit("_", 1)[-1]])[0]
        loc = p.get("locationsText") or ""
        m = re.match(r"/job/([^/]+)/", path)
        if m and re.match(r"\d+ Locations", loc):
            loc = "%s (+%d more)" % (m.group(1).replace("-", ", ", 2).replace("-", " "), int(loc.split()[0]) - 1)
        posted, note = workday_posted(p.get("postedOn"), today)
        remote = "remote" in loc.lower()
        out.append(_job(board, sid, p.get("title"), loc, base + path, posted, "", remote, None, note))
    return out


def from_eightfold(board, data):
    out = []
    for p in data.get("positions", []):
        locs = p.get("locations") or [p.get("location") or ""]
        loc = "; ".join(l.replace(",", ", ") for l in locs if l)
        # "remote_local" means remote near an office, so it is not counted as remote
        remote = str(p.get("work_location_option") or "") == "remote" or "remote" in loc.lower()
        url = p.get("canonicalPositionUrl") or "https://%s/careers/job/%s" % (board["host"], p.get("id"))
        # the search feed carries no description: skills are checked on the posting itself
        out.append(_job(board, p.get("id"), p.get("posting_name") or p.get("name"), loc, url,
                        epoch_day(p.get("t_create")), "", remote))
    return out


def title_keywords(roles):
    out = []
    for r in roles or []:
        r = r.strip()
        if r and r.lower() not in [o.lower() for o in out]:
            out.append(r)
    return out[:3] or ["Software Engineer"]


def fetch_board(fetcher, board, today, roles, details=10, notes=None, exclude=None):
    """All open jobs on one board, normalized. Errors become notes."""
    notes = [] if notes is None else notes
    kind, token = board["type"], board.get("token")
    try:
        if kind == "greenhouse":
            jobs = from_greenhouse(board, fetcher.get(GH_LIST % token, "greenhouse-%s.json" % token))
            # the list has no descriptions: fetch details for title matches only (newest first)
            need = [j for j in jobs if not j["_text"] and title_points(j["title"], roles)[0] >= 15
                    and not excluded(j["title"], exclude)]
            need.sort(key=lambda j: j["posted"] or "", reverse=True)
            for j in need[:details]:
                jid = j["_sid"]
                try:
                    one = fetcher.get(GH_JOB % (token, jid), "greenhouse-%s-%s.json" % (token, jid))
                except ScoutError:
                    continue
                full = from_greenhouse(board, {"jobs": [one]})
                if full:
                    j["_text"], j["pay"] = full[0]["_text"], full[0]["pay"]
            return jobs
        if kind == "lever":
            return from_lever(board, fetcher.get(LEVER % token, "lever-%s.json" % token))
        if kind == "ashby":
            return from_ashby(board, fetcher.get(ASHBY % token, "ashby-%s.json" % token))
        if kind == "workday":
            jobs, seen = [], set()
            url = WORKDAY % (board["host"], board["tenant"], board["site"])
            for kw in title_keywords(roles):
                body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": kw}
                for j in from_workday(board, fetcher.get(url, "workday-%s.json" % token, body), today):
                    if j["id"] not in seen:
                        seen.add(j["id"])
                        jobs.append(j)
                if fetcher.offline:
                    break
            return jobs
        if kind == "eightfold":
            jobs, seen = [], set()
            for kw in title_keywords(roles):
                url = EIGHTFOLD % (board["host"], board["domain"], urllib.parse.quote(kw), 0, 20)
                for j in from_eightfold(board, fetcher.get(url, "eightfold-%s.json" % token)):
                    if j["id"] not in seen:
                        seen.add(j["id"])
                        jobs.append(j)
                if fetcher.offline:
                    break
            return jobs
        notes.append("%s: no feed (%s)" % (board["company"], kind))
    except ScoutError as exc:
        notes.append("%s (%s %s): %s" % (board["company"], kind, token, exc))
    return []


# ---------------------------------------------------------------- scoring

def _norm(s):
    return " " + re.sub(r"[^a-z0-9+#]+", " ", (s or "").lower()).strip() + " "


def title_points(title, roles):
    """(points 0-35, reason) for how well a title matches the target roles."""
    t = _norm(title)
    best, why = 0, None
    for role in roles or []:
        r = _norm(role).strip()
        if not r:
            continue
        names = [r] + TITLE_ALIASES.get(r, [])
        if any(" %s " % n in t for n in names):
            return 35, "title matches %s" % role
        words = [w for w in r.split() if len(w) > 2]
        if words and all(" %s " % w in t for w in words):
            pts, reason = 30, "title has every word of %s" % role
        else:
            hit = [w for w in words if " %s " % w in t]
            pts = int(round(20.0 * len(hit) / len(words))) if words else 0
            reason = "title partly matches %s" % role if hit else None
        if pts > best:
            best, why = pts, reason
    return best, why


def excluded(title, words):
    """The first exclude word in the title (Intern also catches Interns and Internship)."""
    for w in words or []:
        if re.search(r"(?<![a-z0-9])%s(?:s|ship|ships)?(?![a-z0-9])" % re.escape(_norm(w).strip()), _norm(title)):
            return w
    return None


def skill_hits(text, skills):
    hits = []
    for s in skills or []:
        names = [s] + SKILL_ALIASES.get(s.lower(), [])
        for n in names:
            if len(n) <= 3 and n[:1].isupper():
                rx = r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9+#])" % re.escape(n)
                flags = 0
            else:
                rx = r"(?<![a-z0-9])%s(?![a-z0-9+#])" % re.escape(n.lower())
                flags = re.I
            if re.search(rx, text, flags):
                hits.append(s)
                break
    return hits


def is_us(loc):
    low = (loc or "").lower()
    if re.search(r"united states|\bu\.s\.|\busa\b|\bus\b|remote \(u\.?s", low):
        return True
    if any(re.search(r"\b%s\b" % s, low) for s in US_STATES):
        return True
    return bool(re.search(r"\b(?:%s)\b" % "|".join(US_CODES), loc or ""))


def non_us(loc):
    low = (loc or "").lower()
    return any(re.search(r"\b%s\b" % re.escape(w), low) for w in NON_US)


def place_match(loc, places):
    low = (loc or "").lower()
    for p in places or []:
        city = p.split(",")[0].strip().lower()
        names = AREAS.get(city, [city]) if city else []
        for area, members in AREAS.items():
            if city in members or city == area:
                names = members
        if any(n and n in low for n in names):
            return p
    return None


def years_asked(text):
    m = re.search(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years|yrs)", text or "", re.I)
    return int(m.group(1)) if m else None


def score(job, profile, today):
    """(score 0-100, reasons, warnings). Formula: title 35, skills 30, location 15,
    seniority 10, pay 5, freshness 5."""
    roles = profile.get("target_roles") or []
    why, warn = [], []
    t_pts, t_why = title_points(job["title"], roles)
    if t_why:
        why.append(t_why)

    text = job["title"] + "\n" + job.get("_text", "")
    skills = profile.get("skills") or []
    hits = skill_hits(text, skills)
    if job.get("_text", "").strip():
        s_pts = int(round(30.0 * min(1.0, len(hits) / float(max(1, min(6, len(skills)))))))
        if hits:
            why.append("%d of your skills in the posting: %s" % (len(hits), ", ".join(hits[:6])))
        else:
            warn.append("none of your skills appear in the posting")
    else:
        s_pts = max(10, int(round(30.0 * min(1.0, len(hits) / 6.0))))
        warn.append("the feed has no description, skills not checked: open the posting")

    loc = job["location"]
    place = place_match(loc, profile.get("locations"))
    us_only = (profile.get("work_authorization") or {}).get("country", "US") == "US"
    if job.get("remote") and not (us_only and non_us(loc) and not is_us(loc)):
        l_pts = 15
        why.append("remote (%s)" % loc if profile.get("remote", True) else "remote")
        if not profile.get("remote", True):
            l_pts = 8
    elif place:
        l_pts = 15
        why.append("in %s, one of your locations" % place)
    elif profile.get("relocate") and (is_us(loc) or not us_only) and not (us_only and non_us(loc) and not is_us(loc)):
        l_pts = 8
        why.append("in %s (you are open to relocating)" % loc)
    else:
        l_pts = 0
        warn.append("%s is outside your locations" % loc)

    years = profile.get("years_experience")
    asked = years_asked(job.get("_text", ""))
    senior = re.search(r"\b(senior|sr\.?)\b", job["title"], re.I)
    if asked is not None and years is not None and asked > years + 1:
        y_pts = 3
        warn.append("asks for %d+ years, you have %s" % (asked, years))
    elif senior and years is not None and years < 5:
        y_pts = 4
        warn.append("senior title, you have %s years" % years)
    else:
        y_pts = 10

    floor = profile.get("salary_floor")
    pay = job.get("pay")
    if pay and floor:
        if annual(pay) >= floor:
            p_pts = 5
            why.append("pays %s, clears your %s floor" % (fmt_pay(pay), fmt_money(floor, pay.get("currency"))))
        else:
            p_pts = 0
            warn.append("pays %s, under your %s floor" % (fmt_pay(pay), fmt_money(floor, pay.get("currency"))))
    else:
        p_pts = 2

    posted = parse_day(job.get("posted"))
    if posted:
        age = (today - posted).days
        when = job.get("posted_note") or ("today" if age <= 0 else ("yesterday" if age == 1 else "%d days ago" % age))
        f_pts = 5 if age <= 7 else (3 if age <= 30 else 1)
        (why if age <= 30 else warn).append("posted %s" % when)
    else:
        f_pts = 2

    dream = [c.lower() for c in profile.get("dream_companies") or []]
    if job["company"].lower() in dream:
        why.append("one of your dream companies")
    total = t_pts + s_pts + l_pts + y_pts + p_pts + f_pts
    return min(100, total), why, warn


# ---------------------------------------------------------------- search

def pick_boards(boards, companies=None, use_all=False, profile=None, extra=None):
    """(boards to fetch, manual boards to mention, unknown company names)."""
    allb = list(boards) + list(extra or [])
    by = {b["company"].lower(): b for b in allb}
    if companies:
        wanted = companies
    elif use_all:
        wanted = [b["company"] for b in allb]
    else:
        wanted = (profile or {}).get("dream_companies") or [b["company"] for b in allb]
    auto, manual, unknown = [], [], []
    for name in wanted:
        b = by.get(name.lower())
        if not b:
            unknown.append(name)
        elif b["type"] in AUTO:
            if b not in auto:
                auto.append(b)
        elif b not in manual:
            manual.append(b)
    return auto, manual, unknown


def parse_board_flag(text):
    """'Acme=greenhouse:acme' -> board dict."""
    m = re.match(r"\s*([^=]+)=(greenhouse|lever|ashby):([A-Za-z0-9_.\-]+)\s*$", text or "")
    if not m:
        raise ScoutError("--board wants Company=greenhouse|lever|ashby:token, got %r" % text)
    return {"company": m.group(1).strip(), "type": m.group(2), "token": m.group(3)}


def search(fetcher, boards, profile, today, roles=None, places=None, remote_only=False, days=None,
           min_score=0, limit=25, details=10, any_title=False, notes=None):
    notes = [] if notes is None else notes
    roles = roles or profile.get("target_roles") or []
    prof = dict(profile)
    prof["target_roles"] = roles
    if places:
        prof["locations"] = places
    scanned, kept, dropped = 0, [], {"title": 0, "excluded": 0, "place": 0, "age": 0, "score": 0}
    for b in boards:
        jobs = fetch_board(fetcher, b, today, roles, details=details, notes=notes,
                           exclude=profile.get("exclude_titles"))
        scanned += len(jobs)
        for j in jobs:
            if not any_title and title_points(j["title"], roles)[0] < 15:
                dropped["title"] += 1
                continue
            if excluded(j["title"], profile.get("exclude_titles")):
                dropped["excluded"] += 1
                continue
            if remote_only and not j["remote"]:
                dropped["place"] += 1
                continue
            if places and not j["remote"] and not place_match(j["location"], places):
                dropped["place"] += 1
                continue
            posted = parse_day(j.get("posted"))
            if days is not None and posted and (today - posted).days > days:
                dropped["age"] += 1
                continue
            s, why, warn = score(j, prof, today)
            if s < min_score:
                dropped["score"] += 1
                continue
            j["score"] = s
            j["why"] = "; ".join(why + ["note: " + w for w in warn])
            kept.append(j)
    kept.sort(key=lambda j: (-j["score"], j["company"].lower(), j["title"].lower()))
    seen, ranked = set(), []
    for j in kept:
        key = (j["company"].lower(), j["title"].lower(), j["location"].lower())
        if key in seen:
            continue
        seen.add(key)
        ranked.append(j)
    return {"scanned": scanned, "matched": len(ranked), "dropped": dropped, "jobs": ranked[:limit]}


def public(job):
    keep = ("id", "company", "title", "location", "url", "source", "posted", "score", "why", "remote", "pay")
    out = {k: job.get(k) for k in keep}
    if job.get("posted_note"):
        out["posted_note"] = job["posted_note"]
    return out


def render(result, manual, notes, today, out_path):
    lines = []
    jobs = result["jobs"]
    lines.append("Scanned %s listings on %d board%s on %s: %d match your titles and filters." % (
        "{:,}".format(result["scanned"]), result.get("boards", 0), "" if result.get("boards") == 1 else "s",
        today.isoformat(), result["matched"]))
    for i, j in enumerate(jobs, 1):
        lines.append("%2d. %3d  %s, %s  (%s)  %s" % (i, j["score"], j["company"], j["title"], j["location"],
                                                     j.get("posted_note") or j.get("posted") or "date unknown"))
        lines.append("         %s" % j["why"])
        lines.append("         %s   id: %s" % (j["url"], j["id"]))
    if not jobs:
        lines.append("No listing passed the filters. Widen --title, --location or --days, or add boards.")
    for b in manual:
        lines.append("Manual: %s. %s %s %s" % (b["company"], b.get("why_manual", ""), b.get("route", ""), b.get("careers", "")))
    for n in notes:
        lines.append("note: %s" % n)
    if out_path:
        lines.append("Saved to %s. Add the ones you want to the pipeline: jobs.py pick <id> ..." % out_path)
    lines.append("Fit scores rank listings against your profile; they are not a prediction of an offer.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- pipeline

def empty_pipeline():
    return {"roles": [], "contacts": [], "threads": []}


def pick(jobs_doc, ids, pipeline, today):
    """Add chosen jobs to pipeline roles (stage saved). Returns (added, skipped)."""
    for k in ("roles", "contacts", "threads"):
        pipeline.setdefault(k, [])
    by_id = {j["id"]: j for j in jobs_doc.get("jobs", [])}
    have_ids = {r.get("id") for r in pipeline["roles"]}
    have_urls = {r.get("url") for r in pipeline["roles"] if r.get("url")}
    added, skipped = [], []
    for i in ids:
        j = by_id.get(i)
        if not j:
            skipped.append("%s: not in jobs.json" % i)
            continue
        if j["id"] in have_ids or j["url"] in have_urls:
            skipped.append("%s: already in the pipeline" % i)
            continue
        pipeline["roles"].append({
            "id": j["id"], "company": j["company"], "title": j["title"], "url": j["url"],
            "stage": "saved", "applied": None,
            "next_step": "Research the company (/hunter-research) and tailor the resume (/hunter-resume)",
            "next_date": today.isoformat(),
            "notes": "%s: Scout fit %s: %s" % (today.isoformat(), j.get("score"), j.get("why", "")),
        })
        have_ids.add(j["id"])
        added.append(j["id"])
    return added, skipped


# ---------------------------------------------------------------- check

def check_board(fetcher, b):
    """One small live call that proves the token resolves. Returns a line."""
    kind, token = b["type"], b.get("token")
    if kind == "greenhouse":
        d = fetcher.get(GH_BOARD % token, "greenhouse-board-%s.json" % token)
        return "ok  greenhouse %-12s board name: %s" % (token, d.get("name"))
    if kind == "lever":
        d = fetcher.get(LEVER % token + "&limit=1", "lever-%s.json" % token)
        return "ok  lever %-12s %s" % (token, "has postings" if d else "EMPTY (no open postings or wrong token)")
    if kind == "ashby":
        d = fetcher.get(ASHBY % token, "ashby-%s.json" % token)
        return "ok  ashby %-12s %d postings" % (token, len(d.get("jobs", [])))
    if kind == "workday":
        d = fetcher.get(WORKDAY % (b["host"], b["tenant"], b["site"]), "workday-%s.json" % token,
                        {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        return "ok  workday %-12s %s postings" % (token, d.get("total"))
    if kind == "eightfold":
        d = fetcher.get(EIGHTFOLD % (b["host"], b["domain"], "", 0, 1), "eightfold-%s.json" % token)
        return "ok  eightfold %-10s %s postings" % (token, d.get("count"))
    return "manual %s: %s" % (b["company"], b.get("careers"))


# ---------------------------------------------------------------- CLI

def _today(value):
    return parse_day(value) if value else _dt.date.today()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Job Scout: public job boards ranked by fit to hunter/profile.json.")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("search", help="fetch, filter, score, write hunter/jobs.json")
    s.add_argument("--profile", default="hunter/profile.json")
    s.add_argument("--boards", default=BOARDS)
    s.add_argument("--board", action="append", default=[], help="extra board: 'Company=greenhouse:token'")
    s.add_argument("--company", action="append", default=[], help="only these companies (repeat)")
    s.add_argument("--all", action="store_true", help="every automatic board in boards.json")
    s.add_argument("--title", action="append", default=[], help="target titles (default: profile target_roles)")
    s.add_argument("--any-title", action="store_true", help="keep every title, just score it")
    s.add_argument("--location", action="append", default=[], help="keep these places (plus remote)")
    s.add_argument("--remote", action="store_true", help="remote roles only")
    s.add_argument("--days", type=int, help="posted within N days")
    s.add_argument("--min-score", type=int, default=0)
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--details", type=int, default=10, help="Greenhouse descriptions fetched per board")
    s.add_argument("--today", help="YYYY-MM-DD (default: today)")
    s.add_argument("--out", default="hunter/jobs.json")
    s.add_argument("--offline", metavar="DIR")
    s.add_argument("--json", action="store_true")

    p = sub.add_parser("pick", help="add listings from jobs.json to hunter/pipeline.json")
    p.add_argument("ids", nargs="+")
    p.add_argument("--jobs", default="hunter/jobs.json")
    p.add_argument("--pipeline", default="hunter/pipeline.json")
    p.add_argument("--today")

    b = sub.add_parser("boards", help="list bundled boards: automatic or manual, and why")
    b.add_argument("--boards", default=BOARDS)

    c = sub.add_parser("check", help="verify board tokens live (one small call each)")
    c.add_argument("--boards", default=BOARDS)
    c.add_argument("--company", action="append", default=[])
    c.add_argument("--board", action="append", default=[])
    c.add_argument("--offline", metavar="DIR")

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 2

    if args.cmd == "pick":
        jobs_doc = load_json(args.jobs)
        if not jobs_doc:
            print("pick: no %s yet. Run `jobs.py search` first." % args.jobs, file=sys.stderr)
            return 2
        pipeline = load_json(args.pipeline) or empty_pipeline()
        added, skipped = pick(jobs_doc, args.ids, pipeline, _today(args.today))
        if added:
            save_json(args.pipeline, pipeline)
        for a in added:
            print("added %s (stage: saved)" % a)
        for s_ in skipped:
            print("skipped %s" % s_)
        return 0 if added else 1

    doc = load_json(args.boards, {"boards": []})
    if args.cmd == "boards":
        for bd in doc["boards"]:
            if bd["type"] in AUTO:
                print("auto    %-11s %-10s %s" % (bd["company"], bd["type"], bd.get("token")))
            else:
                print("manual  %-11s %s" % (bd["company"], bd.get("careers")))
                print("        why: %s" % bd.get("why_manual"))
                print("        route: %s" % bd.get("route"))
        print("Verified %s. Re-check any time with `jobs.py check`." % doc.get("verified"))
        return 0

    try:
        extra = [parse_board_flag(x) for x in args.board]
    except ScoutError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2

    if args.cmd == "check":
        auto, manual, unknown = pick_boards(doc["boards"], args.company or None, not args.company, None, extra)
        if extra and not args.company:
            auto = [x for x in auto if x in extra] or auto
        fetcher = Fetcher(offline=args.offline, pause=1.0)
        bad = 0
        for bd in auto:
            try:
                print(check_board(fetcher, bd))
            except ScoutError as exc:
                bad += 1
                print("FAIL %s %s %s: %s" % (bd["company"], bd["type"], bd.get("token"), exc))
        for bd in manual:
            print("manual %s: no feed to check, search %s" % (bd["company"], bd.get("careers")))
        for name in unknown:
            print("unknown company %s: add it with --board 'Name=greenhouse:token'" % name)
        return 1 if bad or unknown else 0

    profile = load_json(args.profile)
    if profile is None:
        print("search: no %s. Copy skills/hunter-apply/profile.example.json to hunter/profile.json and "
              "fill in your own details first." % args.profile, file=sys.stderr)
        return 2
    today = _today(args.today)
    auto, manual, unknown = pick_boards(doc["boards"], args.company or None, args.all, profile, extra)
    if extra and not args.company:
        auto += [x for x in extra if x not in auto]
    notes = ["%s is not in boards.json: add it with --board 'Name=greenhouse:token' (or lever/ashby)" % u
             for u in unknown]
    fetcher = Fetcher(offline=args.offline)
    result = search(fetcher, auto, profile, today, roles=args.title or None, places=args.location or None,
                    remote_only=args.remote, days=args.days, min_score=args.min_score, limit=args.limit,
                    details=args.details, any_title=args.any_title, notes=notes)
    result["boards"] = len(auto)
    out = {
        "as_of": today.isoformat(),
        "scanned": result["scanned"],
        "matched": result["matched"],
        "boards": [b_["company"] for b_ in auto],
        "manual": [{"company": m["company"], "careers": m.get("careers"), "route": m.get("route")} for m in manual],
        "jobs": [public(j) for j in result["jobs"]],
    }
    if args.out:
        save_json(args.out, out)
    if args.json:
        print(json.dumps(dict(out, notes=notes), indent=2))
    else:
        sys.stdout.write(render(dict(result, jobs=out["jobs"]), manual, notes, today, args.out))
    return 0 if out["jobs"] else 1


if __name__ == "__main__":
    sys.exit(main())
