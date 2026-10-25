# The X agent skill

Eleven Claude skills that run an X account. Free, MIT, no signup, no API key,
nothing to connect.

They write your posts, comment on other people's threads, handle your replies,
fix your profile and plan your week. And one of them is the virality skill: it
finds the posts that are actually outperforming in your niche, breaks each one
down into hook, structure and format, and recreates the winners in your voice,
for your audience.

Under the skills are nine tools that actually run. One counts a post the way X
counts it (links are 23, emoji are 2). One scores your first line before you
post it. One cuts a draft into a thread that fits. One reads X's own published
ranking code and tells you what it rewards this week. One reads your analytics
export and tells you what worked, with the sample size on every claim.

**Nothing is posted until you approve it.** These skills write. You post.

## Install

Paste this into Claude:

```
https://github.com/Jakeschincariol/x-agent-skill

Install this skill, then confirm /x-post works.
```

Or do it yourself, in Claude Code:

```bash
git clone https://github.com/Jakeschincariol/x-agent-skill.git
cp -r x-agent-skill/skills/x-* ~/.claude/skills/
```

Or as a plugin:

```
/plugin marketplace add Jakeschincariol/x-agent-skill
/plugin install x-agent
```

Project-local instead of global: copy the same folders into your repo's
`.claude/skills/`. No Claude Code at all? Paste any single `SKILL.md` at the
top of a chat and it runs as a mode. You lose the Python tools, which is most
of the point of `/x-post`, `/x-viral` and `/x-human`, but the rest works.

Then spend ten minutes on [`templates/voice.md`](templates/voice.md). Copy it
to `~/.claude/x/voice.md` and fill it in, or paste five of your own posts into
Claude and say "write my voice.md from these". Every skill reads that file.
Skip it and everything comes out sounding like everyone else on the timeline.

## The eleven

| command | | what it does |
| --- | --- | --- |
| `/x-post` | Post Writer | One idea into a post. Three hooks from [21 formulas](skills/x-post/hooks.json), scored, one draft, counted the way X counts, humanized. |
| `/x-comment` | Comment Drafter | Replies on other people's posts and threads. Nine types, picked by what the post is. Reply or quote, decided first. |
| `/x-profile` | Profile Optimizer | Scores your profile against a [12-part rubric](skills/x-profile/rubric.json) out of 100, then rewrites bio, pinned post and header in fix-first order. |
| `/x-reply` | Reply Handler | The replies under your own posts, sorted into lead / substance / peer / question / support / noise, then answered in that order. |
| `/x-plan` | Content Planner | The week: what to post, which format, when, and the 10 accounts to engage with. |
| `/x-viral` | Virality Engine | Finds what is outperforming in your niche, ranks it by multiple over each account's own median, breaks down hook, structure and format, recreates the top three for you. |
| `/x-thread` | Thread Builder | Thread, long post or single post, decided first. Then post 1, one idea per post, cut to fit, and a last post people act on. |
| `/x-human` | Humanizer | Strips em dashes, slop and invisible characters, then scores the draft on a five-check panel. |
| `/x-repurpose` | Repurposer | One video, podcast, newsletter or LinkedIn post into a week of X posts and a thread. |
| `/x-dm` | DM Handler | The first message, two follow-ups, and triage for your inbox and message requests. |
| `/x-audit` | Account Audit | Reads your analytics export. Ranks by engagement, replies and shares per impression, not by impressions. |

## The nine tools

Every one runs on a clean Python 3 with no dependencies. Seven never touch the
network. `pull.py` calls X's documented oEmbed API and `weights.py` reads a
public GitHub file; neither needs an account or a key.

```bash
python3 skills/x-post/count.py post.txt                   # X's weighted count + six lints
python3 skills/x-post/hookscore.py hooks.txt              # score and rank first lines, name the formula
python3 skills/x-thread/thread.py draft.txt --number      # cut a draft into a thread that fits
python3 skills/x-human/humanize.py draft.txt --report     # strip the fingerprint
python3 skills/x-human/detect.py before.txt after.txt     # five-check panel, before and after
python3 skills/x-viral/pull.py urls.txt > swipe.tsv       # post URLs you picked -> text, format, date
python3 skills/x-viral/swipe.py swipe.tsv                 # outliers, broken down, as a swipe file
python3 skills/x-audit/audit.py analytics.csv             # what worked, with n on every claim
python3 skills/x-plan/weights.py                          # what X's ranker rewards, live from X's code
```

### Counting the way X counts

X does not count characters. It counts weighted characters: every link is 23
however long it is, every emoji is 2 (a family emoji built from seven code
points is still 2), Chinese, Japanese and Korean are 2, and "…" is 2, which is
more than the three dots it replaces. `count.py` implements those rules, then
draws the post the way the timeline shows it:

