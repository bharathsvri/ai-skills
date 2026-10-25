# ⚡ AI Skills

> **The ultimate curated monorepo of 140+ battle-tested AI agent skills, Claude Code workflows, social media growth engines, trading intelligence suites, and developer superpowers.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Skills Count](https://img.shields.io/badge/Skills-140%2B-purple.svg)](#-skills-index--quick-reference)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-Compatible-orange.svg)](https://claude.com/claude-code)
[![ChatGPT](https://img.shields.io/badge/ChatGPT-Compatible-74aa9c.svg)](https://chatgpt.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-brightgreen.svg)](#-contributing)

---

## 📖 Table of Contents

- [Overview & Philosophy](#-overview--philosophy)
- [Skills Directory by Category](#-skills-directory-by-category)
  - [📱 Social Media & Growth Agents](#-social-media--growth-agents)
  - [🎬 Video, Media & Creative Engineering](#-video-media--creative-engineering)
  - [💼 Career, Startup & App Building](#-career-startup--app-building)
  - [📈 Trading & Financial Intelligence](#-trading--financial-intelligence)
  - [🧠 Adversarial Reasoning & Prompt Systems](#-adversarial-reasoning--prompt-systems)
  - [🛠️ Developer Modes & Engineering](#️-developer-modes--engineering)
  - [🎙️ Standalone Applications](#️-standalone-applications)
- [🚀 Quick Start & Installation](#-quick-start--installation)
  - [Installing for Claude Code](#installing-for-claude-code)
  - [Using with ChatGPT & Other LLMs](#using-with-chatgpt--other-llms)
  - [Python Tool Requirements](#python-tool-requirements)
- [📋 Skills Index & Quick Reference](#-skills-index--quick-reference)
- [🤝 Contributing](#-contributing)
- [📄 License](#-license)

---

## 🌟 Overview & Philosophy

**AI Skills** is a comprehensive, production-ready library of modular agent skills. Designed primarily for **[Claude Code](https://claude.com/claude-code)** and easily portable to **ChatGPT**, **Cursor**, **Antigravity**, and autonomous LLM agents.

### Why this exists:
1. **Zero Fluff, Real Output:** Standard prompts produce boilerplate. These skills use deterministic frameworks, battle-tested heuristics, and domain constraints.
2. **Human in the Loop:** These skills brainstorm, draft, audit, and analyze—**nothing is posted or traded without your explicit confirmation**.
3. **Local & Free:** MIT licensed, zero signups, zero proprietary subscriptions. Everything runs directly on your machine or through standard API endpoints.
4. **Anti-Slop by Design:** Includes specialized humanizer modules that strip AI markers, clichéd phrasing, and unnecessary em dashes before output ever reaches you.

---

## 📂 Skills Directory by Category

### 📱 Social Media & Growth Agents

Turn your AI assistant into an entire digital media and growth team:

| Suite | Skills Count | Description | Primary Slash Commands |
|---|:---:|---|---|
| [**YouTube Agent**](./youtube-agent-skill) | 11 | Complete YouTube channel lifecycle from hook formulas to retention curves. | `/yt-script`, `/yt-package`, `/yt-retention`, `/yt-shorts`, `/yt-viral` |
| [**ChatGPT YouTube Agent**](./chatgpt-youtube-agent-skill) | 11 | YouTube growth workflows optimized for ChatGPT custom instructions. | `yt-audit`, `yt-chapters`, `yt-package`, `yt-script`, `yt-viral` |
| [**X (Twitter) Agent**](./x-agent-skill) | 11 | Viral thread writing, post breakdowns, reply drafts, and anti-AI tone filtering. | `/x-post`, `/x-thread`, `/x-viral`, `/x-human`, `/x-plan` |
| [**Instagram Agent**](./instagram-agent-skill) | 13 | Reel scripts from 26 viral hooks, feed truncation optimization, and profile audits. | `/ig-reel`, `/ig-caption`, `/ig-viral`, `/ig-human`, `/ig-carousel` |
| [**LinkedIn Agent**](./linkedin-agent-skill) | 11 | High-converting B2B copy, carousel PDF outlines, and authentic professional posts. | `/li-post`, `/li-carousel`, `/li-human`, `/li-profile`, `/li-comment` |

---

### 🎬 Video, Media & Creative Engineering

Programmatic video composition, local transcription, and multi-disciplinary creative skills:

| Suite | Skills Count | Description | Primary Slash Commands |
|---|:---:|---|---|
| [**Video Production Skills**](./video-production-skills) | 13 | HTML/DOM-based video generation engine powered by **HyperFrames**. Deterministic rendering, CSS keyframing, and audio mixing. | `/hyperframes`, `/hyperframes-animation`, `/hyperframes-audio`, `/hyperframes-cli`, `/talking-head-recut` |
| [**Influencer Clone (Transcribe)**](./Influencer-Clone) | 1 | Universal video-to-text transcriber supporting 1,000+ platforms (YouTube, IG, TikTok, X) using `yt-dlp` and `faster-whisper`. | `/transcribe <url>` |
| [**Master Skills**](./master-skills) | 3 | Fused high-leverage workflows combining design, video editing, and cross-platform virality. | `/build`, `/edit`, `/virality` |

---

### 💼 Career, Startup & App Building

Validate business ideas, clone software products, and run an automated job search:

| Suite | Skills Count | Description | Primary Slash Commands |
|---|:---:|---|---|
| [**Founder Suite**](./founder-skill) | 11 | Rigorous business validation: advisory board, financial modeling, GTM timeline, and ICP interviews. | `/founder-board`, `/founder-cfo`, `/founder-launch`, `/founder-offer`, `/founder-pricing` |
| [**Hunter Career Suite**](./hunter-skill) | 11 | End-to-end job hunting: ATS resume tailoring, company dossiers, hiring manager outreach, and interview prep. | `/hunter-scout`, `/hunter-resume`, `/hunter-connector`, `/hunter-interview`, `/hunter-salary` |
| [**Replica App Cloner**](./replica-skill) | 11 | Reverse-engineer, improve, design, and code full-stack clones of existing applications. | `/replica-recon`, `/replica-diff`, `/replica-entrepreneur`, `/replica-build`, `/replica-deploy` |

---

### 📈 Trading & Financial Intelligence

Data-driven market analysis and portfolio discipline using free public data sources:

| Suite | Skills Count | Description | Primary Slash Commands |
|---|:---:|---|---|
| [**Day Trader Suite**](./day-trader-skill) | 11 | Intraday scanning, bar-by-bar entry/exit timing, risk guards, breaking news, and setup playback. | `/trader-scanner`, `/trader-entry`, `/trader-exit`, `/trader-alerts`, `/trader-timemachine` |
| [**Trader & Portfolio Suite**](./trader-skill) | 11 | Copy institutional 13F filings, track Congressional disclosures (Pelosi tracker), and manage position caps. | `/trader-copycat`, `/trader-pelosi`, `/trader-budget`, `/trader-screener`, `/trader-tax` |

---

### 🧠 Adversarial Reasoning & Prompt Systems

Push LLM output quality through tournament debates, self-adversarial checking, and prompt optimization:

| Suite | Skills Count | Description | Primary Slash Commands |
|---|:---:|---|---|
| [**The Arena**](./arena-skill) | 1 | Dispatches 100 sub-agents with differing strategy cards into a tournament bracket scored by an impartial judge. | `/arena` |
| [**The Duel**](./duel-skill) | 1 | Pits Claude against OpenAI models in a structured multi-round debate to audit and refine answers. | `/duel` |
| [**Claude Illegal Codes**](./claude-illegal-codes) | 5 | Unorthodox high-impact operating modes: Mandarin compression, anti-slop styling, and brutal self-adversarial fact checks. | `/67`, `/aura-farming`, `/china-maxing`, `/crash-out`, `/larp` |
| [**Promptmaster**](./promptmaster-skill) | 1 | Analyzes context and rewrites prompts to eliminate costly retry loops and token waste. | `/promptmaster` |

---

### 🛠️ Developer Modes & Engineering

Radical coding personas and console reverse engineering tools:

| Suite | Skills Count | Description | Primary Slash Commands |
|---|:---:|---|---|
| [**Unhinged Claude Skills**](./unhinged-claude-skills) | 25 | 25 wildly distinct operating modes designed for extreme coding speed, ruthless debugging, and zero ceremony. | `/weaponized-autism`, `/apollo-13`, `/chinese-grandpa`, `/meth-lab`, `/rage-compile` |
| [**Console Skill**](./console-skill) | 11 | Port, decompile, mod, and rebuild PlayStation 2 games on PC via static recompiler (`PS2Recomp`). | `/console-reverse`, `/console-graphics`, `/console-backend`, `/console-mod`, `/console-controller` |

---

### 🎙️ Standalone Applications

| Application | Platform | Description |
|---|---|---|
| [**Muesli**](./muesli) | macOS (Swift) | **The open-source meeting notepad.** Granola alternative that records mic + system audio via ScreenCaptureKit without a bot, transcribing locally with `whisper.cpp`. |

---

## 🚀 Quick Start & Installation

### Installing for Claude Code

Claude Code discovers skills placed in `~/.claude/skills/`. Each skill consists of a directory with a `SKILL.md` file.

#### macOS & Linux:

```bash
# Clone the repository
git clone https://github.com/bharathsvri/ai-skills.git
cd ai-skills

# Option 1: Install a specific skill (e.g., Promptmaster)
cp -r promptmaster-skill/promptmaster ~/.claude/skills/

# Option 2: Install an entire suite (e.g., Unhinged Claude Skills)
cp -r unhinged-claude-skills/*/ ~/.claude/skills/

# Option 3: Install all social media agents
cp -r youtube-agent-skill/skills/* ~/.claude/skills/
cp -r instagram-agent-skill/skills/* ~/.claude/skills/
cp -r linkedin-agent-skill/skills/* ~/.claude/skills/
cp -r x-agent-skill/skills/* ~/.claude/skills/
```

#### Windows (PowerShell):

```powershell
# Clone the repository
git clone https://github.com/bharathsvri/ai-skills.git
cd ai-skills

# Create Claude skills directory if it doesn't exist
$ClaudeSkills = "$HOME\.claude\skills"
if (!(Test-Path $ClaudeSkills)) { New-Item -ItemType Directory -Path $ClaudeSkills -Force }

# Install specific skill folder (e.g., Unhinged Skills)
Get-ChildItem -Path .\unhinged-claude-skills -Directory | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $ClaudeSkills -Recurse -Force
}
```

Once installed, simply start Claude Code and invoke any skill with `/`:
```
/weaponized-autism Audit the entire auth flow in src/auth.py
/yt-script Write a 60-second retention-focused video on local LLMs
/trader-pelosi Scan the latest House disclosures for tech stocks
```

---

### Using with ChatGPT & Other LLMs

If you use ChatGPT, Claude Web, or another platform:
1. Navigate into any skill folder (e.g., [`claude-illegal-codes/crash-out/SKILL.md`](./claude-illegal-codes/crash-out/SKILL.md)).
2. Copy the contents of `SKILL.md`.
3. Paste it directly into your chat or add it to **Custom Instructions** / **System Prompt**.

---

### Python Tool Requirements

Certain skills leverage optional local Python scripts for data retrieval, video transcription, or financial data fetching.

```bash
# Recommended setup for Python-backed skills (Influencer-Clone, trader-skill, day-trader-skill)
pip install faster-whisper yt-dlp yfinance requests beautifulsoup4
```

For transcription, ensure `ffmpeg` is available on your system PATH (`brew install ffmpeg` or `winget install ffmpeg`).

---

## 📋 Skills Index & Quick Reference

<details>
<summary><strong>🔍 Click to expand the full catalog of 140+ Slash Commands</strong></summary>

<br/>

### Unhinged Skills (`/unhinged-claude-skills`)
- `/apollo-13` — Fix critical bugs using only what already exists in the repo.
- `/autopilot-chaos` — Autonomous execution loop for bulk coding tasks.
- `/basement-hacker` — Low-level, assembly, byte-level reverse engineering.
- `/caffeine-overdose` — Rapid-fire prototyping without hesitation.
- `/chinese-grandpa` — Zero-dependency, minimal, hyper-frugal engineering.
- `/cowboy-coder` — Ship features immediately without bureaucratic friction.
- `/crackhead-energy` — Relentless creative momentum and idea exploration.
- `/divorced-dad` — Obsessive code cleanup and disciplined refactoring.
- `/duct-tape-dev` — Ultra-fast pragmatic glue code and hotfixes.
- `/feral-goblin` — Unconventional, sneaky workarounds for tough roadblocks.
- `/gas-station-genius` — Surprising street-smart architectural intuition.
- `/goblin-mode` — Raw coding speed over conventions.
- `/keyboard-gremlin` — Relentless fuzzing, mutation tests, and edge-case testing.
- `/macgyver` — Creative problem solving with minimal tooling.
- `/meth-lab` — Experimental, volatile, high-yield code synthesis.
- `/panic-mode` — Triage production outages with zero panic.
- `/questionable-engineering` — Entertaining yet functional architectural hacks.
- `/rage-compile` — Push through compiler warnings and strict type errors until green.
- `/redneck-engineer` — Tough, durable, tractor-grade solutions.
- `/schizotech` — Unconventional visionary frameworks and novel paradigms.
- `/sleep-deprived-founder` — 3 AM MVP shipping frenzy.
- `/speedrun` — Any% prototype speedrun.
- `/tax-fraud` — Aggressive token optimization and resource conservation.
- `/weaponized-autism` — Exhaustive, microscopic code auditing and verification.
- `/zero-sleep` — Sustained marathon developer stamina.

### Illegal Codes (`/claude-illegal-codes`)
- `/67` — Mandarin token compression protocol for multi-agent fleets.
- `/aura-farming` — Anti-slop UI/UX design enforcer with modern aesthetics.
- `/china-maxing` — 6-agent competitive tournament with strict rubric judging.
- `/crash-out` — Relentless self-adversarial fact-checking and red-teaming.
- `/larp` — Ruthless VC diligence and startup pressure testing.

### Social Media & Content Suites
- **YouTube** (`/yt-*`): `yt-script`, `yt-package`, `yt-retention`, `yt-viral`, `yt-shorts`, `yt-edit`, `yt-chapters`, `yt-comment`, `yt-seo`, `yt-plan`, `yt-audit`.
- **Instagram** (`/ig-*`): `ig-reel`, `ig-caption`, `ig-carousel`, `ig-story`, `ig-comment`, `ig-reply`, `ig-dm`, `ig-human`, `ig-profile`, `ig-plan`, `ig-viral`, `ig-repurpose`, `ig-audit`.
- **LinkedIn** (`/li-*`): `li-post`, `li-carousel`, `li-profile`, `li-comment`, `li-reply`, `li-inbox`, `li-dm`, `li-plan`, `li-repurpose`, `li-human`, `li-audit`.
- **X / Twitter** (`/x-*`): `x-post`, `x-thread`, `x-viral`, `x-comment`, `x-reply`, `x-dm`, `x-profile`, `x-human`, `x-plan`, `x-repurpose`, `x-audit`.

### Business, Career & Engineering Suites
- **Founder** (`/founder-*`): `founder-board`, `founder-brand`, `founder-cfo`, `founder-competitors`, `founder-consumer`, `founder-launch`, `founder-marketing`, `founder-offer`, `founder-ops`, `founder-plan`, `founder-pricing`.
- **Hunter** (`/hunter-*`): `hunter-scout`, `hunter-resume`, `hunter-research`, `hunter-linkedin`, `hunter-connector`, `hunter-cover`, `hunter-apply`, `hunter-interview`, `hunter-salary`, `hunter-followup`, `hunter-tracker`.
- **Replica** (`/replica-*`): `replica-recon`, `replica-diff`, `replica-entrepreneur`, `replica-architect`, `replica-design`, `replica-backend`, `replica-build`, `replica-test`, `replica-deploy`, `replica-brand`, `replica-launch`.
- **Trading** (`/trader-*`): `trader-scanner`, `trader-entry`, `trader-exit`, `trader-alerts`, `trader-timemachine`, `trader-copycat`, `trader-pelosi`, `trader-budget`, `trader-risk`, `trader-screener`, `trader-tax`.
- **Video Production** (`/hyperframes*`): `general-video`, `hyperframes`, `hyperframes-core`, `hyperframes-animation`, `hyperframes-keyframes`, `hyperframes-audio`, `hyperframes-cli`, `hyperframes-creative`, `hyperframes-registry`, `media-router`, `media-use`, `product-launch-video`, `talking-head-recut`.
- **Master Skills**: `/build`, `/edit`, `/virality`.
- **Tournament & Debate**: `/arena`, `/duel`.
- **Transcription**: `/transcribe`.
- **Prompt Optimization**: `/promptmaster`.

</details>

---

## 🤝 Contributing

Contributions are welcomed! You can add new skills, improve existing prompts, or add compatibility layers.

### Adding a New Skill:
1. Create a dedicated folder under the appropriate directory (or as a new top-level suite).
2. Include a `SKILL.md` with standard YAML frontmatter:
   ```markdown
   ---
   name: your-skill-name
   description: When and how this skill should be invoked.
   ---

   # Your Skill Title
   Instructions, constraints, workflows, and output format.
   ```
3. Test the skill in Claude Code or ChatGPT.
4. Submit a Pull Request!

---

## 📄 License

This repository is licensed under the [MIT License](LICENSE). Each sub-skill is free to use, modify, distribute, and integrate into personal and commercial projects.
