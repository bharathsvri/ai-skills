#!/usr/bin/env python3
"""Follow-ups that keep threads warm without ever pestering anyone. Standard library only.

Reads hunter/pipeline.json (the schema hunter-tracker owns) and works out what is due
today across conversations and applications, with the same stop rules as the
connector. It drafts; it never sends.

  due       what is due today: follow-ups, replies waiting on you, drafts waiting for
            your yes, application check-ins, next steps, and who is stopped and why
  draft     fills a polite template (templates.json) for one contact or role
  record    logs a follow-up AFTER it went out, with your yes word for word; refuses
            when a stop rule applies or the reply is not an explicit yes
  reply     logs their answer (a "no" or a stop request closes every thread with them)
  stop      marks a person do-not-contact, forever
  templates lists the templates

    python3 followup.py due --today 2026-10-15
    python3 followup.py draft --contact maya-c-google --template nudge-1 --today 2026-10-15
    python3 followup.py record --contact maya-c-google --channel email --text-file f.txt \
        --approval "yes" --today 2026-10-15
    python3 followup.py reply --contact maya-c-google --channel email --text "Happy to chat" --today 2026-10-16
    python3 followup.py stop --contact maya-c-google --today 2026-10-16

Stop rules, per PERSON (every channel counts together):
  1. Stop at the first "no" or any sign of disinterest, and honour a stop request forever.
  2. At most 2 follow-ups after the first message (several first messages sent the same
     day, an email and a LinkedIn request, count as one opening).
  3. Nothing after 21 days of silence, counted from their last reply, or from the
     first message when they never replied (day 21 is the last day a message may go).
  A pending LinkedIn invitation ("invite": true on the thread) gets no follow-up.
Cadence: follow-up 1 is due 3 days after the opening (the reel: Day 1, Day 4),
follow-up 2 is due 7 days after follow-up 1. A thread's own next_followup date, when
set (by hunter-connector or by you), replaces the cadence date. The stop rules always win.
"""

import argparse
import datetime
import json
import os
import re
import sys

DEFAULT_FILE = os.path.join("hunter", "pipeline.json")
DEFAULT_PROFILE = os.path.join("hunter", "profile.json")
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(HERE, "templates.json")

MAX_FOLLOWUPS = 2
SILENCE_DAYS = 21
GAP_FIRST = 3
GAP_NEXT = 7
APP_CHECKIN_DAYS = 10

STAGES = ("saved", "applied", "screen", "interview", "onsite", "offer", "rejected", "withdrawn")
ACTIVE = ("saved", "applied", "screen", "interview", "onsite", "offer")
THREAD_STATUSES = ("drafted", "sent", "replied", "booked", "declined", "closed")

STAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
# A "no" or any sign of disinterest. One match closes every thread with that person.
NO_PATTERNS = [r"\bnot interested\b", r"\bno,? thanks?\b", r"\bno thank you\b", r"\bunsubscribe\b",
               r"\bremove me\b", r"\b(please )?stop (emailing|messaging|contacting|reaching out)\b",
               r"\bdo ?n[o']?t (contact|email|message|reach out)\b", r"\bplease stop\b",
               r"\bnot (a good )?fit\b", r"\bnot hiring\b", r"\b(role|position) (has been|is) (filled|closed)\b",
               r"\bnot (moving|move) forward\b", r"\bdecided to (go|move) (with|forward with) (another|other)\b",
               r"\bnot at this time\b", r"\bleave me alone\b", r"\bno longer (interested|hiring)\b",
               r"\bpass on this\b", r"\bnot open to\b", r"\bplease don'?t\b", r"\btake me off\b",
               r"\bnot the right person\b", r"\bnot looking\b", r"\bnot (right )?now\b", r"\btoo busy\b",
               r"\bno bandwidth\b", r"\bcan'?t help\b", r"\bno (open )?(roles|openings|headcount)\b"]
NO_RE = re.compile("|".join(NO_PATTERNS), re.I)
DNC_RE = re.compile(r"do not contact", re.I)
INTERVIEW_RE = re.compile(r"\b(interview|onsite|on-site|screen|chat|call|coffee|meeting|loop)\b", re.I)

