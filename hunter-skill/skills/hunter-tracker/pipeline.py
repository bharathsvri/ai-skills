#!/usr/bin/env python3
"""The hunter pipeline: every role, contact and conversation in one file. Standard library only.

hunter/pipeline.json is the single source of truth the other hunter skills read and
write. This tool owns its schema and checks it:

  {"roles":    [{"id", "company", "title", "url", "stage", "applied",
                 "next_step", "next_date", "notes"}],
   "contacts": [{"id", "name", "role", "company", "linkedin", "email",
                 "email_confidence", "source", "notes"}],
   "threads":  [{"contact_id", "role_id", "channel",
                 "messages": [{"date", "direction": "out|in", "text"}],
                 "status", "next_followup"}]}

  optional:        thread invite / draft / approval / booked and contact do_not_contact,
                   kept by hunter-connector (see THREAD_OPTIONAL below)
  role stages:     saved, applied, screen, interview, onsite, offer, rejected, withdrawn
  thread statuses: drafted, sent, replied, booked, declined, closed
  dates:           YYYY-MM-DD (a message date may carry a time: 2026-10-12T09:30)

Commands:

    python3 pipeline.py init
    python3 pipeline.py validate
    python3 pipeline.py add-role --company Google --title "Software Engineer" --url URL
    python3 pipeline.py update-role google-software-engineer --next-step "Coffee chat" --next-date 2026-10-22
    python3 pipeline.py move google-software-engineer applied --today 2026-10-23
    python3 pipeline.py add-contact --name "Maya C." --company Google --role "Engineering Manager"
    python3 pipeline.py update-contact maya-c-google --notes "Michigan alum"
    python3 pipeline.py summary --today 2026-10-16
    python3 pipeline.py stale --today 2026-10-16 --days 14
    python3 pipeline.py next --today 2026-10-16 --days 7
    python3 pipeline.py show google-software-engineer
    python3 pipeline.py export --what roles --out hunter/pipeline-roles.csv

Every command takes --file (default hunter/pipeline.json). Commands that depend on
the date take --today YYYY-MM-DD (default: the computer's date), so results are
reproducible. Nothing here sends anything: it is a record.
"""

import argparse
import csv
import datetime
import io
import json
import os
import re
import sys

DEFAULT_FILE = os.path.join("hunter", "pipeline.json")

STAGES = ("saved", "applied", "screen", "interview", "onsite", "offer", "rejected", "withdrawn")
ACTIVE = ("saved", "applied", "screen", "interview", "onsite", "offer")
CLOSED = ("rejected", "withdrawn")
THREAD_STATUSES = ("drafted", "sent", "replied", "booked", "declined", "closed")
CHANNELS = ("email", "linkedin", "phone", "in-person", "other")
DIRECTIONS = ("out", "in")

ROLE_FIELDS = ("id", "company", "title", "url", "stage", "applied", "next_step", "next_date", "notes")
CONTACT_FIELDS = ("id", "name", "role", "company", "linkedin", "email", "email_confidence", "source", "notes")
THREAD_FIELDS = ("contact_id", "role_id", "channel", "messages", "status", "next_followup")
MESSAGE_FIELDS = ("date", "direction", "text")
# Optional fields that hunter-connector keeps (part of the schema, not extras):
#   thread.invite  true while a LinkedIn invitation is pending (it gets no follow-up)
#   thread.draft   {"kind", "subject", "text", "created", "hash"}: a message waiting for the user's yes
#   thread.approval {"reply", "date", "hash"}: the user's yes, word for word, for that exact draft
#   thread.booked  {"when", "minutes", "where", ...}: the coffee chat once it is booked
#   contact.do_not_contact  true after a stop request: never contacted again, on any channel
THREAD_OPTIONAL = ("invite", "draft", "approval", "booked")
CONTACT_OPTIONAL = ("do_not_contact",)

# How sure we are of an email address. "published" means it was found on a public page
# (the source must be that page's URL). Everything else is a guess from public patterns.
CONFIDENCE_WORDS = ("published", "high", "medium", "low", "unknown")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
NOTE_DATE_RE = re.compile(r"(?m)^(\d{4}-\d{2}-\d{2}):")


