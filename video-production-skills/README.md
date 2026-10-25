# Video Production Skills

Thirteen [Claude Code](https://claude.com/claude-code) skills that turn a brief into a
finished, rendered video: composition, animation, audio mix, media sourcing, and render.

Built on **HyperFrames**, which renders video from HTML. A composition is an HTML file
whose DOM declares timing with `data-*` attributes, whose animation runtime is seekable,
and whose media playback is owned by the framework. Because the source is HTML and CSS,
compositions are diffable, reviewable, and deterministic to render.

## Install

```bash
git clone https://github.com/Jakeschincariol/video-production-skills.git
cp -r video-production-skills/*/ ~/.claude/skills/
```

Each folder is a self-contained skill with a `SKILL.md` entry point. Claude Code
discovers them automatically. Copy only the folders you want.

Start with `hyperframes`. It is the entry point and routes any video request to the
right workflow.

## Engine

| Skill | What it covers |
|---|---|
| `hyperframes` | Entry point. Routes any video request to the right workflow. Read first. |
| `hyperframes-core` | The composition contract: structure, timing attributes, tracks, sub-compositions, variables, deterministic render rules. |
| `hyperframes-animation` | Motion rules, multi-phase scene blueprints, scene transitions, and seven runtime adapters (GSAP by default, plus Lottie and others). |
| `hyperframes-keyframes` | Punch-ins, zooms, reframes, Ken Burns, camera moves, masks, SVG morph and draw, 3D depth. All seek-safe. |
| `hyperframes-audio` | Mixing placed audio: fades, crossfades, track gain, ducking, voiceover carve, EQ, compressor, limiter, automation envelopes. |
| `hyperframes-cli` | The dev loop: init, add, catalog, lint, check, snapshot, compare, preview, render, publish, cloud. Also build and render failure diagnosis. |
| `hyperframes-creative` | Non-animation direction: design spec handling, palettes, typography, narration, beat planning, composition patterns. |
| `hyperframes-registry` | Install, discover, and wire reusable registry blocks and components. |

## Workflows

| Skill | What it makes |
|---|---|
| `general-video` | Custom compositions when no specialized workflow fits: multi-scene pieces, brand and sizzle reels, montages, title cards, footage remixes. |
| `talking-head-recut` | Packages an existing talking-head, interview, or podcast clip with timed graphic overlay cards synced to the transcript. The clip plays untouched underneath. |
| `product-launch-video` | Turns a product URL, pasted script, or brief into a launch or promo video. |

## Media

| Skill | What it does |
|---|---|
| `media-use` | The media OS: resolve, generate, operate, remember. Handles BGM, SFX, images, icons, brand logos, voice, color grades, and LUTs, plus voiceover, transcription, captions, and background removal. Ships with a stock SFX library and LUTs. |
| `media-router` | Routes any generate or edit request on an image or video to the right connected MCP tool, discovered at runtime rather than assumed. |

## Requirements

Claude Code, plus the HyperFrames CLI for rendering. Some `media-use` operations expect
`ffmpeg` on your PATH and provider credentials for generation and transcription. See
`media-use/references/setup-providers.md`.
