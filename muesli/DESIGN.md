# Muesli — Design System

This document is law for Muesli's UI. Native macOS first; the brand whispers.

## Principles

1. **Native over novel.** System controls, system typography (SF), standard toolbar/sidebar
   anatomy. Muesli should feel like Apple shipped it, not like a web app in a trench coat.
2. **The transcript is furniture; the notes are the product.** Notes get the biggest, calmest
   surface. Transcript is dense and secondary.
3. **Nothing pulses unless it's recording.** Animation is reserved for the live state.

## Color

| Token | Value | Use |
|---|---|---|
| `Color.oat` | `rgb(0.83, 0.52, 0.24)` ≈ `#D48540` | Brand accent: primary actions, "Me" speaker, ✨ Enhance |
| `.red` (system) | — | Live recording only — dot, stop button, sidebar pill |
| `.blue` (system) | — | "Them" speaker label |
| System semantic colors | — | Everything else (text, backgrounds, separators) |

Never introduce a new hue. Warmth comes from oat + cream (the icon), not from tinting surfaces.

## Type

- System font everywhere. Title = `.title.weight(.semibold)` editable field.
- Transcript body 13.5 pt, notes 14 pt, line spacing 3.
- Timestamps and counters are `.monospacedDigit()`.

## Components

- **Record bar**: pulsing red dot (0.9 s ease), timer, two level meters (Mic = oat, System = blue).
- **Setup rows**: rounded 8 pt, `primary.opacity(0.04)` fill, green check when done.
- **Chat**: user bubbles oat @ 18% fill; assistant replies are plain markdown, no bubble.
- **Empty states**: SF Symbol at 30–34 pt `.tertiary`, one-line explanation, one action.

## Icon

Cream squircle, five toasted-oat waveform bars (center bar darkest). Regenerate with
`make icon` — never hand-edit the .icns.