YES_WORDS = ("yes", "y")
BATCH_WORDS = {"all", "every", "everyone", "everybody", "everything", "rest", "remaining", "them", "both",
               "bulk", "batch", "each", "others"}
DOUBT_WORDS = {"no", "not", "dont", "don't", "wait", "cancel", "stop", "but", "maybe", "later", "hold",
               "unless", "if", "tomorrow"}


class FollowupError(Exception):
    pass


# ---------------------------------------------------------------- basics

def parse_day(s, what="date"):
    if isinstance(s, datetime.date):
        return s
    m = STAMP_RE.match(str(s or "").strip())
    if not m:
        raise FollowupError("%s must be YYYY-MM-DD, got %r" % (what, s))
    try:
        return datetime.date(*[int(x) for x in m.group(1).split("-")])
    except ValueError:
        raise FollowupError("%s is not a real date: %r" % (what, s))


def day_or_none(s):
    if s in (None, ""):
        return None
    try:
        return parse_day(s)
    except FollowupError:
        return None


def today_from(arg):
    return parse_day(arg, "--today") if arg else datetime.date.today()


def load(path):
    if not os.path.exists(path):
        raise FollowupError("no pipeline at %s (hunter-tracker: pipeline.py init)" % path)
    with open(path, encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as e:
            raise FollowupError("%s is not valid JSON: %s" % (path, e))
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


def load_templates(path=TEMPLATES):
    with open(path, encoding="utf-8") as fh:
        t = json.load(fh)
    return {k: v for k, v in t.items() if not k.startswith("_")}


def contact_by_id(data, cid):
    for c in data["contacts"]:
        if c.get("id") == cid:
            return c
    raise FollowupError("no contact with id %r in the pipeline" % cid)


def role_by_id(data, rid):
    for r in data["roles"]:
        if r.get("id") == rid:
            return r
    raise FollowupError("no role with id %r in the pipeline" % rid)


def first_name(name):
    name = (name or "").strip()
    return name.split()[0] if name else "there"


# ---------------------------------------------------------------- the rules

def sent_messages(thread):
    """Messages that really went out or came in. A pending draft is not a sent message:
    a message flagged "draft": true, or (when no message carries a flag) the last
    outgoing message of a thread whose status is "drafted"."""
    msgs = [m for m in (thread.get("messages") or []) if isinstance(m, dict)]
    if any("draft" in m for m in msgs):
        return [m for m in msgs if not m.get("draft")]
    if thread.get("status") == "drafted":
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i].get("direction") == "out":
                return msgs[:i] + msgs[i + 1:]
    return msgs


def has_pending_draft(thread):
    """A draft waiting for the user's yes: hunter-connector keeps it in the thread's
    "draft" object; a hand-written pipeline may flag a message or use status drafted."""
    if isinstance(thread.get("draft"), dict) and thread["draft"].get("text"):
        return True
    msgs = [m for m in (thread.get("messages") or []) if isinstance(m, dict)]
    if any(m.get("draft") for m in msgs):
        return True
    return thread.get("status") == "drafted"


def said_no(data, cid):
    """Why this person must never get another message, or None."""
    c = next((c for c in data["contacts"] if c.get("id") == cid), {})
    if c.get("do_not_contact") or DNC_RE.search(c.get("notes") or ""):
        return "marked do not contact"
    for t in data["threads"]:
        if t.get("contact_id") != cid:
            continue
        if t.get("status") == "declined":
            return "said no (%s thread declined)" % t.get("channel")
        for m in t.get("messages") or []:
            if m.get("direction") == "in":
                hit = NO_RE.search(m.get("text") or "")
                if hit:
                    return 'said "%s" on %s' % (hit.group(0), str(m.get("date"))[:10])
    return None