class PipelineError(Exception):
    pass


# ---------------------------------------------------------------- dates

def parse_day(s, what="date"):
    if isinstance(s, datetime.date):
        return s
    m = STAMP_RE.match(str(s or "").strip())
    if not m:
        raise PipelineError("%s must be YYYY-MM-DD, got %r" % (what, s))
    try:
        return datetime.date(*[int(x) for x in m.group(1).split("-")])
    except ValueError:
        raise PipelineError("%s is not a real date: %r" % (what, s))


def day_or_none(s):
    """A date from a field, or None when the field is empty or not a date."""
    if s in (None, ""):
        return None
    try:
        return parse_day(s)
    except PipelineError:
        return None


def today_from(arg):
    return parse_day(arg, "--today") if arg else datetime.date.today()


# ---------------------------------------------------------------- file

def empty():
    return {"roles": [], "contacts": [], "threads": []}


def load(path, must_exist=True):
    if not os.path.exists(path):
        if must_exist:
            raise PipelineError("no pipeline at %s (run: pipeline.py init)" % path)
        return empty()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        raise PipelineError("%s is not valid JSON: %s" % (path, e))
    if not isinstance(data, dict):
        raise PipelineError("%s must hold a JSON object with roles, contacts and threads" % path)
    for k in ("roles", "contacts", "threads"):
        if data.get(k) is None:
            data[k] = []
    return data


def save(path, data):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def slug(*parts):
    s = "-".join(str(p) for p in parts if p)
    s = s.lower().replace("&", " and ").replace("+", "p").replace("#", "sharp")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "item"


def unique_id(base, taken):
    if base not in taken:
        return base
    n = 2
    while "%s-%d" % (base, n) in taken:
        n += 1
    return "%s-%d" % (base, n)


def find(items, ident, what):
    for it in items:
        if it.get("id") == ident:
            return it
    raise PipelineError("no %s with id %r" % (what, ident))


def add_note(rec, day, text):
    line = "%s: %s" % (day.isoformat(), text)
    rec["notes"] = (rec.get("notes") or "").rstrip()
    rec["notes"] = (rec["notes"] + "\n" + line).strip()


# ---------------------------------------------------------------- validation

def _date_field(errors, where, rec, key, allow_time=False):
    v = rec.get(key)
    if v in (None, ""):
        return
    ok = STAMP_RE.match(str(v)) if allow_time else DATE_RE.match(str(v))
    if not ok or day_or_none(v) is None:
        errors.append("%s: %s must be YYYY-MM-DD, got %r" % (where, key, v))


def _text_field(errors, where, rec, key, required):
    v = rec.get(key)
    if v in (None, ""):
        if required:
            errors.append("%s: %s is required" % (where, key))
        return
    if not isinstance(v, str):
        errors.append("%s: %s must be text, got %r" % (where, key, v))


def check_confidence(value, source):
    """Return (error, warning) for an email_confidence value."""
    if value in (None, ""):
        return None, None
    if isinstance(value, bool):
        return "email_confidence must be a word or a number from 0 to 1, got %r" % value, None
    if isinstance(value, (int, float)):
        if 0 <= value <= 1:
            return None, None
        if 1 < value <= 100:
            return None, "email_confidence %r looks like a percent; use 0 to 1" % value
        return "email_confidence must be from 0 to 1, got %r" % value, None
    word = str(value).strip().lower()
    if word == "verified":
        word = "published"
    if word not in CONFIDENCE_WORDS:
        return "email_confidence must be one of %s or a number from 0 to 1, got %r" % (
            ", ".join(CONFIDENCE_WORDS), value), None
    if word == "published" and "http" not in str(source or ""):
        return ("email_confidence %r needs the public page where the address is published in "
                "'source' (a URL); otherwise it is a guess" % value), None
    return None, None


