# Master skills

Three Claude master skills. Free, MIT, no signup, no API key, nothing to connect.

`skills/edit` `skills/virality` `skills/build`

**Edit** cuts the dead space, adds captions and dynamic visuals, and generates any type of stop motion. **Virality** fuses the LinkedIn agent and YouTube agent skills: it finds what's working, then rewrites it in your voice for your audience. **Build** merges the best design and coding skills into one, so you get apps and websites that actually work.

## Install

Paste this repo link into Claude and say `install skills`.

```
https://github.com/Jakeschincariol/master-skills

install skills
```

Or do it yourself, in Claude Code:

```bash
git clone https://github.com/Jakeschincariol/master-skills.git
cp -r master-skills/skills/* ~/.claude/skills/
```

Or as a plugin:

```
/plugin marketplace add Jakeschincariol/master-skills
/plugin install master-skills
```

Then just ask: "edit this video", "make this go viral", "build me a site that...". Or call them directly with `/edit`, `/virality`, `/build`.

## The three

### /edit

Hand it a raw take. It cuts the dead space and filler without clipping words, writes 1 to 3 word captions that sit in the safe zone instead of on your face, plans dynamic visuals that show the thing you're saying at the moment you say it, and turns frames or a live clip into stop motion in any style (clay, paper cut-out, bricks, sticky notes, pixel). Finishes the audio at -14 LUFS with no compression on the voice.

Merges the three best editing skills: [HyperFrames](https://github.com/heygen-com/hyperframes) (motion engine), [Remotion's agent skills](https://github.com/remotion-dev/skills) and [video-use](https://github.com/browser-use/video-use) (transcript-driven editing).

Needs `ffmpeg`. Transcription uses `faster-whisper` if you have it installed, otherwise it takes a transcript you already have.

### /virality

Fuses the [LinkedIn agent](https://github.com/Jakeschincariol/linkedin-agent-skill) and [YouTube agent](https://github.com/Jakeschincariol/youtube-agent-skill) skills into one loop: find the outliers in your niche (views as a multiple of each creator's own median, so one huge account doesn't drown out the signal), break down why they worked (hook formula, format, structure, CTA), rewrite the winner in your voice for your audience, score the hook, and hand you a shoot-ready script with on-screen text, visuals per beat, a caption and a comment-a-keyword CTA.

Fill in `templates/voice.md` once (or paste three of your own captions and say "write my voice file"). Everything reads it.

### /build

Merges the best design skills ([impeccable](https://github.com/pbakaus/impeccable), Anthropic's [frontend-design](https://github.com/anthropics/skills)) with the best coding skills ([gstack](https://github.com/garrytan/gstack), [superpowers](https://github.com/obra/superpowers)) into one path from "I want an app that does X" to a deployed product: a one-page plain-English spec, the simplest stack that works, a real design direction before any code, small verified build steps, a real-browser QA pass at phone, tablet and desktop widths, then ship. `tools/sitecheck.py` crawls the result for broken links, missing alt text, missing meta tags and other things that quietly break a launch.

## The fine print

- Virality can't be guaranteed by anyone. This raises the odds by copying structure from what is already working in your niche and rewriting it in your voice. Results depend on the idea, the delivery and the account.
- Nothing logs into your accounts or scrapes behind a login. Post data comes from what you paste or export, or from public pages.
- The upstream skills are credited and linked, not copied. Install them alongside for the deep versions; each master skill tells Claude when to use them.
- Tools are Python standard library only. Media tools need `ffmpeg` on your PATH.

## Credits

Edit: HyperFrames by HeyGen (Apache-2.0), Remotion agent skills by Remotion, video-use by Browser Use (MIT).
Virality: linkedin-agent-skill and youtube-agent-skill by Jake Schincariol (MIT).
Build: impeccable by Paul Bakaus (Apache-2.0), frontend-design by Anthropic (Apache-2.0), gstack by Garry Tan (MIT), superpowers by Jesse Vincent (MIT).

## License

MIT