```
  WHAT FITS
  +------------------------------------------------------+
  | Most people use AI to post more. I used it to post   |
  | less.                                                |
  |                                                      |
  | In March I cut from 3 posts a day to 1. Followers    |
  | went from 2,100 to 6,800 by August.                  |
  |                                                      |
  | The system: one idea a day, drafted with Claude, cut |
  | in half by me, and I'm there for the first hour of   |
  | replies.                                             |
  |                                                      |
  | Showing up beats post                                |
  +------------------------------------ cut here, 4 over +

  FAIL  LENGTH      284 / 280, 4 over. X will not let you post it.
  PASS  FIRST LINE  56 characters, reads in one glance
  PASS  LINKS       none
  PASS  HASHTAGS    0
  PASS  MENTIONS    0
  PASS  ENDING      no reflex bait
```

With `--premium` the limit is 25,000 and the box shows where the timeline cuts
a long post to "Show more", at about 280. It also flags an @mention past that
point, because X does not notify it.

### The hook

On X the first line is not the start of the post. It is most of the post.
`hookscore.py` scores it on five properties (length, specificity, stakes,
whether the payoff is up front, who it is aimed at), flags the dealbreakers,
and names which of the 21 formulas it uses:

```
HOOK RANKING
==============================================================================
-> 100.0 STRONG  Nobody tells you your first 1,000 followers come from rep...
        #6 Nobody Tells You  ·  weakest: LENGTH (100)
    78.4 STRONG  I posted every day for 90 days. Here's what actually move...
        #2 Number Reveal  ·  weakest: FRONTLOAD (70)
    52.2 OK      The hottest new marketing hire is a skill file.
        #7 The Hottest New  ·  weakest: SPECIFICITY (15)
    36.2 WEAK    Hey guys, here are some thoughts on growing on X
        #21 The One-Liner  ·  weakest: STAKES (20)
        dealbreaker: Greeting. Nobody opened X to be greeted.
     4.8 WEAK    A thread 🧵
        #16 Thread Promise  ·  weakest: FRONTLOAD (0)
        dealbreaker: Opens on the word "thread". That is packaging. Put the
                     payoff in line 1 and let X's own UI say it is a thread.
```

Every formula in [`hooks.json`](skills/x-post/hooks.json) carries a template,
a filled example, what it is for, how it usually gets ruined, and a regex, so
the same 21 names describe a hook you are writing and a hook you found in
someone else's feed. That is what lets `/x-viral` say "the top third of your
niche is The Hottest New and Field Report" instead of "posts that did well".

### The virality engine

```bash
python3 skills/x-viral/pull.py urls.txt > swipe.tsv
# fill in the views column from the posts, they are public on every post
python3 skills/x-viral/swipe.py swipe.tsv --out ~/.claude/x/swipe.md
```

Raw numbers are not evidence. An account with 900,000 followers doing 400,000
views had an ordinary Tuesday; an account with 6,000 doing the same found
something copyable. So `swipe.py` ranks on the **outlier multiple**, each
post's views over its own account's median, computed from the 10 to 15 posts
you collected per account. Accounts with too few posts are skipped instead of
ranked on noise. Then each post gets broken down:

- **hook**: which of the 21 formulas, and its score
- **structure**: one line, one paragraph, short lines, a list, a long post, a thread
- **format**: text, media, link, long

It compares the top third with the bottom third on all three, lists the hooks
it could not classify (read those, they are where a new formula is hiding) and
writes a swipe file with the reusable shape of each winner. `/x-viral` then
recreates the top three in your voice: the found post's structure, none of its
words.

### What X rewards, from X

X open-sourced its current recommendation system in January 2026 and has
published the production ranking weights in it since August. They move: two
of them changed in the week this pack was written. So `weights.py` reads the
file live and prints it with the date of its last change:

```
X FOR YOU RANKER  ·  action weights  ·  live from GitHub, last changed 2026-09-29 (commit a707cc2)
==============================================================================
REWARDED                                  weight   vs a like
  share by copying the link                     20     40.0x
  + added to a reply between mutuals            15     30.0x
  reply                                          5     10.0x
  share by DM                                    5     10.0x
  quote                                          5     10.0x
  follow the author                              4      8.0x
  share (any)                                    2      4.0x
  repost                                         1      2.0x
  like                                         0.5      1.0x
  ...
PUNISHED
  report                                      -234
  mute the author                            -58.8
  "not interested"                          -47.52
  block the author                           -31.2
```

Read it the way X's own comment in that file says to: each weight multiplies
the *predicted probability* of an action for a given viewer, not a count of
actions, so "a reply is worth ten likes" is the wrong conclusion. The right
one is the direction. Write things people reply to, quote and send to one
friend. Do not write the things people mute.

### The humanizer