def validate(data):
    """Check the whole file against the schema. Returns (errors, warnings)."""
    errors, warnings = [], []
    if not isinstance(data, dict):
        return ["the file must hold a JSON object"], []
    for k in ("roles", "contacts", "threads"):
        if not isinstance(data.get(k), list):
            errors.append("%s must be a list" % k)
    for k in data:
        if k not in ("roles", "contacts", "threads") and not str(k).startswith("_"):
            warnings.append("extra top-level field %r (kept)" % k)
    if errors:
        return errors, warnings

    role_ids, contact_ids = set(), set()
    for i, r in enumerate(data["roles"]):
        where = "roles[%d]" % i
        if not isinstance(r, dict):
            errors.append("%s must be an object" % where)
            continue
        if r.get("id"):
            where = "role %s" % r["id"]
        for k in ("id", "company", "title"):
            _text_field(errors, where, r, k, True)
        for k in ("url", "next_step", "notes"):
            _text_field(errors, where, r, k, False)
        if r.get("id") in role_ids:
            errors.append("%s: duplicate id" % where)
        role_ids.add(r.get("id"))
        if r.get("stage") not in STAGES:
            errors.append("%s: stage must be one of %s, got %r" % (where, ", ".join(STAGES), r.get("stage")))
        _date_field(errors, where, r, "applied")
        _date_field(errors, where, r, "next_date")
        if r.get("url") and isinstance(r.get("url"), str) and not r["url"].startswith(("http://", "https://")):
            warnings.append("%s: url should start with https://" % where)
        if r.get("next_date") and not r.get("next_step"):
            warnings.append("%s: next_date without a next_step" % where)
        if r.get("stage") in ("applied", "screen", "interview", "onsite", "offer") and not r.get("applied"):
            warnings.append("%s: stage %s but no applied date" % (where, r.get("stage")))
        for k in r:
            if k not in ROLE_FIELDS:
                warnings.append("%s: extra field %r (kept)" % (where, k))

    for i, c in enumerate(data["contacts"]):
        where = "contacts[%d]" % i
        if not isinstance(c, dict):
            errors.append("%s must be an object" % where)
            continue
        if c.get("id"):
            where = "contact %s" % c["id"]
        for k in ("id", "name", "company"):
            _text_field(errors, where, c, k, True)
        for k in ("role", "linkedin", "email", "source", "notes"):
            _text_field(errors, where, c, k, False)
        if c.get("id") in contact_ids:
            errors.append("%s: duplicate id" % where)
        contact_ids.add(c.get("id"))
        if c.get("email") and isinstance(c.get("email"), str) and not EMAIL_RE.match(c["email"]):
            errors.append("%s: email %r is not an email address" % (where, c["email"]))
        err, warn = check_confidence(c.get("email_confidence"), c.get("source"))
        if err:
            errors.append("%s: %s" % (where, err))
        if warn:
            warnings.append("%s: %s" % (where, warn))
        if c.get("email") and c.get("email_confidence") in (None, ""):
            warnings.append("%s: email without email_confidence (a guess unless it was found published)" % where)
        li = c.get("linkedin")
        if li and isinstance(li, str) and "linkedin.com/" not in li:
            warnings.append("%s: linkedin should be a linkedin.com URL" % where)
        if "do_not_contact" in c and not isinstance(c["do_not_contact"], bool):
            errors.append("%s: do_not_contact must be true or false" % where)
        for k in c:
            if k not in CONTACT_FIELDS and k not in CONTACT_OPTIONAL:
                warnings.append("%s: extra field %r (kept)" % (where, k))

    seen = set()
    for i, t in enumerate(data["threads"]):
        where = "threads[%d]" % i
        if not isinstance(t, dict):
            errors.append("%s must be an object" % where)
            continue
        if t.get("contact_id") not in contact_ids:
            errors.append("%s: contact_id %r is not in contacts" % (where, t.get("contact_id")))
        if t.get("role_id") not in (None, "") and t.get("role_id") not in role_ids:
            errors.append("%s: role_id %r is not in roles" % (where, t.get("role_id")))
        ch = t.get("channel")
        if not ch or not isinstance(ch, str):
            errors.append("%s: channel is required (email, linkedin, ...)" % where)
        elif ch not in CHANNELS:
            warnings.append("%s: channel %r is not one of %s" % (where, ch, ", ".join(CHANNELS)))
        key = (t.get("contact_id"), t.get("role_id"), ch)
        if key in seen:
            warnings.append("%s: a second thread for the same contact, role and channel" % where)
        seen.add(key)
        if t.get("status") not in THREAD_STATUSES:
            errors.append("%s: status must be one of %s, got %r" % (where, ", ".join(THREAD_STATUSES), t.get("status")))
        _date_field(errors, where, t, "next_followup")
        msgs = t.get("messages")
        if not isinstance(msgs, list):
            errors.append("%s: messages must be a list" % where)
            msgs = []
        last = None
        for j, m in enumerate(msgs):
            mw = "%s.messages[%d]" % (where, j)
            if not isinstance(m, dict):
                errors.append("%s must be an object" % mw)
                continue
            _date_field(errors, mw, m, "date", allow_time=True)
            if m.get("date") in (None, ""):
                errors.append("%s: date is required" % mw)
            if m.get("direction") not in DIRECTIONS:
                errors.append("%s: direction must be out or in, got %r" % (mw, m.get("direction")))
            if not isinstance(m.get("text"), str):
                errors.append("%s: text is required" % mw)
            d = day_or_none(m.get("date"))
            if d and last and d < last:
                warnings.append("%s: messages are out of date order" % mw)
            last = d or last
            for k in m:
                if k not in MESSAGE_FIELDS:
                    warnings.append("%s: extra field %r (kept)" % (mw, k))
        outs = [m for m in msgs if isinstance(m, dict) and m.get("direction") == "out"]
        ins = [m for m in msgs if isinstance(m, dict) and m.get("direction") == "in"]
        status = t.get("status")
        if status in ("sent", "replied", "booked") and not outs:
            warnings.append("%s: status %s but no outgoing message" % (where, status))
        if status in ("replied", "booked") and not ins:
            warnings.append("%s: status %s but no reply logged" % (where, status))
        if status in ("declined", "closed", "booked") and t.get("next_followup"):
            warnings.append("%s: next_followup on a %s thread (stop rules: nothing more is sent)" % (where, status))
        if "invite" in t and not isinstance(t["invite"], bool):
            errors.append("%s: invite must be true or false" % where)
        for k in ("draft", "approval", "booked"):
            if t.get(k) is not None and not isinstance(t[k], dict):
                errors.append("%s: %s must be an object" % (where, k))
        if isinstance(t.get("draft"), dict) and not isinstance(t["draft"].get("text"), str):
            errors.append("%s: draft.text is required" % where)
        if t.get("approval") and not t.get("draft"):
            warnings.append("%s: an approval with no draft (it went out or was dropped)" % where)
        for k in t:
            if k not in THREAD_FIELDS and k not in THREAD_OPTIONAL:
                warnings.append("%s: extra field %r (kept)" % (where, k))
    return errors, warnings


