# Design checklist

Use it twice: Part 1 before any code, Parts 2 and 3 before you call the design done.

## Part 1: Direction (fill this in, show it to the owner, then build)

Answer from the owner's world, not from the category:

- **Who and where:** who opens this, on what device, in what situation, under what light? (This decides light or dark. Never pick dark "because it's tech" or light "because it's health".)
- **The one job:** what must a first-time visitor understand or do within 5 seconds?
- **The memorable thing:** one sentence. What should they remember an hour later?
- **Owner's real material:** logo, photos, brand colors, documents, price lists. Open and look at every file before proposing anything. Their real assets beat anything generated.
- **Mode:** Sell (landing, pricing), Use (app, tool, dashboard), Read (menu, docs, blog), Show (portfolio, gallery). Sell and Show may be loud; Use and Read win on clarity and calm.

Then write the direction block:

```
THESIS     one sentence: the idea this site owns, and the generic version it refuses
SCENE      who, where, what light -> light or dark
TYPE       display face + text face (max 2 families, 4 weights), why they fit, fallbacks
COLOR      4-6 named hex values with jobs: ground, surface, ink, muted ink, accent (primary action only), state colors
STRATEGY   restrained (tinted neutrals + one accent) | committed (one color owns 30-60% of the page) | drenched (the page IS the color)
SPACE      4px base: 4 8 12 16 24 32 48 64 96 128; content width ~65-75ch for reading
SHAPE      radius scale (e.g. 2/6/12, not one radius on everything), borders, depth (shadows need offset + blur)
MOTION     one signature moment + feedback timings (150-250ms, ease-out) + reduced-motion plan
SIGNATURE  the single bold element where you spend the boldness; everything else stays quiet
ANTI-GOALS 3 things this design will not do
```

Self-check before code: if someone could guess this design from the category alone ("it's a coffee shop, so cream and a serif"), it is a default. Change the part that is generic and say what you changed.

Verify the palette with numbers, not eyes:
`python3 tools/contrast.py --css site/styles.css --pair ink:ground --pair muted:ground --pair ground:accent`

## Part 2: AI-slop defaults to avoid (unless the brief asks for them)

Each of these reads as "a machine made this". If the owner's brief explicitly asks for one, the brief wins.

**Layout**
- Hero with headline left, screenshot right, two buttons, and three stat numbers under it.
- Three identical feature cards: icon in a tinted circle, bold title, two lines of text. Content of unequal weight in equal boxes.
- Everything wrapped in rounded cards, cards inside cards, the same soft gray shadow under each.
- Everything centered. Every section the same height and rhythm (hero, 3 features, testimonials, pricing, CTA).
- Tiny all-caps label above every heading; 01 / 02 / 03 numbers on content that is not a sequence.
- A modal for something that could live inline.

**Surfaces and effects**
- Purple-to-blue (or any decorative) gradients, gradient text, glowing edges, frosted glass panels as the default surface.
- Decorative blobs, floating circles, wavy dividers, grid-paper backgrounds filling empty space.
- A thick colored stripe on the left edge of cards or alerts.
- Light sweeps, pulsing dots, glow rings, "scanner" effects.

**Type**
- One overused sans for everything (Inter, Roboto, Arial, Poppins, Montserrat, Open Sans, the system UI font) when the page needs a voice. Fine for dense app UI, weak as a brand's display face.
- The reflex pairings: a high-contrast serif display with italic accent words on cream; a mono font as "tech" costume.
- One word in the headline italicized or colored for emphasis.
- Body text under 16px, gray body text on white below 4.5:1, lines longer than ~80 characters.

**Color**
- Pure #000 on pure #fff with one neon accent; near-black page with acid green.
- Cream background + serif + terracotta accent as the default "warm" look.
- More than one accent color competing for the primary action.

**Copy**
- "Welcome to ...", "Unlock the power of ...", "Your all-in-one solution", "Seamless", "Elevate", "Supercharge".
- Fake testimonials, invented stats ("10k+ happy customers"), stock five-star rows. Real proof or none.
- Buttons that say Submit, Learn more, Get started when they could name the outcome ("Book a table", "Get the quote").
- Em dashes everywhere (a known machine-writing tell); use commas, colons and periods.

**Imagery**
- Emoji or unicode symbols as icons. Use one icon set (Lucide, Phosphor, Heroicons) or drawn SVG, one stroke weight.
- Generic stock heroes, AI people, or a gray box standing in for an image. The owner's real photos or the product itself.
- Fake product screenshots or invented logos.

## Part 3: Polish pass (before calling the design done)

- [ ] **First look:** screenshot at 1440 and 375. In 3 seconds, what does the page say? Are the first three things your eye lands on the three that matter most? If not, the hierarchy is wrong.
- [ ] **Squint test:** blur your eyes. Primary action, headline and main groups still read in the right order.
- [ ] **Type:** two families max; clear size steps; headings balanced (`text-wrap: balance`); body 16px+; measure 45-75ch; no orphaned single words in headings at 375.
- [ ] **Spacing:** every gap comes from the scale; related things close, separate groups far; more space above a heading than below it.
- [ ] **Color:** every color has a job; accent only on actions and key highlights; contrast verified with `contrast.py` (text 4.5:1, large text and UI 3:1).
- [ ] **States:** hover, focus-visible, active, disabled, loading, empty, error, success are all designed, not browser defaults.
- [ ] **Browser surfaces themed:** `::selection`, focus ring, `accent-color` on checkboxes, caret color, link underline offset, `font-variant-numeric: tabular-nums` for numbers in tables and prices.
- [ ] **Images:** real, sharp, cropped with intent, `width`/`height` set, compressed (WebP/AVIF), `alt` written.
- [ ] **Motion:** one orchestrated moment; feedback 150-250ms ease-out; nothing hidden until JavaScript runs; `prefers-reduced-motion` respected.
- [ ] **Copy:** the owner's words, specific, sentence case, buttons name the outcome, errors say what happened and how to fix it.
- [ ] **Remove one thing.** Find the least necessary decoration and delete it.
