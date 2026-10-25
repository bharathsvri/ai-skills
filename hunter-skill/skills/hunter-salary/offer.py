#!/usr/bin/env python3
"""Offers in plain numbers, benchmarks with their sources, and a counter you can say out loud.
Standard library only.

    python3 offer.py total   hunter/offers/google.json
    python3 offer.py compare hunter/offers/google.json hunter/offers/amazon.json
    python3 offer.py bls --soc 15-1252 --area msa:41940 --out hunter/offers/bench.json
    python3 offer.py bench   hunter/offers/google.json --bench hunter/offers/bench.json
    python3 offer.py counter hunter/offers/google.json --bench hunter/offers/bench.json \
        --competing hunter/offers/amazon.json --floor 180000 --me "Jordan Reyes"

TOTAL COMPENSATION, year by year (years = the vesting schedule's length, 4 by default)

    base     base x (1 + raise_pct)^(year - 1)      raise_pct defaults to 0: no raise is assumed
    bonus    base x bonus_target_pct, or a fixed "bonus"; a TARGET, not a promise
    equity   grant value x the schedule's percent for that year (at the grant's value:
             the stock can go up or down). Schedules: even-4 (25/25/25/25), back-loaded
             (5/15/40/40), front-loaded (33/33/22/12), even-3, or your own list from the offer letter
    sign-on  "sign_on": a number (paid in year 1) or a list per year ([45000, 35000])
    TC       base + bonus + equity + sign-on. One-time items in "other" (relocation) are shown apart.

BENCHMARKS come only from sources you can cite: the BLS Occupational Employment and Wage
Statistics (OEWS) via the bls command, a pay range printed in a job posting (with its URL),
or an offer you really hold. A benchmark without a source is refused. Nothing here makes up
a market number. OEWS wages leave out stock grants and non-production bonuses: compare them
with BASE salary only. OEWS covers every employer and experience level for that occupation and
area: it is a broad benchmark, not a quote for one company or level.

THE COUNTER (stated rule, not a prediction)

    evidence  cited numbers above your base: OEWS median and 75th percentile for your area,
              the top of a posted range, a competing offer's base
    ask       the highest evidence, capped at your base x (1 + max_bump) (15% by default),
              except a real competing base, which is never capped; never above a posted
              range's top (ask for the rest as sign-on); rounded up to the next 1,000
    middle    halfway between the offer and the ask: a result you would be glad to take
    floor     YOUR walk-away number (--floor or profile salary_floor). The tool never picks it.
A counter can be declined. No outcome is guaranteed. Not financial, tax or legal advice.
"""

import argparse
import json
import math
import os
import sys
import urllib.request

BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
UA = "hunter-skill/1.0 (+https://github.com/Jakeschincariol/hunter-skill)"
SCHEDULES = {
    "even-4": [25, 25, 25, 25],
    "back-loaded": [5, 15, 40, 40],
    "back-loaded-5-15-40-40": [5, 15, 40, 40],
    "front-loaded": [33, 33, 22, 12],
    "front-loaded-33-33-22-12": [33, 33, 22, 12],
    "even-3": [100 / 3.0, 100 / 3.0, 100 / 3.0],
    "even-5": [20, 20, 20, 20, 20],
}
DATATYPES = {"mean": "04", "p10": "11", "p25": "12", "p50": "13", "p75": "14", "p90": "15"}
SOC_NAMES = {
    "15-1252": "Software Developers",
    "15-1253": "Software Quality Assurance Analysts and Testers",
    "15-2051": "Data Scientists",
    "15-1211": "Computer Systems Analysts",
    "15-1212": "Information Security Analysts",
    "15-1244": "Network and Computer Systems Administrators",
    "11-3021": "Computer and Information Systems Managers",
}
AREA_NAMES = {"N0000000": "United States (national)", "M0041940": "San Jose-Sunnyvale-Santa Clara, CA"}
STATE_FIPS = {
    "AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10", "DC": "11",
    "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19", "KS": "20", "KY": "21",
    "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27", "MS": "28", "MO": "29", "MT": "30",
    "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35", "NY": "36", "NC": "37", "ND": "38", "OH": "39",
    "OK": "40", "OR": "41", "PA": "42", "RI": "44", "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49",
    "VT": "50", "VA": "51", "WA": "53", "WV": "54", "WI": "55", "WY": "56", "PR": "72",
}
MARKET_KINDS = ("base", "total", "posting_range")
MAX_BUMP = 0.15