# ---------------------------------------------------------------- activity

def last_activity(data, role):
    """The latest date anything happened on a role: applied, a dated note line, a thread message."""
    days = []
    d = day_or_none(role.get("applied"))
    if d:
        days.append(d)
    for s in NOTE_DATE_RE.findall(role.get("notes") or ""):
        d = day_or_none(s)
        if d:
            days.append(d)
    for t in data.get("threads", []):
        if t.get("role_id") == role.get("id"):
            for m in t.get("messages") or []:
                d = day_or_none(m.get("date"))
                if d:
                    days.append(d)
    return max(days) if days else None


def stale_roles(data, today, days):
    out = []
    for r in data["roles"]:
        if r.get("stage") not in ACTIVE:
            continue
        nd = day_or_none(r.get("next_date"))
        if nd and nd >= today:
            continue  # something is scheduled
        last = last_activity(data, r)
        idle = (today - last).days if last else None
        if idle is None or idle >= days:
            out.append((r, last, idle))
    out.sort(key=lambda x: (-(x[2] if x[2] is not None else 10 ** 6), x[0].get("id") or ""))
    return out


def upcoming(data, today, days):
    """Next steps on roles and follow-ups on threads, due within `days` (overdue included)."""
    horizon = today + datetime.timedelta(days=days)
    items = []
    for r in data["roles"]:
        nd = day_or_none(r.get("next_date"))
        if r.get("stage") in ACTIVE and nd and nd <= horizon:
            items.append((nd, "role", r.get("id"), "%s, %s: %s" % (r.get("company"), r.get("title"), r.get("next_step") or "next step")))
    names = {c.get("id"): c.get("name") for c in data["contacts"]}
    for t in data["threads"]:
        nd = day_or_none(t.get("next_followup"))
        if nd and nd <= horizon and t.get("status") not in ("declined", "closed", "booked"):
            items.append((nd, "thread", t.get("contact_id"), "follow up with %s (%s)" % (
                names.get(t.get("contact_id"), t.get("contact_id")), t.get("channel"))))
    items.sort(key=lambda x: (x[0], x[1], x[2] or ""))
    return items


