# The Duel skill

**Make Claude defend its answer against another model.** The Duel, also called Face Off, sends an
answer to an OpenAI model for a critique. Claude defends what holds up, revises what does not, and
returns the answer with a record of what changed.

Say **“Duel this with ChatGPT”** or run `/duel`. Up to three rounds. Two actual models. One clear
account of the claims they challenged.

“ChatGPT” is the friendly name here: the critic runs through the **OpenAI API**, not your ChatGPT
app or subscription. Claude Code is the defender and writes the final synthesis. There is no
neutral judge and no guarantee the resulting answer is correct.

## Install

Paste this into Claude Code:

```text
https://github.com/Jakeschincariol/duel-skill

Install this skill, then confirm /duel is available. Do not run a paid duel yet.
```

Or install manually:

```bash
git clone https://github.com/Jakeschincariol/duel-skill.git
mkdir -p ~/.claude/skills
cp -R duel-skill/skills/duel ~/.claude/skills/duel
```

For a project-only install, copy `skills/duel` into that project's `.claude/skills/` instead.

Or install as a Claude Code plugin:

```text
/plugin marketplace add Jakeschincariol/duel-skill
/plugin install duel-skill@duel-skill
```

Plugin installs use `/duel-skill:duel`. The copied skill uses `/duel`.

Requires **Claude Code and Python 3.9 or newer**. The helper uses Python's standard library;
there is nothing to pip install.

## Connect the critic

Configure `OPENAI_API_KEY` securely in the environment that launches Claude Code. Do this yourself
through your preferred secret manager or shell setup; do not paste the key into chat or put it in
this repository. No Anthropic API key is needed: the current Claude Code session is the defender.

The default critic is [`gpt-6-astra`](https://developers.openai.com/api/docs/models/gpt-6-astra).
Set `DUEL_OPENAI_MODEL` to use a different Responses API model available to your account, or pass
`--model` to `/duel` or the Python helper.

The skill is free under the MIT license. Claude Code usage and
[OpenAI API usage](https://openai.com/api/pricing/) are billed under their respective plans.
The normal run makes up to three critic calls; `--quick` makes one. Actual cost depends on the
model and the amount of text sent and returned.

## Use it

```text
/duel
/duel --quick
/duel --manual --quick
/duel --rounds 2 Should I raise my coaching price from $500 to $700?
Duel this with ChatGPT.
Face off this answer.
```

On its own, `/duel` uses the answer you want challenged and its original task. With a new task,
Claude first writes an answer. Three rounds is the default; `--quick` selects one, and `--rounds`
accepts 1, 2, or 3. A run can end early if the critique adds nothing substantive.

1. **Prepare.** Claude captures the task, answer, relevant context, and claims in a focused packet.
2. **Challenge.** The OpenAI critic identifies specific weaknesses, counterexamples, missing
   evidence, and conditions that could change the answer.
3. **Defend and revise.** Claude addresses the objections, updates its answer, and carries the
   debate forward to the next round.
4. **Return the result.** You get the revised answer and a claim ledger: **retained**, **revised**,
   **dropped**, or **unresolved**. Claims keep stable IDs so concessions remain visible.

Claude makes the final synthesis, and disagreement may remain unresolved. Debate is a way to
surface weaknesses; it is not independent verification of every fact.

Without an API key, use manual mode: have an external model critique the prepared packet yourself,
then paste its actual response back into Claude. The skill must label this manual mode and cannot
invent an external model's participation.

## What gets sent and saved

The helper sends only the prepared packet and its critic instructions to
`https://api.openai.com/v1/responses`. It does not upload the repository or conversation wholesale.
Review the packet before using sensitive material, and include only the context needed for the task.

Requests use `store: false`. This disables Responses API application-state storage; it does not
promise zero retention. See [OpenAI's API data controls](https://platform.openai.com/docs/guides/your-data).
The critic receives no tools. Each helper invocation makes one request, with no automatic retries,
an input limit of 128 KiB (and 100,000 text characters) and a default output budget
of 8,192 tokens. An explicit
`--max-output-tokens` override can raise that budget to 32,768 tokens.

Local run records live under `.duel/`, which this repository ignores. Keep real run packets and
responses out of commits, including when installing the skill into another project.

## Helper and offline checks

Run these from the cloned repository:

```bash
python3 skills/duel/scripts/duel.py check
mkdir -p .duel
python3 skills/duel/scripts/duel.py critique \
  --packet examples/pricing.packet.json \
  --output .duel/example.request.json --dry-run
python3 -m unittest discover -s tests -v
```

The example packet is illustrative offline input, not a live duel or a model verdict. A dry run
prepares the request without contacting OpenAI. `check` also runs offline; it exits with status 1
when no API key is configured. To make one paid critic call:

```bash
mkdir -p .duel/example
python3 skills/duel/scripts/duel.py critique \
  --packet examples/pricing.packet.json \
  --output .duel/example/critique.json
```

The helper also accepts `--model`, `--max-output-tokens`, and `--timeout`. It handles one critique;
the [skill](skills/duel/SKILL.md) orchestrates the rounds and final answer.

CI runs the offline unit tests on Python 3.9, 3.12, and 3.14, without API credentials.

## License

[MIT](LICENSE). Made by Jake Schincariol.