def contact_state(data, cid, today):
    """The follow-up state for one person across all their threads.

    state: due | waiting | draft | your-turn | stopped | done | none
    """
    threads = [t for t in data["threads"] if t.get("contact_id") == cid]
    st = {"contact_id": cid, "state": "none", "reason": "", "due": None, "followup": None,
          "channel": None, "role_id": None, "opening": None, "followups_sent": 0}
    if not threads:
        st["reason"] = "no conversation yet"
        return st
    no = said_no(data, cid)
    drafts = [t for t in threads if has_pending_draft(t)]
    if no:
        st.update(state="stopped", reason=no + ": never message again" +
                  ("; do NOT send the pending draft" if drafts else ""))
        return st
    if any(t.get("status") == "booked" for t in threads):
        st.update(state="done", reason="chat booked: no follow-ups, prepare for it")
        return st
    live = [t for t in threads if t.get("status") not in ("closed", "declined")]
    if not live:
        st.update(state="done", reason="every thread is closed")
        return st

    msgs = []
    for t in threads:
        for i, m in enumerate(sent_messages(t)):
            d = day_or_none(m.get("date"))
            if d:
                msgs.append((d, str(m.get("date")), m.get("direction"), t))
    msgs.sort(key=lambda x: (x[0], x[1]))
    if not msgs:
        if drafts:
            t = drafts[0]
            st.update(state="draft", reason="first message drafted, waiting for your yes",
                      channel=t.get("channel"), role_id=t.get("role_id"))
        else:
            st["reason"] = "no messages yet"
        return st

    last_in = max((i for i, m in enumerate(msgs) if m[2] == "in"), default=-1)
    silence_from = msgs[last_in][0] if last_in >= 0 else None
    if msgs[-1][2] == "in":
        t = msgs[-1][3]
        st.update(state="your-turn", reason="they replied on %s: answer them (no follow-up rules apply)" % msgs[-1][0].isoformat(),
                  channel=t.get("channel"), role_id=t.get("role_id"))
        return st

    stretch = [m for m in msgs[last_in + 1:] if m[2] == "out"]
    opening = stretch[0][0]
    silence_from = silence_from or opening
    followups = [m for m in stretch if m[0] > opening]
    k = len(followups)
    last_out = stretch[-1]
    nudgeable = [m for m in stretch if not m[3].get("invite")]
    st.update(opening=opening.isoformat(), followups_sent=k)
    if not nudgeable:
        t = last_out[3]
        st.update(state="waiting", channel=t.get("channel"), role_id=t.get("role_id"),
                  reason="LinkedIn invitation pending: no follow-up until they accept")
        return st
    pick = next((m for m in reversed(nudgeable) if m[3].get("channel") == "email"), nudgeable[-1])
    st.update(channel=pick[3].get("channel"), role_id=pick[3].get("role_id"))
    if k >= MAX_FOLLOWUPS:
        st.update(state="stopped", reason="%d follow-ups sent with no reply: stop here" % k)
        return st
    if (today - silence_from).days > SILENCE_DAYS:
        st.update(state="stopped", reason="%d days of silence since %s: let it go" % (
            (today - silence_from).days, silence_from.isoformat()))
        return st
    cadence = opening + datetime.timedelta(days=GAP_FIRST) if k == 0 else last_out[0] + datetime.timedelta(days=GAP_NEXT)
    explicit = [day_or_none(t.get("next_followup")) for t in live if t.get("next_followup") and not t.get("invite")]
    explicit = [d for d in explicit if d]
    due = min(explicit) if explicit else cadence
    if (due - silence_from).days > SILENCE_DAYS:
        st.update(state="stopped", reason="the next follow-up would land %d days into the silence (limit %d): no more" % (
            (due - silence_from).days, SILENCE_DAYS))
        return st
    st.update(due=due.isoformat(), followup=k + 1)
    if drafts:
        st.update(state="draft", reason="follow-up %d of %d drafted, waiting for your yes%s" % (
            k + 1, MAX_FOLLOWUPS, "" if due <= today else " (not due until %s)" % due.isoformat()))
    elif due <= today:
        st.update(state="due", reason="follow-up %d of %d: opened %s, no reply" % (k + 1, MAX_FOLLOWUPS, opening.isoformat()))
    else:
        st.update(state="waiting", reason="follow-up %d of %d due %s" % (k + 1, MAX_FOLLOWUPS, due.isoformat()))
    return st