def summary(data, today, stale_days=14):
    by_stage = {s: 0 for s in STAGES}
    for r in data["roles"]:
        if r.get("stage") in by_stage:
            by_stage[r["stage"]] += 1
    by_status = {s: 0 for s in THREAD_STATUSES}
    for t in data["threads"]:
        if t.get("status") in by_status:
            by_status[t["status"]] += 1
    active = sum(by_stage[s] for s in ACTIVE)
    applied_ever = sum(1 for r in data["roles"] if r.get("applied"))
    return {
        "as_of": today.isoformat(),
        "roles": len(data["roles"]),
        "active": active,
        "applied": applied_ever,
        "by_stage": by_stage,
        "contacts": len(data["contacts"]),
        "threads": by_status,
        "next": [{"date": d.isoformat(), "kind": k, "id": i, "what": w, "overdue": d < today}
                 for d, k, i, w in upcoming(data, today, 7)],
        "stale": [{"id": r.get("id"), "company": r.get("company"), "title": r.get("title"),
                   "stage": r.get("stage"), "last_activity": last.isoformat() if last else None,
                   "idle_days": idle} for r, last, idle in stale_roles(data, today, stale_days)],
    }


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def render_summary(s):
    lines = ["Pipeline on %s: %s (%d active, %d applied), %s" % (
        s["as_of"], plural(s["roles"], "role"), s["active"], s["applied"], plural(s["contacts"], "contact")), ""]
    lines.append("By stage:")
    for st in STAGES:
        if s["by_stage"][st]:
            lines.append("  %-10s %d" % (st, s["by_stage"][st]))
    if not any(s["by_stage"].values()):
        lines.append("  (no roles yet)")
    if any(s["threads"].values()):
        lines.append("")
        lines.append("Conversations: " + ", ".join("%d %s" % (n, st) for st, n in s["threads"].items() if n))
    lines.append("")
    lines.append("Next 7 days:")
    if s["next"]:
        for n in s["next"]:
            lines.append("  %s%s  %s" % (n["date"], " OVERDUE" if n["overdue"] else "", n["what"]))
    else:
        lines.append("  nothing scheduled")
    if s["stale"]:
        lines.append("")
        lines.append("Stale (no activity and nothing scheduled):")
        for r in s["stale"]:
            idle = "never touched" if r["idle_days"] is None else "%d days idle" % r["idle_days"]
            lines.append("  %s (%s, %s): %s" % (r["id"], r["company"], r["stage"], idle))
    return "\n".join(lines)


# ---------------------------------------------------------------- export

