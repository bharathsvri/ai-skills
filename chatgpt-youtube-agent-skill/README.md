# The YouTube agent skill

Eleven ChatGPT skills that run a YouTube channel. Free, MIT, no signup, no API key, nothing to
connect.

One of them writes your script off 21 hook formulas and scores the hook before you waste a take on
it. One lints the title and the thumbnail as a single pairing, because writing them separately is
why half of your click surface says the same thing twice. One reads your audience-retention export
and tells you the exact second people left and what you were saying when they did. One turns a
transcript into an edit decision list. One finds the Shorts already hiding inside a long video. One
goes and finds what is working in your niche and ranks it by how far each video beat its own
channel, not by how big the channel is.

**Nothing gets published until you do it.** These skills write. You upload.

## Install

Paste this link into ChatGPT and say **install skill**:

```
https://github.com/Jakeschincariol/chatgpt-youtube-agent-skill
```

Or do it yourself:

```bash
git clone https://github.com/Jakeschincariol/chatgpt-youtube-agent-skill
cp -r chatgpt-youtube-agent-skill/skills/yt-* ~/.codex/skills/
```

Restart the app and the skills are available. Project-local instead of global: copy the same
folders into your repo's `.codex/skills/`.

## The eleven

| skill | what it does |
|---|---|
| `yt-script` | writes the script off 21 hook formulas, scores the hook |
| `yt-package` | title and thumbnail linted as one pairing |
| `yt-viral` | finds what is working in your niche, ranked by channel-relative lift |
| `yt-retention` | reads your retention export, names the second people left |
| `yt-edit` | transcript to an edit decision list, dead air flagged |
| `yt-plan` | the week's upload schedule |
| `yt-comment` | drafts replies in your voice |
| `yt-seo` | description, tags, and search surface |
| `yt-chapters` | chapter markers off the transcript |
| `yt-shorts` | finds the Shorts hiding in a long video |
| `yt-audit` | reads a channel and says what is actually wrong |

## Your voice

Copy `templates/voice.md` to `~/.codex/youtube/voice.md` and fill it in. Every skill reads it.
Or send ChatGPT three of your own videos and say "write my voice profile from these".

## The tools

Six dependency-free Python scripts, no packages to install: `hookscore.py`, `title.py`,
`deadair.py`, `chapters.py`, `retention.py`, `swipe.py`.

MIT.