class OfferError(Exception):
    pass


# ---------------------------------------------------------------- money

def money(v, cur="USD"):
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    s = "{:,.0f}".format(abs(v))
    return "%s$%s" % (sign, s) if cur in ("USD", "CAD", "AUD", "$") else "%s%s %s" % (sign, s, cur)


def round_up(v, step=1000):
    return int(math.ceil(v / float(step)) * step)


def read_json(path):
    if not path or not os.path.exists(path):
        raise OfferError("no file at %s" % path)
    with open(path, encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except json.JSONDecodeError as e:
            raise OfferError("%s is not valid JSON: %s" % (path, e))


# ---------------------------------------------------------------- an offer

def schedule(eq):
    v = (eq or {}).get("vesting", "even-4")
    if isinstance(v, str):
        if v not in SCHEDULES:
            raise OfferError("unknown vesting %r (use %s, or a list of yearly percents)" % (v, ", ".join(sorted(SCHEDULES))))
        return list(SCHEDULES[v])
    if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) and x >= 0 for x in v):
        raise OfferError("vesting must be a name or a list of yearly percents")
    if abs(sum(v) - 100) > 0.5:
        raise OfferError("vesting percents add up to %.1f, not 100" % sum(v))
    return [float(x) for x in v]


def grant_value(eq):
    if not eq:
        return 0.0
    if eq.get("grant_value") is not None:
        return float(eq["grant_value"])
    if eq.get("shares") is not None and eq.get("share_price") is not None:
        return float(eq["shares"]) * float(eq["share_price"])
    if eq.get("shares") is not None:
        raise OfferError("equity has shares but no share_price: ask the recruiter for the value or the price used")
    return 0.0


def yearly(offer):
    """Year-by-year compensation for one offer."""
    if offer.get("base") is None:
        raise OfferError("the offer needs a base salary")
    base0 = float(offer["base"])
    raise_pct = float(offer.get("raise_pct", 0) or 0)
    eq = offer.get("equity") or {}
    sched = schedule(eq) if eq else [25, 25, 25, 25]
    years = len(sched)
    grant = grant_value(eq)
    so = offer.get("sign_on", 0) or 0
    so_list = [float(x) for x in so] if isinstance(so, list) else [float(so)]
    rows = []
    for y in range(1, years + 1):
        base = base0 * (1 + raise_pct / 100.0) ** (y - 1)
        if offer.get("bonus") is not None:
            bonus = float(offer["bonus"])
        else:
            bonus = base * float(offer.get("bonus_target_pct", 0) or 0) / 100.0
        equity = grant * sched[y - 1] / 100.0
        sign_on = so_list[y - 1] if y - 1 < len(so_list) else 0.0
        rows.append({"year": y, "base": base, "bonus": bonus, "equity": equity, "sign_on": sign_on,
                     "tc": base + bonus + equity + sign_on})
    other = sum(float(v) for v in (offer.get("other") or {}).values() if isinstance(v, (int, float)))
    total = sum(r["tc"] for r in rows)
    return {"company": offer.get("company", "?"), "title": offer.get("title", ""), "currency": offer.get("currency", "USD"),
            "years": rows, "total": total, "average": total / len(rows), "grant": grant,
            "schedule": sched, "cliff_months": eq.get("cliff_months"), "one_time": other}