def to_csv(data, what):
    buf = io.StringIO()
    w = csv.writer(buf)
    if what == "roles":
        w.writerow(ROLE_FIELDS)
        for r in data["roles"]:
            w.writerow([r.get(k) if r.get(k) is not None else "" for k in ROLE_FIELDS])
    elif what == "contacts":
        w.writerow(CONTACT_FIELDS)
        for c in data["contacts"]:
            w.writerow([c.get(k) if c.get(k) is not None else "" for k in CONTACT_FIELDS])
    elif what == "threads":
        cols = ("contact_id", "role_id", "channel", "status", "next_followup", "messages",
                "first_date", "last_date", "last_direction")
        w.writerow(cols)
        for t in data["threads"]:
            msgs = t.get("messages") or []
            w.writerow([t.get("contact_id") or "", t.get("role_id") or "", t.get("channel") or "",
                        t.get("status") or "", t.get("next_followup") or "", len(msgs),
                        msgs[0].get("date", "") if msgs else "", msgs[-1].get("date", "") if msgs else "",
                        msgs[-1].get("direction", "") if msgs else ""])
    else:
        raise PipelineError("--what must be roles, contacts or threads")
    return buf.getvalue()


# ---------------------------------------------------------------- commands

def _require_valid(data):
    errors, _ = validate(data)
    if errors:
        raise PipelineError("the change would leave the pipeline invalid:\n  " + "\n  ".join(errors))


def cmd_init(a):
    if os.path.exists(a.file):
        raise PipelineError("%s already exists; nothing changed" % a.file)
    save(a.file, empty())
    print("Created %s (roles, contacts, threads: all empty)" % a.file)
    return 0


def cmd_validate(a):
    data = load(a.file)
    errors, warnings = validate(data)
    if a.json:
        print(json.dumps({"ok": not errors, "errors": errors, "warnings": warnings}, indent=2))
    else:
        if not errors:
            print("OK: %s matches the pipeline schema (%s, %s, %s)" % (
                a.file, plural(len(data["roles"]), "role"), plural(len(data["contacts"]), "contact"),
                plural(len(data["threads"]), "thread")))
        for e in errors:
            print("ERROR  " + e)
        for w in warnings:
            print("WARN   " + w)
    return 1 if errors else 0


def cmd_add_role(a):
    data = load(a.file, must_exist=False)
    today = today_from(a.today)
    for r in data["roles"]:
        same_url = a.url and r.get("url") == a.url
        same_name = (str(r.get("company", "")).lower(), str(r.get("title", "")).lower()) == (a.company.lower(), a.title.lower())
        if (same_url or same_name) and not a.force:
            print("Already in the pipeline as %s (stage %s). Use --force to add a second one." % (r.get("id"), r.get("stage")))
            return 1
    stage = a.stage or "saved"
    if stage not in STAGES:
        raise PipelineError("stage must be one of %s" % ", ".join(STAGES))
    taken = {r.get("id") for r in data["roles"]}
    rid = a.id or unique_id(slug(a.company, a.title), taken)
    if rid in taken:
        raise PipelineError("id %r is taken" % rid)
    applied = a.applied
    if not applied and stage in ("applied", "screen", "interview", "onsite", "offer"):
        applied = today.isoformat()
    role = {"id": rid, "company": a.company, "title": a.title, "url": a.url, "stage": stage,
            "applied": applied, "next_step": a.next_step, "next_date": a.next_date, "notes": a.notes or ""}
    add_note(role, today, "added as %s" % stage)
    data["roles"].append(role)
    _require_valid(data)
    save(a.file, data)
    print("Added role %s: %s, %s (%s)" % (rid, a.company, a.title, stage))
    return 0


def cmd_update_role(a):
    data = load(a.file)
    role = find(data["roles"], a.id, "role")
    changed = []
    for k in ("company", "title", "url", "applied", "next_step", "next_date"):
        v = getattr(a, k)
        if v is not None:
            role[k] = v or None
            changed.append(k)
    if a.clear_next:
        role["next_step"], role["next_date"] = None, None
        changed.append("next step cleared")
    if a.notes:
        add_note(role, today_from(a.today), a.notes)
        changed.append("notes")
    if not changed:
        print("Nothing to change.")
        return 1
    _require_valid(data)
    save(a.file, data)
    print("Updated %s: %s" % (a.id, ", ".join(changed)))
    return 0