def application_items(data, today):
    """Applications with no news and next steps that are due."""
    items = []
    names = {c.get("id"): c for c in data["contacts"]}
    for r in data["roles"]:
        if r.get("stage") not in ACTIVE:
            continue
        nd = day_or_none(r.get("next_date"))
        if nd and nd <= today:
            step = r.get("next_step") or "next step"
            item = {"kind": "next-step", "role_id": r.get("id"), "company": r.get("company"),
                    "title": r.get("title"), "date": nd.isoformat()}
            if INTERVIEW_RE.search(step) and nd == today:
                item["what"] = "today: %s. Afterwards, a thank-you within 24 hours (template %s)" % (
                    step, "after-coffee" if "coffee" in step.lower() else "thank-you")
            elif INTERVIEW_RE.search(step) and (today - nd).days == 1:
                item["what"] = "%s was yesterday: send the thank-you today (template %s)" % (
                    step, "after-coffee" if "coffee" in step.lower() else "thank-you")
            elif nd == today:
                item["what"] = "today: %s" % step
            else:
                item["what"] = "%s was due %s (%d days ago): do it or update the step in the tracker" % (
                    step, nd.isoformat(), (today - nd).days)
            items.append(item)
            continue
        if r.get("stage") != "applied" or nd:
            continue
        ad = day_or_none(r.get("applied"))
        if not ad or (today - ad).days < APP_CHECKIN_DAYS:
            continue
        touched = False
        for t in data["threads"]:
            if t.get("role_id") == r.get("id"):
                for m in sent_messages(t):
                    d = day_or_none(m.get("date"))
                    if d and d >= ad:
                        touched = True
        if touched:
            continue  # the thread's own follow-up rules cover it
        company = str(r.get("company") or "").lower()
        people = [c for c in data["contacts"] if str(c.get("company") or "").lower() == company
                  and not said_no(data, c.get("id"))]
        item = {"kind": "application", "role_id": r.get("id"), "company": r.get("company"),
                "title": r.get("title"), "date": ad.isoformat()}
        if people:
            p = people[0]
            item["contact_id"] = p.get("id")
            item["what"] = ("applied %s (%d days, no news): one check-in to %s (template application-check-in)"
                            % (ad.isoformat(), (today - ad).days, p.get("name")))
        else:
            item["what"] = ("applied %s (%d days, no news) and no contact at %s yet: /hunter-connector finds "
                            "the hiring manager" % (ad.isoformat(), (today - ad).days, r.get("company")))
        items.append(item)
    items.sort(key=lambda x: (x["date"], x["role_id"] or ""))
    return items


def due_report(data, today):
    people = []
    for c in data["contacts"]:
        st = contact_state(data, c.get("id"), today)
        st["name"] = c.get("name")
        st["company"] = c.get("company")
        if st["state"] != "none":
            people.append(st)
    order = {"due": 0, "your-turn": 1, "draft": 2, "waiting": 3, "stopped": 4, "done": 5}
    people.sort(key=lambda s: (order.get(s["state"], 9), s.get("due") or "", s["contact_id"] or ""))
    return {"today": today.isoformat(), "people": people, "applications": application_items(data, today)}


def render_due(rep):
    out = ["Follow-ups for %s (drafts only: nothing goes out without your yes)" % rep["today"]]
    groups = (("due", "DUE NOW"), ("your-turn", "YOUR TURN (they replied)"), ("draft", "DRAFTS WAITING FOR YOUR YES"),
              ("waiting", "WAITING"), ("stopped", "STOPPED (stop rules)"), ("done", "DONE"))
    for key, title in groups:
        rows = [p for p in rep["people"] if p["state"] == key]
        if not rows:
            continue
        out.append("")
        out.append(title)
        for p in rows:
            ch = " by %s" % p["channel"] if p.get("channel") else ""
            out.append("  %s (%s)%s: %s" % (p["name"], p["company"], ch, p["reason"]))
            if key == "due":
                tpl = "nudge-1" if p["followup"] == 1 else "nudge-2"
                out.append("    draft it: followup.py draft --contact %s --template %s" % (p["contact_id"], tpl))
            if key == "your-turn":
                out.append("    draft it: followup.py draft --contact %s --template confirm-time (if they offered a time)" % p["contact_id"])
    if rep["applications"]:
        out.append("")
        out.append("APPLICATIONS AND NEXT STEPS")
        for a in rep["applications"]:
            out.append("  %s, %s: %s" % (a["company"], a["title"], a["what"]))
    if len(out) == 1:
        out.append("")
        out.append("Nothing due. Every thread is waiting on its date or closed.")
    return "\n".join(out)


