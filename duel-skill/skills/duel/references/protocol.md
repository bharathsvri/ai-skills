# Exchange protocol

The helper makes one OpenAI Responses API request. Claude manages the local files,
the rebuttal, and the final answer. It does not need an Anthropic API key.

## Packet

```json
{
  "task": "Should I raise my coaching price from $500 to $700?",
  "answer": "Yes. At $700 you make 40% more revenue from the same clients.",
  "context": "No retention or demand data has been supplied.",
  "round": 1,
  "history": [],
  "claims": [
    {"id": "C1", "text": "The new price produces 40% more total revenue."}
  ]
}
```

`task`, `answer`, `round`, and `history` are required. `context` and `claims` are
optional. Use nonempty strings for text fields, except context may be omitted when
there is nothing to add. Claims use unique, stable IDs. `round` must be 1, 2, or 3.

For round 2, history contains the completed first exchange:

```json
[
  {
    "round": 1,
    "critic": "The actual critique returned by the critic.",
    "response": "Claude's concise response to the objections and revised answer."
  }
]
```

For round 3, include rounds 1 and 2 in order. Preserve the critic's actual text;
do not rewrite it to imply agreement. The top-level answer is always the current
answer. Keep the original in `initial.md`. The packet has a 128 KiB byte limit and
a 100,000-character limit across its text fields;
if the helper rejects an oversized packet, narrow the task or context explicitly
instead of silently cutting relevant history.

## Run files

```text
.duel/<unique-run>/
  initial.md
  round-1.packet.json
  round-1.critic.json
  round-1.response.md
  round-2.packet.json       # only when needed
  round-2.critic.json
  round-2.response.md
  round-3.packet.json       # only when needed
  round-3.critic.json
  round-3.response.md
  final.md
```

The helper refuses to overwrite an output file. A successful result contains
`status`, `round`, `model`, `response_id`, `critique`, and `usage`. Preserve those
metadata fields. Usage reports tokens from the API, not a calculated dollar cost.
Round packet/reply files stay local; only the prepared packet and critic instructions
are sent to OpenAI. The key is read from the process environment and never belongs
in a packet or run record.

## Controls

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/duel.py" critique \
  --packet ".duel/RUN/round-1.packet.json" \
  --output ".duel/RUN/round-1.request.json" \
  --dry-run
```

Dry-run validates the packet and writes the planned request without a key or a
network call. It is useful for inspecting exactly what would leave the machine.
It is not a model response and does not complete a debate round.

Use `critique --help` for the available `--model`, `--timeout`, and
`--max-output-tokens` controls. The default output cap is 8192 tokens per call,
including reasoning tokens. A token cap is not a dollar budget. Do not increase it
or repeat uncertain requests without the user's agreement. The helper has no
automatic retries and sends no browsing or execution tools.

The request uses `store: false`. That setting is not a promise of zero retention;
OpenAI's account and API data policies still apply. The helper sends requests only
to `https://api.openai.com/v1/responses`.

## Manual mode

Generate a dry-run request file. Give the user `request.body.instructions` and
the JSON text in `request.body.input[0].content[0].text` to paste into a separate
model, excluding the API-only fields. Ask them
to paste that model's actual response back. Do not claim to have accessed their
ChatGPT account or verified which model they used. Save the supplied critique in
`round-N.manual.json`, separate from the helper's API output format:

```json
{
  "mode": "manual",
  "round": 1,
  "origin": "user-provided",
  "model": "unknown",
  "verified": false,
  "critique": "The actual external response pasted by the user."
}
```

Replace `model` with the user's reported model only when supplied. Do not invent
response IDs or token usage. Continue the same claim/revision process, counting an
exchange after the actual critique and Claude's response are both present. API
credentials are not needed. Manual responses must never be described as
API-verified results; a generated prompt alone completes zero exchanges.

## Worked example: the evidence boundary

For the illustrative coaching question above, raising price from 500 to 700 is a
40% price increase. Total revenue grows by 40% only if the paying client count is
unchanged. At 70% retention, revenue is `700 × 0.70 / 500 = 0.98` of its old level.
Revenue breaks even at `500 / 700 ≈ 71.43%` retention, before costs or new demand.

Neither a 30% churn prediction nor a guaranteed 90-day rollout is established by
those calculations. Retain the arithmetic, revise the unconditional revenue claim,
and mark retention/demand as unknown until tested. This example is a protocol
illustration, not a live model transcript or business recommendation.
