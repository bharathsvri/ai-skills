# QA checklist (real browser, 375 / 768 / 1440)

Done means verified, not "should work". Every box below is checked by doing it and looking at the result.

## 1. Automated sweep (2 minutes)

```bash
python3 tools/sitecheck.py site/                        # local folder (served for you)
python3 tools/sitecheck.py http://127.0.0.1:8000/       # or a running dev server / live URL
python3 tools/sitecheck.py https://the-live-site.com --external   # after deploy
```

- [ ] Zero errors. Fix them all, re-run.
- [ ] Every warning either fixed or consciously accepted (write down why).
- [ ] App with JavaScript-built pages: sitecheck only sees the served HTML, so the browser pass below carries more weight.

## 2. Screenshots at three widths

Use the harness browser tool if you have one (Claude in Chrome, the Claude Code preview browser): resize to 375x812, 768x1024, 1440x900 and screenshot each page.

Without one, Playwright's CLI gives true viewports:

```bash
npx playwright screenshot --viewport-size=375,812  --full-page http://127.0.0.1:8000/ qa/home-375.png
npx playwright screenshot --viewport-size=768,1024 --full-page http://127.0.0.1:8000/ qa/home-768.png
npx playwright screenshot --viewport-size=1440,900 --full-page http://127.0.0.1:8000/ qa/home-1440.png
```

(First run may need `npx playwright install chromium`, a ~150 MB download: tell the owner before running it.)

Trap: `chrome --headless --window-size=375,...` does NOT give a 375 layout. Chrome enforces a ~500px minimum window, lays the page out at 500px and crops the image to 375, so it looks mobile while hiding real mobile bugs. Use the tools above for 375.

Open and look at every screenshot. For each page at each width:
- [ ] No horizontal scroll, nothing cut off at the right edge (the most common mobile bug; grid tracks need `minmax(0, 1fr)`, images `max-width: 100%; height: auto`).
- [ ] Text readable without zoom (16px+ body), no overlapping elements, no orphaned words in headings.
- [ ] Navigation works at that size (menu opens, closes, every item reachable).
- [ ] Tap targets at least 44x44px on phones; nothing important hidden on mobile.
- [ ] Below-the-fold sections are actually visible (scroll-reveal animations can leave them blank).

## 3. Every flow, by hand

- [ ] Every nav link, button and call to action goes where its label says.
- [ ] Forms: submit empty (clear inline errors), invalid input (wrong email, letters in a number), very long input, special characters (é, emoji, apostrophes), valid input (success message, data arrives where the owner expects it), double-click submit (no duplicate).
- [ ] States: empty (no data yet), loading (slow network), error (offline, server down), success. Each one is designed and tells the visitor what to do next.
- [ ] Logic: calculators, filters, totals, dates checked against a few cases worked out by hand (and covered by tests).
- [ ] Back and refresh don't lose work or break the page; deep links open the right state.

## 4. Accessibility basics

- [ ] Keyboard only: Tab reaches everything in a sensible order, focus is always visible, Enter/Space activate, Escape closes menus and dialogs, no traps.
- [ ] One `<h1>` per page, headings in order, landmarks (`header`, `nav`, `main`, `footer`).
- [ ] Every image has meaningful `alt` (or `alt=""` if decorative); icon buttons have `aria-label`.
- [ ] Every form field has a visible label; errors are announced in text, not color alone.
- [ ] Contrast checked (`tools/contrast.py`); page usable at 200% zoom; `prefers-reduced-motion` turns off big movement.

## 5. Console and network

- [ ] Zero console errors and zero failed requests (4xx/5xx) on every page, at every width, after every interaction. A 404 favicon counts.
- [ ] No mixed content warnings on HTTPS.

## Logging and fixing

Write each issue as: page, width, steps to reproduce, expected, actual, severity.

| Severity | Meaning |
|---|---|
| critical | data loss, security/privacy exposure, or the main task is impossible |
| high | a major feature broken, no workaround |
| medium | works with a workaround, or broken at one width |
| low | cosmetic, copy, small polish |

Fix loop:
1. Fix in severity order, one issue at a time, smallest change that fixes the cause (find the cause first; don't patch symptoms).
2. Logic bug: write a failing test that reproduces it, then fix, then watch it pass.
3. Re-verify that issue at all three widths and re-check the console.
4. Stop and rethink if a fix breaks something else twice, or three attempts at one bug fail: the approach is wrong, not the details.
5. After the batch: re-run sitecheck and the screenshot pass once more. Two full rounds is the budget; report anything left honestly instead of looping.

Report to the owner: what was tested, what was fixed, what is left and why, in plain English.