# ---------------------------------------------------------------- yes

def parse_yes(reply):
    """(ok, why). Only an explicit yes for this one message counts."""
    text = (reply or "").strip().lower()
    if not text:
        return False, "no reply recorded"
    if "?" in text:
        return False, "a question is not a yes"
    words = re.findall(r"[a-z']+", text)
    if not words or words[0] not in YES_WORDS:
        return False, 'the reply must start with "yes"'
    if BATCH_WORDS & set(words):
        return False, "one yes covers one message; ask again for each"
    if DOUBT_WORDS & set(words):
        return False, "the reply has a condition or a doubt in it"
    return True, "explicit yes"


# ---------------------------------------------------------------- drafting

def profile_name(path):
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return (json.load(fh) or {}).get("name")
        except (ValueError, OSError):
            return None
    return None


def fill(template, values):
    out = template
    missing = []
    for key in re.findall(r"\{([a-z_]+)\}", template):
        v = values.get(key)
        if v in (None, ""):
            missing.append(key)
            out = out.replace("{%s}" % key, "[fill: %s]" % key)
        else:
            out = out.replace("{%s}" % key, str(v))
    return out, sorted(set(missing))


def draft(data, templates, name, contact_id=None, role_id=None, me=None, hook=None, subject=None,
          day=None, today=None):
    if name not in templates:
        raise FollowupError("no template %r (have: %s)" % (name, ", ".join(sorted(templates))))
    c = contact_by_id(data, contact_id) if contact_id else {}
    if contact_id:
        no = said_no(data, contact_id)
        if no:
            raise FollowupError("%s %s: nothing is drafted for them, ever" % (c.get("name"), no))
        if today is not None and name in ("nudge-1", "nudge-2"):
            st = contact_state(data, contact_id, today)
            if st["state"] == "stopped":
                raise FollowupError("stop rule for %s: %s" % (c.get("name"), st["reason"]))
    r = {}
    if role_id:
        r = role_by_id(data, role_id)
    elif contact_id:
        rids = [t.get("role_id") for t in data["threads"] if t.get("contact_id") == contact_id and t.get("role_id")]
        if rids:
            r = role_by_id(data, rids[-1])
    ad = day_or_none(r.get("applied"))
    values = {"first": first_name(c.get("name")) if c else None, "role": r.get("title"),
              "company": r.get("company") or c.get("company"),
              "applied": "%s %d" % (ad.strftime("%B"), ad.day) if ad else None,
              "my_first": first_name(me) if me else None, "my_name": me, "hook": hook,
              "subject": subject, "day": day}
    tpl = templates[name]
    subj, m1 = fill(tpl.get("subject", ""), values)
    body, m2 = fill(tpl.get("body", ""), values)
    return {"template": name, "use": tpl.get("use"), "subject": subj, "body": body,
            "missing": sorted(set(m1 + m2 + re.findall(r"\[fill: ([^\]]+)\]", tpl.get("body", ""))))}


# ---------------------------------------------------------------- writing

def find_thread(data, cid, channel, role_id):
    cands = [t for t in data["threads"] if t.get("contact_id") == cid and t.get("channel") == channel]
    if role_id:
        exact = [t for t in cands if t.get("role_id") == role_id]
        if exact:
            return exact[-1]
        return None
    return cands[-1] if cands else None