def render_total(t):
    cur = t["currency"]
    out = ["%s, %s: %s over %d years (average %s a year)" % (
        t["company"], t["title"], money(t["total"], cur), len(t["years"]), money(t["average"], cur))]
    out.append("  year        base       bonus      equity     sign-on          TC")
    for r in t["years"]:
        out.append("  %4d  %10s  %10s  %10s  %10s  %10s" % (
            r["year"], money(r["base"], cur), money(r["bonus"], cur), money(r["equity"], cur),
            money(r["sign_on"], cur), money(r["tc"], cur)))
    sched = "/".join(("%g" % round(x, 1)) for x in t["schedule"])
    out.append("  equity: %s granted, vesting %s%s" % (money(t["grant"], cur), sched,
               (", %d-month cliff (leave before it and the equity is gone)" % t["cliff_months"]) if t.get("cliff_months") else ""))
    if t["one_time"]:
        out.append("  one-time (not in TC): %s" % money(t["one_time"], cur))
    out.append("  bonus is a target, equity is valued at grant; neither is guaranteed")
    return "\n".join(out)


def render_compare(ts):
    cur = ts[0]["currency"]
    width = max(len(t["company"]) for t in ts) + 2
    out = ["Total compensation by year (TC = base + bonus + equity + sign-on)"]
    out.append("  " + "year".ljust(8) + "".join(t["company"].rjust(max(width, 12)) for t in ts))
    years = max(len(t["years"]) for t in ts)
    for y in range(years):
        row = "  " + ("%d" % (y + 1)).ljust(8)
        for t in ts:
            v = t["years"][y]["tc"] if y < len(t["years"]) else None
            row += money(v, cur).rjust(max(width, 12))
        out.append(row)
    out.append("  " + "total".ljust(8) + "".join(money(t["total"], cur).rjust(max(width, 12)) for t in ts))
    best1 = max(ts, key=lambda t: t["years"][0]["tc"])
    bestall = max(ts, key=lambda t: t["total"])
    out.append("")
    out.append("Highest in year 1: %s. Highest over the full schedule: %s." % (best1["company"], bestall["company"]))
    for t in ts:
        first, last = t["years"][0]["tc"], t["years"][-1]["tc"]
        if abs(last - first) > 0.10 * max(first, 1):
            out.append("  %s changes a lot by year: %s in year 1, %s in year %d (vesting %s, sign-on %s)." % (
                t["company"], money(first, cur), money(last, cur), len(t["years"]),
                "/".join("%g" % round(x, 1) for x in t["schedule"]),
                "/".join(money(r["sign_on"], cur) for r in t["years"] if r["sign_on"]) or "none"))
    return "\n".join(out)


# ---------------------------------------------------------------- benchmarks

def load_bench(paths):
    items = []
    for p in paths or []:
        data = read_json(p)
        items += data.get("benchmarks", data if isinstance(data, list) else [])
    for b in items:
        if not b.get("source"):
            raise OfferError("benchmark %r has no source: every number needs one (never invent a market number)" % b.get("label"))
        if b.get("kind") in MARKET_KINDS and not b.get("url"):
            raise OfferError("benchmark %r needs the URL it came from" % b.get("label"))
        if b.get("kind") not in MARKET_KINDS:
            raise OfferError("benchmark kind must be one of %s, got %r" % (", ".join(MARKET_KINDS), b.get("kind")))
    return items


def position(value, b):
    """Where a value sits against one benchmark, in words."""
    if b["kind"] == "posting_range":
        lo, hi = b.get("min"), b.get("max")
        if lo is None or hi is None:
            return "range incomplete"
        if value < lo:
            return "below the posted range"
        if value > hi:
            return "above the posted range"
        return "%d%% of the way up the posted range" % round(100 * (value - lo) / float(hi - lo or 1))
    marks = [(k, b.get(k)) for k in ("p10", "p25", "p50", "p75", "p90") if b.get(k) is not None]
    if not marks:
        return "no percentiles"
    below = [k for k, v in marks if value >= v]
    if not below:
        return "below the 10th percentile" if marks[0][0] == "p10" else "below the lowest percentile given"
    top = below[-1]
    names = {"p10": "10th", "p25": "25th", "p50": "median", "p75": "75th", "p90": "90th"}
    if top == "p90":
        return "above the 90th percentile"
    nxt = marks[[k for k, _ in marks].index(top) + 1][0]
    return "between the %s and the %s" % (names[top], names[nxt] + ("" if nxt == "p50" else " percentile"))