`humanize.py` strips invisible characters, fixes typography (em dash to comma,
curly to straight) and replaces 176 stock words and phrases from
[`slop.json`](skills/x-human/slop.json), including an X block: "if you found
this thread helpful", "RT if you agree", "let's dive in". It keeps the
invisible characters that emoji need, so 👨‍💻 stays one emoji. Structural tells
("A thread 🧵" as the hook, "it's not just X, it's Y", a pile of hashtags) are
flagged, not rewritten, because changing the shape of a sentence needs
judgement.

`detect.py` scores five checks: burstiness, specificity, slop density,
fingerprint, voice. A post of one or two sentences cannot show burstiness or a
specificity density, so those sit out as n/a and the output says it scored on
3 of 5 rather than pretending.

A deliberately bad post, the automatic passes, then a rewrite by hand:

```
  HUMAN SCORE   #####...................  19.6   FLAGGED     the original
  HUMAN SCORE   ##########..............  42.9   FLAGGED     after humanize.py alone
  HUMAN SCORE   #####################...  85.7   PASS        after rewriting the flagged lines
```

The script gets you the first 23 points. The last 43 are the part it
deliberately leaves to you.

## The fine print, which is the honest part

**These skills do not post, reply, like, follow or DM.** X's API does allow
posting with your own developer app and OAuth, unlike LinkedIn's. As of
September 2026 it is pay-per-use: $0.015 a post, $0.20 for a post with a link,
credits bought upfront ([pricing](https://docs.x.com/x-api/getting-started/pricing)).
It is still not built here, on purpose. X's
[automation rules](https://help.x.com/en/rules-and-policies/x-automation)
prohibit automated likes, bulk follows and unsolicited automated replies, and
AI reply bots need X's written approval, and replies and comments are most of
what this pack writes. So every skill ends the same way: a copy-ready block,
and you paste it.

**`/x-viral` reads, it does not scrape.** X's Terms prohibit crawling or
scraping "in any form, for any purpose" without written consent. You pick the
posts; `pull.py` only fetches URLs you give it, through the documented oEmbed
API, one per second, capped at 100 a run. It never logs in, never uses your
session and never fetches counts. You read those off the screen.

**`hookscore.py` is a lint, not a predictor.** The same five-property panel,
tested on 74 real short-form hooks in the Instagram version of this pack,
separated real hooks from deliberately bad ones well (AUC 0.83) and a
creator's own hits from their own misses barely at all (AUC 0.56, a coin flip
is 0.50). It has not been re-calibrated on X. It catches labels, greetings and
hooks with nothing concrete in them. It will not tell you which of two decent
hooks will travel. `/x-audit` on your own posts will.

**The link question is left to your data.** X says it stopped down-ranking
posts with links more than a year ago (Musk and Nikita Bier, July 2026). An
independent analysis in January 2026 still measured fewer views on them. The
pack does not pick a side. `/x-audit` splits your posts by format and tells
you which is true for your account.

**The five detection checks are local heuristics**, not GPTZero, Originality,
Copyleaks, Winston or Turnitin. They do not call those services and cannot
promise their verdicts. Nobody can honestly sell you "undetectable".

**Nothing here fabricates.** No invented metrics, clients or outcomes go under
your name. If a draft needs a number you have not given, it comes back with
`{{your number}}` in it and a flag, every time.

## Files

```
skills/x-post/hooks.json         21 hook formulas: template, example, use, trap, match regex
skills/x-post/hookscore.py       five-property hook panel + formula classifier
skills/x-post/count.py           X's weighted character count + six lints
skills/x-thread/thread.py        draft -> thread that fits, five thread lints
skills/x-viral/pull.py           post URLs -> swipe sheet, via X's oEmbed API
skills/x-viral/swipe.py          outlier ranking + hook / structure / format breakdown
skills/x-audit/audit.py          analytics export -> what worked, with n
skills/x-plan/weights.py         X's published ranking weights, live
skills/x-human/slop.json         176 terms, 18 invisible classes, 18 structural tells
skills/x-human/humanize.py       the three cleaning passes
skills/x-human/detect.py         the five-check panel
skills/x-profile/rubric.json     the 100-point profile score
templates/voice.md               your voice profile. Fill this in first.
```

Your own files live in `~/.claude/x/`: `voice.md`, `plan.md`, `log.md` and
`swipe.md`. The skills read each other's.

## Credit

Made by Jake Schincariol, [opusjake.ai](https://opusjake.ai). Siblings:
[LinkedIn](https://github.com/Jakeschincariol/linkedin-agent-skill),
[Instagram](https://github.com/Jakeschincariol/instagram-agent-skill),
[YouTube](https://github.com/Jakeschincariol/youtube-agent-skill).

## License

MIT. Take it, change it, ship it.