def cmd_move(a):
    data = load(a.file)
    role = find(data["roles"], a.id, "role")
    if a.stage not in STAGES:
        raise PipelineError("stage must be one of %s" % ", ".join(STAGES))
    today = today_from(a.today)
    old = role.get("stage")
    role["stage"] = a.stage
    if a.stage in ("applied", "screen", "interview", "onsite", "offer") and not role.get("applied"):
        role["applied"] = today.isoformat()
    if a.stage in CLOSED:
        role["next_step"], role["next_date"] = None, None
    if a.next_step is not None:
        role["next_step"] = a.next_step or None
    if a.next_date is not None:
        role["next_date"] = a.next_date or None
    add_note(role, today, "%s -> %s" % (old, a.stage))
    _require_valid(data)
    save(a.file, data)
    print("Moved %s: %s -> %s" % (a.id, old, a.stage))
    return 0


def cmd_add_contact(a):
    data = load(a.file, must_exist=False)
    for c in data["contacts"]:
        if (str(c.get("name", "")).lower(), str(c.get("company", "")).lower()) == (a.name.lower(), a.company.lower()) and not a.force:
            print("Already in the pipeline as %s. Use --force to add a second one." % c.get("id"))
            return 1
    taken = {c.get("id") for c in data["contacts"]}
    cid = a.id or unique_id(slug(a.name, a.company), taken)
    if cid in taken:
        raise PipelineError("id %r is taken" % cid)
    conf = a.email_confidence
    if conf is not None:
        try:
            conf = float(conf)
        except ValueError:
            pass
    contact = {"id": cid, "name": a.name, "role": a.role, "company": a.company, "linkedin": a.linkedin,
               "email": a.email, "email_confidence": conf, "source": a.source, "notes": a.notes or ""}
    data["contacts"].append(contact)
    _require_valid(data)
    save(a.file, data)
    print("Added contact %s: %s, %s" % (cid, a.name, a.company))
    return 0


def cmd_update_contact(a):
    data = load(a.file)
    c = find(data["contacts"], a.id, "contact")
    changed = []
    for k in ("name", "role", "company", "linkedin", "email", "source"):
        v = getattr(a, k)
        if v is not None:
            c[k] = v or None
            changed.append(k)
    if a.email_confidence is not None:
        v = a.email_confidence
        try:
            v = float(v)
        except ValueError:
            pass
        c["email_confidence"] = v if v != "" else None
        changed.append("email_confidence")
    if a.notes:
        add_note(c, today_from(a.today), a.notes)
        changed.append("notes")
    if not changed:
        print("Nothing to change.")
        return 1
    _require_valid(data)
    save(a.file, data)
    print("Updated %s: %s" % (a.id, ", ".join(changed)))
    return 0


def cmd_summary(a):
    data = load(a.file)
    s = summary(data, today_from(a.today), a.stale_days)
    print(json.dumps(s, indent=2) if a.json else render_summary(s))
    return 0


def cmd_stale(a):
    data = load(a.file)
    rows = stale_roles(data, today_from(a.today), a.days)
    if not rows:
        print("Nothing stale: every active role moved in the last %d days or has a next step scheduled." % a.days)
        return 0
    for r, last, idle in rows:
        when = "never touched" if last is None else "last activity %s (%d days)" % (last.isoformat(), idle)
        print("%s  %s, %s  [%s]  %s" % (r.get("id"), r.get("company"), r.get("title"), r.get("stage"), when))
    return 0


def cmd_next(a):
    data = load(a.file)
    today = today_from(a.today)
    items = upcoming(data, today, a.days)
    if not items:
        print("Nothing scheduled in the next %d days." % a.days)
        return 0
    for d, kind, ident, what in items:
        flag = "OVERDUE " if d < today else ("TODAY   " if d == today else "        ")
        print("%s %s %s" % (d.isoformat(), flag, what))
    return 0


