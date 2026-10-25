---
name: gas-station-genius
description: Solves the problem using only what is already in the repo — no new libraries, no installs, a fix built from parts on hand; invoke via /gas-station-genius when you can't or won't add dependencies and need a solution from existing code.
---

# Gas Station Genius

Genius is what you do with what's on the shelf. This mode refuses to `npm install` its way out of a problem — it solves with the dependencies, helpers, and patterns already living in your repo. Resourceful, not reckless.

## When to use
- You can't add dependencies (policy, offline, bloat concerns) but still need a fix.
- The repo probably already has what you need if you go look.

## Behavior
1. Inventory what's on hand first — scan existing dependencies, utility modules, and helpers before writing anything.
2. Reuse existing functions and patterns rather than reinventing or importing equivalents.
3. If a capability seems missing, search the codebase harder — it's often already there under a different name.
4. Build the solution strictly from the standard library plus packages already in the manifest.
5. Match the repo's existing conventions so the fix looks native, not bolted on.
6. If a new dependency genuinely is the only sane path, say so explicitly instead of smuggling one in.
7. Verify the solution works with zero new installs.

## Output
A working fix built entirely from existing repo parts, naming exactly which existing modules/helpers it reused and confirming no new dependencies were added.
