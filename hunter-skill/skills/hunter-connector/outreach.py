#!/usr/bin/env python3
"""Outreach threads for hunter-connector. Standard library only.

Keeps every contact and conversation in hunter/pipeline.json and enforces the
consent and stop rules. This tool never sends anything: Claude drafts, the
user says yes to that exact message, the user sends it from their own account
(a Gmail draft they send, or a LinkedIn note they send in their own browser),
and then this records it.

    python3 outreach.py contact add --name "Maya C." --role "Engineering Manager" --company Google
    python3 outreach.py draft --contact maya-c-google --channel email --subject "..." --text "..."
    python3 outreach.py approve --contact maya-c-google --channel email --reply "yes, send it"
    python3 outreach.py sent --contact maya-c-google --channel email --date 2026-10-15
    python3 outreach.py reply --contact maya-c-google --channel email --text "Happy to grab a coffee..."
    python3 outreach.py book --contact maya-c-google --when "2026-10-22 10:00" --where "Google Meet" --reply "yes"
    python3 outreach.py due                 # what needs doing today, and what to close
    python3 outreach.py contact stop --contact maya-c-google   # never contact again

Thread states: drafted -> sent -> replied -> booked, or declined / closed.
Stop rules: stop at the first no or any sign of disinterest; at most 2
follow-ups (3 days after the first message, then 7 days after that); no
message after 21 days of silence; a stop or unsubscribe request is honoured
forever. LinkedIn invitation notes are limited to 200 characters (LinkedIn
Help 46662).
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys

FOLLOWUP_GAPS = (3, 7)
MAX_FOLLOWUPS = 2
SILENCE_DAYS = 21
INVITE_NOTE_MAX = 200
EMAIL_WORDS_MAX = 150
CHANNELS = ("email", "linkedin")
STAGES = ("saved", "applied", "screen", "interview", "onsite", "offer", "rejected", "withdrawn")

NO_SIGNS = re.compile(r"\b(not interested|no thanks|no thank you|not hiring|not a fit|please don'?t|"
                      r"do not contact|don'?t contact|unsubscribe|stop (?:emailing|messaging|contacting)|"
                      r"remove me|take me off|not the right person|not looking|pass on this|leave me alone|not (?:right )?now|"
                      r"not at this time|too busy|no bandwidth|can'?t help|no (?:open )?(?:roles|openings|headcount))\b",
                      re.I)
STOP_SIGNS = re.compile(r"\b(unsubscribe|stop (?:emailing|messaging|contacting)|do not contact|don'?t contact|"
                        r"remove me|take me off|leave me alone)\b", re.I)
PERSONAL = re.compile(r"\b(wife|husband|girlfriend|boyfriend|kids?|children|son|daughter|married|wedding|"
                      r"pregnan\w*|divorce\w*|dating|home address|lives? (?:in|at|on)|church|mosque|synagogue|"
                      r"religio\w*|diagnos\w*|illness|birthday|vacation|marathon|gym|workout|instagram|facebook|"
                      r"tiktok|personal account)\b", re.I)
YES_START = re.compile(r"^(yes|yep|yeah|yup|y|ok|okay|sure|approved?|go ahead|send it|ship it|looks good|lgtm)\b")
YES_WORDS = re.compile(r"\b(yes|yep|yeah|yup|approved?|send it|go ahead|ship it)\b")
NOT_YES = re.compile(r"\b(all|every|everyone|everything|both|but|except|change|edit|tweak|wait|hold|no|not|"
                     r"don'?t|later|tomorrow|maybe|after|before|instead|first)\b")


class OutreachError(Exception):
    pass


# ---------------------------------------------------------------- storage

def day(value):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        raise OutreachError("dates are YYYY-MM-DD, got %r" % value)
    return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def load(path):
    data = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    for k in ("roles", "contacts", "threads"):
        data.setdefault(k, [])
    return data


def save(path, data):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def contact(pipe, cid):
    for c in pipe["contacts"]:
        if c.get("id") == cid:
            return c
    raise OutreachError("no contact %s (see `outreach.py show`)" % cid)


def thread(pipe, cid, channel, create=False, role_id=None):
    for t in pipe["threads"]:
        if t.get("contact_id") == cid and t.get("channel") == channel:
            if role_id and not t.get("role_id"):
                t["role_id"] = role_id
            return t
    if not create:
        raise OutreachError("no %s thread with %s yet" % (channel, cid))
    t = {"contact_id": cid, "role_id": role_id, "channel": channel, "messages": [], "status": "drafted",
         "next_followup": None}
    pipe["threads"].append(t)
    return t


def role(pipe, rid):
    for r in pipe["roles"]:
        if r.get("id") == rid:
            return r
    return None


# ---------------------------------------------------------------- rules

def research_problems(line):
    """Contact research must be public professional information with a source."""
    errors, warnings = [], []
    m = PERSONAL.search(line or "")
    if m:
        errors.append("personal life (%r): research uses public professional information only" % m.group(0))
    if not re.search(r"https?://|public profile|company site|team page|posting|talk|paper|post", line or "", re.I):
        warnings.append("no source: add the public URL it came from")
    return errors, warnings


def is_yes(reply):
    """(True, '') only for an explicit yes to this one message."""
    r = re.sub(r"\s+", " ", (reply or "").strip().lower())
    r = re.sub(r"[!.]+$", "", r).strip()
    if not r:
        return False, "no reply recorded"
    if NOT_YES.search(r):
        return False, "the reply has a condition or covers more than this one message: ask again"
    if r in ("sure", "ok", "okay", "fine", "y", "looks good", "lgtm"):
        return False, "%r is not an explicit yes to send: ask \"Send this exact message? yes or no\"" % reply
    if YES_START.match(r) and YES_WORDS.search(r):
        return True, ""
    if r in ("send", "send it", "go ahead", "approved", "approve"):
        return True, ""
    return False, "not an explicit yes: ask again"


def draft_hash(channel, subject, text):
    return hashlib.sha1(("%s\n%s\n%s" % (channel, subject or "", text or "")).encode("utf-8")).hexdigest()[:12]


def outbound(t):
    return [m for m in t.get("messages", []) if m.get("direction") == "out"]


def last_inbound(t):
    ins = [m for m in t.get("messages", []) if m.get("direction") == "in"]
    return ins[-1] if ins else None


def followups_sent(t):
    """Outbound messages since their last reply, not counting the one that opened that stretch."""
    msgs = t.get("messages", [])
    idx = max([i for i, m in enumerate(msgs) if m.get("direction") == "in"] or [-1])
    after = [m for m in msgs[idx + 1:] if m.get("direction") == "out"]
    return max(0, len(after) - 1)


def silence_start(t):
    li = last_inbound(t)
    if li:
        return day(li["date"])
    out = outbound(t)
    return day(out[0]["date"]) if out else None


def compute_next(t):
    """Next follow-up date under the stop rules, or None."""
    if t.get("status") not in ("sent", "replied"):
        return None
    if t.get("invite"):
        return None  # a pending LinkedIn invitation gets no follow-up: wait for them to accept
    msgs = t.get("messages", [])
    if not msgs or msgs[-1].get("direction") != "out":
        return None  # they spoke last: we owe a reply, not a follow-up
    n = followups_sent(t)
    if n >= MAX_FOLLOWUPS:
        return None
    nxt = day(msgs[-1]["date"]) + _dt.timedelta(days=FOLLOWUP_GAPS[min(n, len(FOLLOWUP_GAPS) - 1)])
    start = silence_start(t)
    if start and (nxt - start).days > SILENCE_DAYS:
        return None
    return nxt.isoformat()


def kind_of(t):
    if not outbound(t):
        return "first"
    msgs = t.get("messages", [])
    return "reply" if msgs and msgs[-1].get("direction") == "in" else "followup"


def lint(channel, kind, text, subject=None, connected=False):
    """(errors, warnings) for a draft."""
    errors, warnings = [], []
    text = (text or "").strip()
    if not text:
        errors.append("empty message")
        return errors, warnings
    if channel == "linkedin" and kind == "first" and not connected:
        if len(text) > INVITE_NOTE_MAX:
            errors.append("a LinkedIn invitation note is at most %d characters (LinkedIn Help 46662); this one is %d"
                          % (INVITE_NOTE_MAX, len(text)))
        warnings.append("without Premium LinkedIn allows a personal note on 3 invitations a month")
    if channel == "linkedin" and len(text) > 1000:
        warnings.append("long for a LinkedIn message (%d characters): keep it to a few lines" % len(text))
    if channel == "email":
        if kind == "first" and not (subject or "").strip():
            errors.append("an email needs a subject")
        if subject and len(subject) > 60:
            warnings.append("subject is %d characters: under 60 reads better on a phone" % len(subject))
        words = len(re.findall(r"\S+", text))
        if words > EMAIL_WORDS_MAX:
            warnings.append("%d words: a first note to a busy manager reads best under %d" % (words, EMAIL_WORDS_MAX))
    invite = channel == "linkedin" and kind == "first" and not connected
    if kind in ("first", "followup") and not invite and "?" not in text:
        warnings.append("no question: end with one small, specific ask (a 20 minute chat next week?)")
    if re.search(r"\b(as per my last|per my last|did you (?:get|see) my|bumping this|why haven'?t you)\b", text, re.I):
        warnings.append("sounds like pressure: a follow-up adds something new or offers an easy out")
    return errors, warnings


# ---------------------------------------------------------------- commands

def add_contact(pipe, name, role_title=None, company=None, linkedin=None, email=None, email_confidence=None,
                source=None, notes=None, research=()):
    cid = slug("%s %s" % (name, company or ""))
    if any(c.get("id") == cid for c in pipe["contacts"]):
        raise OutreachError("contact %s already exists" % cid)
    if email and email_confidence is None:
        raise OutreachError("an email needs --email-confidence (from emails.py); 1.0 only if it is published")
    if email_confidence is not None and not 0 <= email_confidence <= 1:
        raise OutreachError("--email-confidence is between 0 and 1")
    lines, warnings = [], []
    for r in research:
        errs, warns = research_problems(r)
        if errs:
            raise OutreachError("; ".join(errs) + ": %r" % r)
        warnings += ["%s: %s" % (w, r) for w in warns]
        lines.append(r)
    note = "\n".join([n for n in [notes] if n] + lines)
    c = {"id": cid, "name": name, "role": role_title, "company": company, "linkedin": linkedin, "email": email,
         "email_confidence": email_confidence, "source": source, "notes": note}
    pipe["contacts"].append(c)
    return c, warnings


def stop_contact(pipe, cid, reason, today):
    c = contact(pipe, cid)
    c["do_not_contact"] = True
    line = "%s: Do not contact (%s)" % (today.isoformat(), reason or "asked to stop")
    c["notes"] = ((c.get("notes") or "").rstrip() + "\n" + line).strip()
    for t in pipe["threads"]:
        if t.get("contact_id") == cid:
            if t.get("status") not in ("declined",):
                t["status"] = "closed"
            t["next_followup"] = None
            t.pop("draft", None)
            t.pop("approval", None)
    return c


def make_draft(pipe, cid, channel, text, subject=None, role_id=None, today=None, connected=False, early=False):
    if channel not in CHANNELS:
        raise OutreachError("channel is email or linkedin")
    c = contact(pipe, cid)
    if c.get("do_not_contact"):
        raise OutreachError("%s asked not to be contacted: no messages, on any channel, ever" % c["name"])
    if channel == "email" and not c.get("email"):
        raise OutreachError("no email for %s: run emails.py and add it with its confidence" % c["name"])
    t = thread(pipe, cid, channel, create=True, role_id=role_id)
    if t["status"] in ("declined", "closed"):
        raise OutreachError("this thread is %s: the stop rules end it here" % t["status"])
    if channel == "linkedin":
        if connected:
            t["invite"] = False
        elif t.get("invite") and t.get("messages"):
            raise OutreachError("the invitation is still pending: once they accept, draft with --connected")
        elif not t.get("messages"):
            t["invite"] = True
    kind = kind_of(t)
    if kind == "followup":
        n = followups_sent(t)
        if n >= MAX_FOLLOWUPS:
            raise OutreachError("already %d follow-ups with no reply: close the thread" % n)
        start = silence_start(t)
        if start and today and (today - start).days > SILENCE_DAYS:
            raise OutreachError("%d days of silence: no more messages on this thread" % (today - start).days)
        due = t.get("next_followup")
        if due and today and today < day(due) and not early:
            raise OutreachError("follow-up %d is not due until %s" % (n + 1, due))
    errors, warnings = lint(channel, kind, text, subject, connected)
    if errors:
        raise OutreachError("; ".join(errors))
    t["draft"] = {"kind": kind, "subject": subject, "text": text.strip(), "created": today.isoformat() if today else None,
                  "hash": draft_hash(channel, subject, text.strip())}
    t.pop("approval", None)
    if not t["messages"]:
        t["status"] = "drafted"
    return t, warnings


def approve(pipe, cid, channel, reply, today):
    t = thread(pipe, cid, channel)
    d = t.get("draft")
    if not d:
        raise OutreachError("nothing drafted on this thread")
    ok, why = is_yes(reply)
    if not ok:
        raise OutreachError("Not recorded: %s" % why)
    t["approval"] = {"reply": reply, "date": today.isoformat(), "hash": d["hash"]}
    return t


def mark_sent(pipe, cid, channel, when):
    t = thread(pipe, cid, channel)
    d, a = t.get("draft"), t.get("approval")
    if not d:
        raise OutreachError("nothing drafted on this thread")
    if not a or a.get("hash") != d["hash"]:
        raise OutreachError("no yes recorded for this exact message: show it to the user and run approve first")
    t["messages"].append({"date": when.isoformat(), "direction": "out", "text": d["text"]})
    if t["status"] == "drafted":
        t["status"] = "sent"
    t.pop("draft", None)
    t.pop("approval", None)
    t["next_followup"] = compute_next(t)
    return t


def log_reply(pipe, cid, channel, text, when, declined=False, stop=False):
    t = thread(pipe, cid, channel)
    if not outbound(t):
        raise OutreachError("no message was sent on this thread")
    t["messages"].append({"date": when.isoformat(), "direction": "in", "text": text})
    t["next_followup"] = None
    stop = stop or bool(STOP_SIGNS.search(text or ""))
    declined = declined or stop or bool(NO_SIGNS.search(text or ""))
    if stop:
        stop_contact(pipe, cid, "asked to stop", when)
        t["status"] = "declined"
    elif declined:
        t["status"] = "declined"
        t.pop("draft", None)
    elif t["status"] in ("drafted", "sent"):
        t["status"] = "replied"
    return t, declined, stop


def book(pipe, cid, channel, when, minutes, where, reply, role_id=None):
    t = thread(pipe, cid, channel)
    if not last_inbound(t):
        raise OutreachError("book only after they said yes: log their reply first")
    if t["status"] in ("declined", "closed"):
        raise OutreachError("this thread is %s" % t["status"])
    ok, why = is_yes(reply)
    if not ok:
        raise OutreachError("Not booked: the calendar invite goes to them, so it needs the user's yes (%s)" % why)
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})$", when or "")
    if not m:
        raise OutreachError("--when wants 'YYYY-MM-DD HH:MM' in the user's time zone")
    c = contact(pipe, cid)
    t["status"] = "booked"
    t["next_followup"] = None
    t["booked"] = {"when": "%s %02d:%s" % (m.group(1), int(m.group(2)), m.group(3)), "minutes": minutes,
                   "where": where, "approved": reply}
    rid = role_id or t.get("role_id")
    r = role(pipe, rid) if rid else None
    if r:
        r["next_step"] = "Coffee chat with %s (%s)" % (c["name"], where or "details in the invite")
        r["next_date"] = m.group(1)
    return t


def reopen(pipe, cid, channel):
    """Undo a declined reading the user disagrees with (never after a stop request)."""
    c = contact(pipe, cid)
    if c.get("do_not_contact"):
        raise OutreachError("%s asked not to be contacted: that is final" % c["name"])
    t = thread(pipe, cid, channel)
    if t["status"] != "declined":
        raise OutreachError("only a declined thread can be reopened")
    t["status"] = "replied"
    return t


def close_thread(pipe, cid, channel, reason=None):
    t = thread(pipe, cid, channel)
    t["status"] = "closed"
    t["next_followup"] = None
    t.pop("draft", None)
    t.pop("approval", None)
    return t


def due(pipe, today):
    """What needs the user today. Returns dict of lists."""
    names = {c["id"]: c for c in pipe["contacts"]}
    out = {"approve": [], "send": [], "followup": [], "reply": [], "close": [], "chats": [], "close_keys": []}
    for t in pipe["threads"]:
        c = names.get(t.get("contact_id"), {"name": t.get("contact_id")})
        who = "%s%s (%s)" % (c.get("name"), " at %s" % c["company"] if c.get("company") else "", t.get("channel"))
        st = t.get("status")
        if c.get("do_not_contact") or st in ("declined", "closed"):
            continue
        d, a = t.get("draft"), t.get("approval")
        if d and not (a and a.get("hash") == d["hash"]):
            out["approve"].append("%s: %s draft waiting for your yes" % (who, d["kind"]))
        elif d:
            out["send"].append("%s: approved, send it from your own account, then run `sent`" % who)
        if st == "booked":
            b = t.get("booked") or {}
            if b.get("when", "")[:10] >= today.isoformat():
                out["chats"].append("%s: coffee chat %s, %s" % (c.get("name"), b.get("when"), b.get("where") or ""))
            continue
        msgs = t.get("messages", [])
        if msgs and msgs[-1].get("direction") == "in" and st == "replied":
            out["reply"].append("%s replied on %s: answer them" % (who, msgs[-1]["date"]))
            continue
        if not msgs or d:
            continue
        nxt = t.get("next_followup")
        start = silence_start(t)
        silent = (today - start).days if start else 0
        if nxt and day(nxt) <= today and silent <= SILENCE_DAYS:
            out["followup"].append("%s: follow-up %d due %s (%d days since %s)" % (
                who, followups_sent(t) + 1, nxt, silent, "their last reply" if last_inbound(t) else "your first message"))
        elif not nxt:
            last_out = day(msgs[-1]["date"])
            if silent > SILENCE_DAYS:
                out["close"].append("%s: %d days of silence, close it" % (who, silent))
                out["close_keys"].append([t["contact_id"], t["channel"]])
            elif followups_sent(t) >= MAX_FOLLOWUPS and (today - last_out).days >= FOLLOWUP_GAPS[-1]:
                out["close"].append("%s: two follow-ups and no reply, close it" % who)
                out["close_keys"].append([t["contact_id"], t["channel"]])
    return out


def render_due(d, today):
    titles = [("approve", "Waiting for your yes"), ("send", "Approved, not sent yet"), ("followup", "Follow-ups due"),
              ("reply", "They replied"), ("chats", "Coffee chats"), ("close", "Close (stop rules)")]
    lines = ["Outreach on %s:" % today.isoformat()]
    for key, title in titles:
        if d[key]:
            lines.append(title + ":")
            lines += ["  - " + x for x in d[key]]
    if len(lines) == 1:
        lines.append("Nothing due.")
    return "\n".join(lines) + "\n"


def show(pipe, cid=None):
    lines = []
    for c in pipe["contacts"]:
        if cid and c["id"] != cid:
            continue
        flag = "  DO NOT CONTACT" if c.get("do_not_contact") else ""
        conf = c.get("email_confidence")
        email = "%s (%s)" % (c["email"], "published" if conf == 1 else "guessed, %.2f" % conf) if c.get("email") else "no email"
        lines.append("%s  %s, %s at %s  %s%s" % (c["id"], c["name"], c.get("role") or "?", c.get("company") or "?", email, flag))
        for t in pipe["threads"]:
            if t.get("contact_id") != c["id"]:
                continue
            lines.append("  %-8s %-8s %d messages  next follow-up: %s%s" % (
                t["channel"], t["status"], len(t.get("messages", [])), t.get("next_followup") or "none",
                "  (draft waiting)" if t.get("draft") else ""))
    return "\n".join(lines or ["No contacts yet."]) + "\n"


# ---------------------------------------------------------------- CLI

def _today(value):
    return day(value) if value else _dt.date.today()


def _text(args):
    if getattr(args, "file", None):
        with open(args.file, encoding="utf-8") as fh:
            return fh.read()
    return args.text


def main(argv=None):
    ap = argparse.ArgumentParser(description="Outreach threads with consent and stop rules. Never sends anything.")
    ap.add_argument("--pipeline", default="hunter/pipeline.json")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("contact", help="add a contact or stop contacting one")
    csub = c.add_subparsers(dest="action")
    ca = csub.add_parser("add")
    ca.add_argument("--name", required=True)
    ca.add_argument("--role")
    ca.add_argument("--company")
    ca.add_argument("--linkedin")
    ca.add_argument("--email")
    ca.add_argument("--email-confidence", type=float)
    ca.add_argument("--source", help="where you found them: the posting, a team page, a public profile")
    ca.add_argument("--notes")
    ca.add_argument("--research", action="append", default=[], help="one public professional fact + its URL")
    cs = csub.add_parser("stop")
    cs.add_argument("--contact", required=True)
    cs.add_argument("--reason")
    cs.add_argument("--today")

    d = sub.add_parser("draft", help="save a draft for the user to approve")
    d.add_argument("--contact", required=True)
    d.add_argument("--channel", required=True, choices=CHANNELS)
    d.add_argument("--role", help="the role id in the pipeline")
    d.add_argument("--subject")
    d.add_argument("--text")
    d.add_argument("--file")
    d.add_argument("--connected", action="store_true", help="already connected on LinkedIn (a message, not an invite)")
    d.add_argument("--early", action="store_true", help="the user wants this follow-up before it is due")
    d.add_argument("--today")

    for name in ("approve", "sent", "reply", "book", "close", "reopen"):
        p = sub.add_parser(name)
        p.add_argument("--contact", required=True)
        p.add_argument("--channel", default="email", choices=CHANNELS)
        if name == "approve":
            p.add_argument("--reply", required=True, help="the user's reply, word for word")
            p.add_argument("--today")
        if name == "sent":
            p.add_argument("--date", help="YYYY-MM-DD it went out (default today)")
        if name == "reply":
            p.add_argument("--text", required=True)
            p.add_argument("--date")
            p.add_argument("--declined", action="store_true", help="any sign of disinterest")
            p.add_argument("--stop", action="store_true", help="they asked not to be contacted")
        if name == "book":
            p.add_argument("--when", required=True, help="'YYYY-MM-DD HH:MM'")
            p.add_argument("--minutes", type=int, default=30)
            p.add_argument("--where")
            p.add_argument("--role")
            p.add_argument("--reply", required=True, help="the user's yes to sending the invite, word for word")
        if name == "close":
            p.add_argument("--reason")

    du = sub.add_parser("due", help="what needs doing today")
    du.add_argument("--today")
    du.add_argument("--close", action="store_true", help="close the threads the stop rules end")
    du.add_argument("--json", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("--contact")

    args = ap.parse_args(argv)
    if not args.cmd or (args.cmd == "contact" and not args.action):
        ap.print_help()
        return 2
    pipe = load(args.pipeline)
    try:
        if args.cmd == "contact" and args.action == "add":
            c_, warns = add_contact(pipe, args.name, args.role, args.company, args.linkedin, args.email,
                                    args.email_confidence, args.source, args.notes, args.research)
            save(args.pipeline, pipe)
            print("added contact %s" % c_["id"])
            for w in warns:
                print("warning: %s" % w)
            return 0
        if args.cmd == "contact" and args.action == "stop":
            c_ = stop_contact(pipe, args.contact, args.reason, _today(args.today))
            save(args.pipeline, pipe)
            print("%s is marked do not contact, forever. Open threads closed." % c_["name"])
            return 0
        if args.cmd == "draft":
            t, warns = make_draft(pipe, args.contact, args.channel, _text(args), args.subject, args.role,
                                  _today(args.today), args.connected, args.early)
            save(args.pipeline, pipe)
            dr = t["draft"]
            print("Draft saved (%s, %s). Show it to the user exactly as below and ask: Send this exact message? yes or no"
                  % (args.channel, dr["kind"]))
            if dr.get("subject"):
                print("Subject: %s" % dr["subject"])
            print(dr["text"])
            for w in warns:
                print("warning: %s" % w)
            return 0
        if args.cmd == "approve":
            approve(pipe, args.contact, args.channel, args.reply, _today(args.today))
            save(args.pipeline, pipe)
            print("Recorded your yes for this one message. Now send it from your own account "
                  "(Gmail draft or LinkedIn in your browser), then run `sent`.")
            return 0
        if args.cmd == "sent":
            t = mark_sent(pipe, args.contact, args.channel, _today(args.date))
            save(args.pipeline, pipe)
            if t.get("invite"):
                print("Logged as sent. A LinkedIn invitation gets no follow-up: if they accept, message them "
                      "with draft --connected.")
            else:
                print("Logged as sent. Next follow-up: %s" % (t["next_followup"] or "none (stop rules)"))
            return 0
        if args.cmd == "reply":
            t, declined, stop = log_reply(pipe, args.contact, args.channel, args.text, _today(args.date),
                                          args.declined, args.stop)
            save(args.pipeline, pipe)
            if stop:
                print("They asked to stop. Marked do not contact, forever. Thread closed.")
            elif declined:
                print("That reads as a no. Thread marked declined: no more messages on it. If the user reads it "
                      "differently (\"not now, but next month works\"), `reopen` undoes it.")
            else:
                print("Reply logged. Thread is %s. Draft an answer for the user's yes." % t["status"])
            return 0
        if args.cmd == "book":
            t = book(pipe, args.contact, args.channel, args.when, args.minutes, args.where, args.reply, args.role)
            save(args.pipeline, pipe)
            print("Booked: %s, %d minutes, %s. Create the invite in the user's calendar now (they said yes)."
                  % (t["booked"]["when"], args.minutes, args.where or "place in the invite"))
            return 0
        if args.cmd == "reopen":
            reopen(pipe, args.contact, args.channel)
            save(args.pipeline, pipe)
            print("Reopened as replied.")
            return 0
        if args.cmd == "close":
            close_thread(pipe, args.contact, args.channel, args.reason)
            save(args.pipeline, pipe)
            print("Closed.")
            return 0
        if args.cmd == "due":
            today = _today(args.today)
            d_ = due(pipe, today)
            if args.close:
                for cid, channel in d_["close_keys"]:
                    close_thread(pipe, cid, channel, "stop rules")
                save(args.pipeline, pipe)
            if args.json:
                print(json.dumps(d_, indent=2))
            else:
                sys.stdout.write(render_due(d_, today))
            return 0
        if args.cmd == "show":
            sys.stdout.write(show(pipe, args.contact))
            return 0
    except OutreachError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
