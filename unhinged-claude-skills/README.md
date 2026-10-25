# Unhinged Claude Skills

25 Claude Code skills with names that sound like a police report and uses that save real hours. Each one is a legit operating mode — a compressor for sub-agent dispatch, an obsessive auditor, a workflow optimizer, a ship-it-tonight enforcer, a spec writer — dressed in a name that makes you laugh. The name is the joke; the saved hours are the point.

## Install

These are standard Claude Code skills. Drop any folder into your skills directory and invoke it with its slash command.

```bash
# 1. Clone the repo
git clone https://github.com/Jakeschincariol/unhinged-claude-skills.git
cd unhinged-claude-skills

# 2. Copy any skill folder into your Claude Code skills directory
cp -r chinese-grandpa ~/.claude/skills/

# 3. Use it inside Claude Code by typing its slash command
#    /chinese-grandpa
```

You don't have to install all 25 — copy only the ones you want:

```bash
cp -r weaponized-autism meth-lab divorced-dad ~/.claude/skills/
```

Each skill lives in its own folder containing a single `SKILL.md`. Invoke a skill by typing its slash command, e.g. `/weaponized-autism`.

## The 25 skills

### Headliners

| Command | What it does |
| --- | --- |
| `/chinese-grandpa` | Compresses repeated sub-agent instructions via Mandarin to slash the token bill, intent preserved. |
| `/weaponized-autism` | Obsessive-detail mode — reads everything, checks every edge case, hard to fool. |
| `/meth-lab` | Strips a bloated system, prompt, or automation down to the fastest, cheapest version that still works. |
| `/divorced-dad` | Stops gold-plating — builds the simplest functional version and ships it tonight. |
| `/redneck-engineer` | Turns a vague idea into a tight PRD, task list, flows, and acceptance criteria. |

### Ship It Anyway

| Command | What it does |
| --- | --- |
| `/duct-tape-dev` | Ships the quick patch that unblocks now, clearly flagged as debt. |
| `/gas-station-genius` | Solves with whatever is already in the repo — no new libraries, no installs. |
| `/macgyver` | Improvises from primitives — standard library and cleverness over a new framework. |
| `/apollo-13` | Works a critical failure under hard constraints to get the broken thing home. |
| `/cowboy-coder` | Makes the judgment calls itself and keeps moving — fast and opinionated. |
| `/questionable-engineering` | Picks the solution that works over the one that's technically correct. |
| `/goblin-mode` | Gets it working ugly first — no naming debates, no premature structure. |

### Full Send

| Command | What it does |
| --- | --- |
| `/speedrun` | Finds the shortest path to done and takes it — no detours, no nice-to-haves. |
| `/autopilot-chaos` | Runs the whole task end to end without stopping; you review at the finish line. |
| `/rage-compile` | Attacks the error list in one pass — fix, rebuild, repeat, until it builds clean. |
| `/panic-mode` | Triages a live incident — stop the bleeding, smallest safe fix, post-mortem later. |
| `/zero-sleep` | Holds the thread across a big multi-step build without losing the plot. |
| `/sleep-deprived-founder` | Cuts the backlog to the one or two things that actually move the needle. |
| `/crackhead-energy` | Fires out ~20 rough ideas in a minute for you to cherry-pick. |
| `/caffeine-overdose` | Goes wide and exhaustive — every option, every edge, every step spelled out. |

### Feral Focus

| Command | What it does |
| --- | --- |
| `/feral-goblin` | Drops the small talk and goes heads-down — just code and short status lines. |
| `/keyboard-gremlin` | Makes the smallest possible change — surgical edits, minimal diff. |
| `/basement-hacker` | Reverse-engineers internals and explains how something actually works. |
| `/schizotech` | Connects the dots nobody asked for — wild lateral architecture ideas (filter heavily). |
| `/tax-fraud` | Hunts cost everywhere — trims tokens, kills redundant calls, finds the cheapest path. |

## Credit

Made by Jake Schincariol — [opusjake.ai](https://opusjake.ai). Read [the full write-up](https://opusjake.ai/r/unhinged-claude-skills).

## License

MIT — see [LICENSE](LICENSE).