def render_bench(offer, benches):
    cur = offer.get("currency", "USD")
    base = float(offer["base"])
    out = ["%s base %s against cited benchmarks:" % (offer.get("company", "Offer"), money(base, cur))]
    if not benches:
        out.append("  none given. Run: offer.py bls --soc 15-1252 --area msa:41940 --out bench.json, or add a posted range with its URL.")
    for b in benches:
        nums = ", ".join("%s %s" % (k, money(b[k], cur)) for k in ("p10", "p25", "p50", "p75", "p90", "mean", "min", "max")
                         if b.get(k) is not None)
        out.append("  %s\n    %s\n    your base is %s\n    source: %s (%s)" % (b.get("label"), nums, position(base, b),
                                                                             b["source"], b["url"]))
    return "\n".join(out)


# ---------------------------------------------------------------- BLS OEWS

def area_code(area):
    a = (area or "national").strip()
    if a.lower() in ("national", "us", "usa", "n"):
        return "N0000000"
    if ":" in a:
        kind, val = a.split(":", 1)
        kind = kind.lower()
        if kind == "msa":
            if not val.isdigit() or len(val) != 5:
                raise OfferError("msa: needs the 5-digit metro code (CBSA), e.g. msa:41940")
            return "M00" + val
        if kind == "state":
            fips = STATE_FIPS.get(val.upper(), val if val.isdigit() and len(val) == 2 else None)
            if not fips:
                raise OfferError("state: needs a 2-letter state or a 2-digit FIPS code")
            return "S" + fips + "00000"
    raise OfferError("--area must be national, state:XX or msa:NNNNN")


def series_ids(soc, area):
    occ = soc.replace("-", "")
    if not occ.isdigit() or len(occ) != 6:
        raise OfferError("--soc must look like 15-1252")
    a = area_code(area)
    return {k: "OEU" + a + "000000" + occ + dt for k, dt in DATATYPES.items()}