def record(data, cid, channel, text, approval, today, role_id=None):
    """Log a message that went out after the user's yes. Returns (ok, message)."""
    ok, why = parse_yes(approval)
    if not ok:
        return False, "Not recorded: %s. Ask again, for this one message." % why
    c = contact_by_id(data, cid)
    st = contact_state(data, cid, today)
    no = said_no(data, cid)
    if no:
        return False, "Not recorded: %s %s. Nothing more goes to them." % (c.get("name"), no)
    if st["state"] == "stopped":
        return False, "Not recorded: stop rule, %s." % st["reason"]
    if not text or not text.strip():
        return False, "Not recorded: the message text is empty."
    t = find_thread(data, cid, channel, role_id)
    if t is None:
        t = {"contact_id": cid, "role_id": role_id, "channel": channel, "messages": [], "status": "sent",
             "next_followup": None}
        data["threads"].append(t)
    if isinstance(t.get("draft"), dict):
        t.pop("draft", None)  # hunter-connector's draft just went out: the sent text replaces it
        t.pop("approval", None)
    elif has_pending_draft(t):
        # the draft that just went out: drop it, the sent text replaces it
        msgs = t.get("messages") or []
        flagged = [i for i, m in enumerate(msgs) if m.get("draft")]
        if flagged:
            for i in reversed(flagged):
                msgs.pop(i)
        else:
            for i in range(len(msgs) - 1, -1, -1):
                if msgs[i].get("direction") == "out":
                    msgs.pop(i)
                    break
    t.setdefault("messages", []).append({"date": today.isoformat(), "direction": "out", "text": text.strip()})
    if t.get("status") not in ("booked",):
        t["status"] = "sent"
    after = contact_state(data, cid, today)
    for tt in data["threads"]:
        if tt.get("contact_id") == cid and tt.get("status") not in ("booked", "declined", "closed"):
            tt["next_followup"] = None
    if after["state"] in ("waiting", "due") and after.get("due"):
        t["next_followup"] = after["due"]
    if st["state"] == "your-turn":
        kind = "reply"
    elif st["state"] == "done":
        kind = "message"
    elif st["state"] in ("none", "draft") and not st.get("opening"):
        kind = "first message"
    else:
        kind = "follow-up %d of %d" % (st.get("followup") or (st["followups_sent"] + 1), MAX_FOLLOWUPS)
    nxt = ("next follow-up %s" % t["next_followup"]) if t.get("next_followup") else "no more follow-ups scheduled"
    return True, "Recorded the %s to %s by %s on %s (%s)." % (kind, c.get("name"), channel, today.isoformat(), nxt)


def log_reply(data, cid, channel, text, today, role_id=None):
    c = contact_by_id(data, cid)
    t = find_thread(data, cid, channel, role_id)
    if t is None:
        t = {"contact_id": cid, "role_id": role_id, "channel": channel, "messages": [], "status": "replied",
             "next_followup": None}
        data["threads"].append(t)
    t.setdefault("messages", []).append({"date": today.isoformat(), "direction": "in", "text": text.strip()})
    if NO_RE.search(text or ""):
        for tt in data["threads"]:
            if tt.get("contact_id") == cid:
                tt["status"] = "declined"
                tt["next_followup"] = None
        return "Logged. %s said no: every thread with them is closed for good. Thank them once only if you want to, then stop." % c.get("name")
    if t.get("status") != "booked":
        t["status"] = "replied"
    for tt in data["threads"]:
        if tt.get("contact_id") == cid:
            tt["next_followup"] = None
    return "Logged the reply from %s. Your turn: answer them (no follow-up rules apply to a reply)." % c.get("name")


def mark_stop(data, cid, today, said=None):
    c = contact_by_id(data, cid)
    threads = [t for t in data["threads"] if t.get("contact_id") == cid]
    if said:
        if threads:
            threads[-1].setdefault("messages", []).append({"date": today.isoformat(), "direction": "in", "text": said})
    for t in threads:
        t["status"] = "declined"
        t["next_followup"] = None
    note = "%s: DO NOT CONTACT (asked to stop). Honour forever." % today.isoformat()
    c["notes"] = ((c.get("notes") or "").rstrip() + "\n" + note).strip()
    return "%s is marked do not contact. %d thread(s) closed. Nothing will be drafted for them again." % (c.get("name"), len(threads))