def cmd_show(a):
    data = load(a.file)
    for coll, what in ((data["roles"], "role"), (data["contacts"], "contact")):
        for it in coll:
            if it.get("id") == a.id:
                key = "role_id" if what == "role" else "contact_id"
                threads = [t for t in data["threads"] if t.get(key) == a.id]
                print(json.dumps({what: it, "threads": threads}, indent=2, ensure_ascii=False))
                return 0
    raise PipelineError("no role or contact with id %r" % a.id)


def cmd_export(a):
    data = load(a.file)
    text = to_csv(data, a.what)
    if a.out:
        d = os.path.dirname(a.out)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        print("Wrote %s (%d %s)" % (a.out, len(data[a.what]), a.what))
    else:
        sys.stdout.write(text)
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="The hunter pipeline: roles, contacts and threads in hunter/pipeline.json.")
    p.add_argument("--file", default=DEFAULT_FILE, help="pipeline file (default hunter/pipeline.json)")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--file", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        sp.add_argument("--today", help="YYYY-MM-DD (default: the computer's date)")

    sp = sub.add_parser("init", help="create an empty pipeline")
    common(sp)
    sp = sub.add_parser("validate", help="check the file against the schema (exit 1 on errors)")
    common(sp)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("add-role", help="add a role")
    common(sp)
    sp.add_argument("--company", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--url")
    sp.add_argument("--stage", choices=STAGES)
    sp.add_argument("--applied")
    sp.add_argument("--next-step")
    sp.add_argument("--next-date")
    sp.add_argument("--notes")
    sp.add_argument("--id")
    sp.add_argument("--force", action="store_true")

    sp = sub.add_parser("update-role", help="change fields on a role")
    common(sp)
    sp.add_argument("id")
    for k in ("--company", "--title", "--url", "--applied", "--next-step", "--next-date", "--notes"):
        sp.add_argument(k)
    sp.add_argument("--clear-next", action="store_true")

    sp = sub.add_parser("move", help="move a role to a stage")
    common(sp)
    sp.add_argument("id")
    sp.add_argument("stage", choices=STAGES)
    sp.add_argument("--next-step")
    sp.add_argument("--next-date")

    sp = sub.add_parser("add-contact", help="add a contact")
    common(sp)
    sp.add_argument("--name", required=True)
    sp.add_argument("--company", required=True)
    for k in ("--role", "--linkedin", "--email", "--email-confidence", "--source", "--notes", "--id"):
        sp.add_argument(k)
    sp.add_argument("--force", action="store_true")

    sp = sub.add_parser("update-contact", help="change fields on a contact")
    common(sp)
    sp.add_argument("id")
    for k in ("--name", "--role", "--company", "--linkedin", "--email", "--email-confidence", "--source", "--notes"):
        sp.add_argument(k)

    sp = sub.add_parser("summary", help="counts by stage, next steps, stale roles")
    common(sp)
    sp.add_argument("--stale-days", type=int, default=14)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("stale", help="active roles with no activity and nothing scheduled")
    common(sp)
    sp.add_argument("--days", type=int, default=14)

    sp = sub.add_parser("next", help="next steps and follow-ups coming up")
    common(sp)
    sp.add_argument("--days", type=int, default=7)

    sp = sub.add_parser("show", help="one role or contact with its threads")
    common(sp)
    sp.add_argument("id")

    sp = sub.add_parser("export", help="write roles, contacts or threads as CSV")
    common(sp)
    sp.add_argument("--what", choices=("roles", "contacts", "threads"), default="roles")
    sp.add_argument("--out")
    return p


COMMANDS = {"init": cmd_init, "validate": cmd_validate, "add-role": cmd_add_role, "update-role": cmd_update_role,
            "move": cmd_move, "add-contact": cmd_add_contact, "update-contact": cmd_update_contact,
            "summary": cmd_summary, "stale": cmd_stale, "next": cmd_next, "show": cmd_show, "export": cmd_export}


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    try:
        return COMMANDS[a.cmd](a)
    except PipelineError as e:
        print("pipeline: " + str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