def fetch_bls(ids, year, key=None):
    body = {"seriesid": list(ids), "startyear": str(year), "endyear": str(year)}
    if key:
        body["registrationkey"] = key
    req = urllib.request.Request(BLS_API, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def bls_benchmark(resp, soc, area, year, occupation=None, area_name=None):
    if resp.get("status") != "REQUEST_SUCCEEDED":
        raise OfferError("BLS answered %s: %s" % (resp.get("status"), "; ".join(resp.get("message") or [])))
    ids = series_ids(soc, area)
    by_id = {s.get("seriesID"): s for s in (resp.get("Results") or {}).get("series", [])}
    vals, missing = {}, []
    used_year = None
    for k, sid in ids.items():
        s = by_id.get(sid)
        pts = [d for d in (s or {}).get("data", []) if str(d.get("year")) == str(year)] if s else []
        if not pts:
            missing.append(k)
            continue
        raw = str(pts[0].get("value", "")).replace(",", "")
        try:
            vals[k] = float(raw)
            used_year = pts[0].get("year")
        except ValueError:
            missing.append(k)  # BLS prints "-" or "*" when a value is top-coded or not released
    if not vals:
        raise OfferError("BLS has no %s OEWS wages for %s in %s (check the codes, or try the year before)" % (year, soc, area))
    a = area_code(area)
    occ_name = occupation or SOC_NAMES.get(soc, "SOC " + soc)
    if a.startswith("S") and ":" in (area or ""):
        state = area.split(":", 1)[1].upper()
        guess = state if state.isalpha() else "FIPS " + state
        place = area_name or "the state of %s" % guess
    else:
        place = area_name or AREA_NAMES.get(a) or ("MSA " + a[3:])
    out = {"label": "BLS OEWS May %s, %s (SOC %s), %s" % (used_year, occ_name, soc, place),
           "kind": "base",
           "source": "U.S. Bureau of Labor Statistics, Occupational Employment and Wage Statistics (OEWS), May %s estimates, BLS Public Data API" % used_year,
           "url": BLS_API + ids["p50"],
           "as_of": "May %s" % used_year,
           "series": ids,
           "occupation": occ_name,
           "area": place,
           "cite": "BLS wage data (OEWS, May %s)" % used_year,
           "note": "Annual wages for every employer and experience level in this occupation and area. They leave out stock grants and non-production bonuses: compare with base salary only."}
    for k in ("p10", "p25", "p50", "p75", "p90", "mean"):
        if k in vals:
            out[k] = vals[k]
    if missing:
        out["missing"] = missing
    return out


# ---------------------------------------------------------------- the counter

def counter(offer, benches, competing=None, floor=None, max_bump=MAX_BUMP):
    base = float(offer["base"])
    t = yearly(offer)
    evidence = []
    for b in benches:
        if b["kind"] == "base":
            for k, name in (("p50", "median"), ("p75", "75th percentile")):
                if b.get(k) is not None and b[k] > base:
                    evidence.append({"value": float(b[k]), "why": "%s %s" % (b.get("label"), name), "kind": "bench", "bench": b, "stat": name})
        if b["kind"] == "posting_range" and b.get("max") is not None and b["max"] > base:
            evidence.append({"value": float(b["max"]), "why": "top of the posted range (%s)" % b.get("label"), "kind": "posting", "bench": b})
    comp_t = None
    if competing:
        comp_t = yearly(competing)
        if float(competing["base"]) > base:
            evidence.append({"value": float(competing["base"]), "why": "%s's base offer" % competing.get("company", "the other"),
                             "kind": "competing"})
    cap_posting = min([float(b["max"]) for b in benches if b["kind"] == "posting_range" and b.get("max") is not None] or [None]) \
        if any(b["kind"] == "posting_range" and b.get("max") is not None for b in benches) else None
    ask = None
    capped_by = None
    if evidence:
        top = max(evidence, key=lambda e: e["value"])
        ask = top["value"]
        if top["kind"] != "competing" and ask > base * (1 + max_bump):
            ask = base * (1 + max_bump)
            capped_by = "the %d%% cap on a base ask (change with --max-bump)" % round(max_bump * 100)
        if cap_posting is not None and ask > cap_posting:
            ask = cap_posting
            capped_by = "the top of the posted range"
        ask = float(round_up(ask))
        if cap_posting is not None and ask > cap_posting:
            ask = cap_posting
    middle = float(round_up((base + ask) / 2.0)) if ask else None
    sign_on_ask = None
    if comp_t and comp_t["years"][0]["tc"] > t["years"][0]["tc"]:
        sign_on_ask = float(round_up(comp_t["years"][0]["tc"] - t["years"][0]["tc"]))
    gaps = None
    if comp_t:
        gaps = {"year1": comp_t["years"][0]["tc"] - t["years"][0]["tc"], "total": comp_t["total"] - t["total"]}
    support = sorted([e for e in evidence if ask and e["value"] <= ask + 0.5] or evidence, key=lambda e: -e["value"])[:2]
    return {"base": base, "ask": ask, "middle": middle, "floor": floor, "below_floor": floor is not None and base < floor,
            "capped_by": capped_by, "evidence": evidence, "support": support, "sign_on_ask": sign_on_ask,
            "gaps": gaps, "offer": t, "competing": comp_t}


def script(c, offer, me=None, recruiter=None, share_competing=False):
    cur = offer.get("currency", "USD")
    first = (me or "").split()[0] if me else "[your name]"
    hello = "Hi %s," % recruiter if recruiter else "Hi [recruiter's first name],"
    title = offer.get("title") or "the role"
    lines = [hello, "",
             "Thank you for the offer for the %s role at %s. I am excited about the team and I want to make this work." % (
                 title, offer.get("company", "the company"))]
    if c["ask"]:
        cites = []
        by_bench = []
        for e in sorted(c["support"], key=lambda e: e["value"]):
            if e["kind"] == "competing":
                if share_competing:
                    cites.append("I also have an offer with a base of %s" % money(e["value"], cur))
            elif e["kind"] == "posting":
                cites.append("the posted range for this role goes up to %s" % money(e["value"], cur))
            else:
                hit = next((x for x in by_bench if x[0] is e["bench"]), None)
                if hit is None:
                    hit = (e["bench"], [])
                    by_bench.append(hit)
                hit[1].append("the %s at %s" % (e["stat"], money(e["value"], cur)))
        for b, stats in by_bench:
            who = ("%s in the %s area" % (b["occupation"].lower(), b["area"])) if b.get("occupation") and b.get("area") \
                else (b.get("label") or "this role")
            cites.insert(0, "%s for %s puts %s" % (b.get("cite") or b["source"], who, " and ".join(stats)))
        reason = ("%s, so " % "; ".join(cites)) if cites else ""
        lines += ["", "%sI would like to ask for a base salary of %s." % (reason[0].upper() + reason[1:] if reason else "", money(c["ask"], cur))]
        if c["capped_by"] == "the top of the posted range":
            lines.append("If base is fixed at the top of the range, a sign-on bonus would help close the gap.")
    else:
        lines += ["", "Is there any flexibility on base salary or a sign-on bonus?"]
    if c["sign_on_ask"] and share_competing:
        lines.append("My other offer is %s higher in the first year, so a sign-on bonus of %s would close that gap." % (
            money(c["gaps"]["year1"], cur), money(c["sign_on_ask"], cur)))
    lines += ["", "Is there flexibility there? If we can get closer, I am ready to move quickly.", "", "Thank you,", first]
    return "\n".join(lines)


def render_counter(c, offer, me=None, recruiter=None, share_competing=False):
    cur = offer.get("currency", "USD")
    out = ["Counter for %s, %s (base %s)" % (offer.get("company"), offer.get("title", ""), money(c["base"], cur))]
    if c["below_floor"]:
        out.append("  WARNING: the base is below your floor of %s." % money(c["floor"], cur))
    if c["evidence"]:
        out.append("  Evidence above your base:")
        for e in sorted(c["evidence"], key=lambda e: -e["value"]):
            out.append("    %s  %s" % (money(e["value"], cur).rjust(10), e["why"]))
    else:
        out.append("  No cited number is above your base. Ask about flexibility, sign-on or equity, without a number.")
    if c["ask"]:
        out.append("  Ask:    %s%s" % (money(c["ask"], cur), ("  (capped by %s)" % c["capped_by"]) if c["capped_by"] else ""))
        out.append("  Middle: %s  (a result you would be glad to take)" % money(c["middle"], cur))
    out.append("  Floor:  %s" % (money(c["floor"], cur) if c["floor"] is not None else "yours to set (--floor); the tool never picks it"))
    if c["gaps"]:
        out.append("  Against %s: year 1 %s, full schedule %s (positive = the other offer is higher)." % (
            c["competing"]["company"], money(c["gaps"]["year1"], cur), money(c["gaps"]["total"], cur)))
    out.append("")
    out.append("Script (a DRAFT: you send it, from your own email, after you approve it):")
    out.append("")
    out.append(script(c, offer, me, recruiter, share_competing))
    out.append("")
    out.append("No outcome is guaranteed. Not financial, tax or legal advice.")
    return "\n".join(out)


# ---------------------------------------------------------------- CLI

def profile_floor(path):
    if path and os.path.exists(path):
        try:
            p = read_json(path)
            v = p.get("salary_floor")
            if isinstance(v, dict):
                v = v.get("base") or v.get("amount")
            return float(v) if v is not None else None
        except (OfferError, ValueError, TypeError):
            return None
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description="Offers, cited benchmarks and a counter script.")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("total", help="year-by-year total compensation for one offer")
    sp.add_argument("offer")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("compare", help="two or more offers side by side")
    sp.add_argument("offers", nargs="+")
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("bls", help="OEWS wage percentiles from the BLS API (or --offline FILE)")
    sp.add_argument("--soc", required=True, help="occupation code, e.g. 15-1252 (Software Developers)")
    sp.add_argument("--area", default="national", help="national, state:CA or msa:41940")
    sp.add_argument("--year", type=int, default=2025, help="OEWS reference year (May of that year)")
    sp.add_argument("--occupation", help="name for the label")
    sp.add_argument("--area-name", help="name for the label")
    sp.add_argument("--offline", help="a saved BLS API response (JSON) instead of the network")
    sp.add_argument("--out", help="add the benchmark to this bench file")
    sp = sub.add_parser("bench", help="where the base sits against cited benchmarks")
    sp.add_argument("offer")
    sp.add_argument("--bench", action="append", default=[])
    sp = sub.add_parser("counter", help="the counter range and a script")
    sp.add_argument("offer")
    sp.add_argument("--bench", action="append", default=[])
    sp.add_argument("--competing")
    sp.add_argument("--floor", type=float)
    sp.add_argument("--profile", default=os.path.join("hunter", "profile.json"))
    sp.add_argument("--max-bump", type=float, default=MAX_BUMP, help="cap on a base ask as a fraction (default 0.15)")
    sp.add_argument("--me")
    sp.add_argument("--recruiter")
    sp.add_argument("--share-competing", action="store_true", help="name the competing offer in the script (only if it is real and you are fine sharing it)")
    sp.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    try:
        if a.cmd == "total":
            t = yearly(read_json(a.offer))
            print(json.dumps(t, indent=2) if a.json else render_total(t))
            return 0
        if a.cmd == "compare":
            ts = [yearly(read_json(x)) for x in a.offers]
            print(json.dumps(ts, indent=2) if a.json else render_compare(ts))
            return 0
        if a.cmd == "bls":
            ids = series_ids(a.soc, a.area)
            if a.offline:
                resp = read_json(a.offline)
            else:
                resp = fetch_bls(ids.values(), a.year, os.environ.get("BLS_API_KEY"))
            b = bls_benchmark(resp, a.soc, a.area, a.year, a.occupation, a.area_name)
            if a.out:
                data = read_json(a.out) if os.path.exists(a.out) else {"benchmarks": []}
                data["benchmarks"] = [x for x in data.get("benchmarks", []) if x.get("label") != b["label"]] + [b]
                d = os.path.dirname(a.out)
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(a.out, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2)
                    fh.write("\n")
                print("Added to %s: %s" % (a.out, b["label"]))
            print(json.dumps(b, indent=2))
            return 0
        offer = read_json(a.offer)
        benches = load_bench(a.bench)
        if a.cmd == "bench":
            print(render_bench(offer, benches))
            return 0
        if a.cmd == "counter":
            floor = a.floor if a.floor is not None else profile_floor(a.profile)
            comp = read_json(a.competing) if a.competing else None
            c = counter(offer, benches, comp, floor, a.max_bump)
            if a.json:
                slim = {k: v for k, v in c.items() if k not in ("offer", "competing")}
                for e in slim["evidence"] + slim["support"]:
                    e.pop("bench", None)
                slim["script"] = script(c, offer, a.me, a.recruiter, a.share_competing)
                print(json.dumps(slim, indent=2))
            else:
                print(render_counter(c, offer, a.me, a.recruiter, a.share_competing))
            return 0
    except (OfferError, OSError) as e:
        print("offer: " + str(e), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