# ---------------------------------------------------------------- CLI

def _text_arg(a):
    if getattr(a, "text_file", None):
        with open(a.text_file, encoding="utf-8") as fh:
            return fh.read()
    return a.text


def build_parser():
    p = argparse.ArgumentParser(description="Polite follow-ups with stop rules, from hunter/pipeline.json. Drafts only.")
    p.add_argument("--file", default=DEFAULT_FILE, help="pipeline file (default hunter/pipeline.json)")
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--file", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        sp.add_argument("--today", help="YYYY-MM-DD (default: the computer's date)")

    sp = sub.add_parser("due", help="what is due today")
    common(sp)
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("draft", help="fill a template for one contact or role")
    common(sp)
    sp.add_argument("--template", required=True)
    sp.add_argument("--contact")
    sp.add_argument("--role")
    sp.add_argument("--me", help="your name (default: name in hunter/profile.json)")
    sp.add_argument("--profile", default=DEFAULT_PROFILE)
    sp.add_argument("--hook", help="one new, specific, true line")
    sp.add_argument("--subject", help="the subject of the first email, for Re: lines")
    sp.add_argument("--day", help="for confirm-time: the day and time they offered")
    sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("record", help="log a message that went out after your yes")
    common(sp)
    sp.add_argument("--contact", required=True)
    sp.add_argument("--channel", required=True)
    sp.add_argument("--role")
    sp.add_argument("--text")
    sp.add_argument("--text-file")
    sp.add_argument("--approval", required=True, help="the user's reply, word for word")

    sp = sub.add_parser("reply", help="log their answer")
    common(sp)
    sp.add_argument("--contact", required=True)
    sp.add_argument("--channel", required=True)
    sp.add_argument("--role")
    sp.add_argument("--text")
    sp.add_argument("--text-file")

    sp = sub.add_parser("stop", help="mark a person do-not-contact, forever")
    common(sp)
    sp.add_argument("--contact", required=True)
    sp.add_argument("--said", help="their words, logged as their last message")

    sp = sub.add_parser("templates", help="list the templates")
    common(sp)
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if not a.cmd:
        p.print_help()
        return 2
    try:
        if a.cmd == "templates":
            for k, v in load_templates().items():
                print("%-22s %s" % (k, v.get("use", "")))
            return 0
        data = load(a.file)
        today = today_from(a.today)
        if a.cmd == "due":
            rep = due_report(data, today)
            print(json.dumps(rep, indent=2) if a.json else render_due(rep))
            return 0
        if a.cmd == "draft":
            if not a.contact and not a.role:
                raise FollowupError("give --contact or --role")
            me = a.me or profile_name(a.profile)
            d = draft(data, load_templates(), a.template, a.contact, a.role, me, a.hook, a.subject, a.day, today)
            if a.json:
                print(json.dumps(d, indent=2, ensure_ascii=False))
            else:
                print("DRAFT (%s). Show it to the user; it goes out only after their yes.\n" % d["template"])
                print("Subject: " + d["subject"])
                print("")
                print(d["body"])
                if d["missing"]:
                    print("")
                    print("Fill in before showing: " + ", ".join(d["missing"]))
            return 0
        if a.cmd == "record":
            ok, msg = record(data, a.contact, a.channel, _text_arg(a), a.approval, today, a.role)
            print(msg)
            if ok:
                save(a.file, data)
            return 0 if ok else 1
        if a.cmd == "reply":
            text = _text_arg(a)
            if not text:
                raise FollowupError("give --text or --text-file")
            msg = log_reply(data, a.contact, a.channel, text, today, a.role)
            save(a.file, data)
            print(msg)
            return 0
        if a.cmd == "stop":
            msg = mark_stop(data, a.contact, today, a.said)
            save(a.file, data)
            print(msg)
            return 0
    except FollowupError as e:
        print("followup: " + str(e), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
