# Locked decisions

Standing orders for this project. Promptmaster reads this file before every
request and applies each row automatically. It will refuse to produce output
that contradicts a locked row until you say `unlock <key>`.

Lock one with `lock: <key> = <value>`. Print the table with `decisions`.

| locked | key | value | scope |
| --- | --- | --- | --- |
| 2026-08-28 | voice | casual, like I talk | all writing |
| 2026-08-28 | length | under 200 words | posts + captions |
| 2026-08-28 | emojis | never | everywhere |

Delete the example rows above and lock your own. Keep values short enough to
apply without interpretation. One row, one rule.
