# promptmaster — get it right the first prompt

A free Claude skill that rewrites your prompt into an optimized format Claude
understands the first time, so you are not stuck re-explaining yourself and
burning through usage.

Every retry resends your whole conversation. Five rounds of "no, I meant..."
means you paid for the same context five times. Promptmaster kills the retries
at the source:

- **Rewrites your raw ask** into a specific one before answering it. Vague in,
  exact out, then it executes the optimized prompt in the same turn.
- **Audits against 35 credit-waste patterns** ([waste-patterns.json](waste-patterns.json)):
  the specific ways prompts force retries, from "no deliverable named" to
  pattern #35, redundant context.
- **Remembers the decisions you already made** ([decisions.md](decisions.md)):
  lock a preference once (voice, length, emojis, stack) and it is applied to
  every future request. Contradictions get blocked, not silently absorbed.

The whole move, one line each:

```
raw:       write me something for instagram, idk
rewritten: Write a 30-day Instagram plan for a local coffee shop with 8k
           followers. One table: week, theme, 3 post ideas. Under 400 words.
```

## Install

The fast way: **paste this repo link into Claude and ask it to install the
skill.** Then type `/promptmaster` before any request.

```
https://github.com/Jakeschincariol/promptmaster-skill
Install this skill, then confirm /promptmaster works.
```

Manual, for Claude Code:

```bash
git clone https://github.com/Jakeschincariol/promptmaster-skill
cp -R promptmaster-skill/.claude/skills/promptmaster ~/.claude/skills/
```

Project-local instead: copy the same folder into your repo's
`.claude/skills/`. No Claude Code? Paste [SKILL.md](SKILL.md) at the top of any
Claude chat and it runs as a mode.

## Use

```
/promptmaster write me something for instagram, idk
```

You get a short receipt (what was rewritten, which waste patterns were flagged,
which locked decisions applied), then the finished answer. Standing preferences:

```
lock: voice = casual, like I talk
unlock voice
decisions
```

## Files

| file | what it is |
| --- | --- |
| [SKILL.md](SKILL.md) | the rewrite loop + examples |
| [waste-patterns.json](waste-patterns.json) | all 35 credit-waste patterns |
| [decisions.md](decisions.md) | persist locked decisions |
| `.claude/skills/promptmaster/` | the same skill in standard installable layout |

More free skills and resources: [opusjake.ai](https://opusjake.ai)

MIT licensed.
