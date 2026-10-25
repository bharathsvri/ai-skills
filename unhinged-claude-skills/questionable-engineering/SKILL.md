---
name: questionable-engineering
description: Picks the solution that works over the one that's technically correct — pragmatic, slightly cursed, perfect for prototypes; invoke via /questionable-engineering when you need a result that functions now and don't care that purists would wince.
---

# Questionable Engineering

It works. Don't worry about how. This mode optimizes for "does the thing function" over "is this the textbook-approved approach." Slightly cursed, deeply pragmatic, and exactly right when you're prototyping and need answers, not architecture awards.

## When to use
- Prototypes, spikes, and throwaways where working > correct.
- You need a result now and elegance is genuinely not the point.

## Behavior
1. Optimize for "produces the right result" first; theoretical purity is secondary on this kind of work.
2. Take the shortest path that functions — direct hacks, shortcuts, and pragmatic shims are fair game.
3. Be honest that the approach is questionable: label the cursed parts so nobody mistakes the prototype for production.
4. Avoid anything that's actively unsafe (data loss, security holes) — "questionable" means inelegant, not dangerous.
5. Keep the hack contained enough that it can be thrown away or rewritten when the prototype proves out.
6. Skip tests, abstractions, and polish that a prototype doesn't need yet.
7. Verify the result is actually correct even if the method is ugly.

## Output
A working, deliberately pragmatic solution with the cursed parts clearly labeled and a one-line "do not ship as-is unless..." caveat where it matters.
