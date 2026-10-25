# Ship checklist

## Before deploy

**Content**
- [ ] Every word is the owner's real copy. No lorem ipsum, no "Your Company", no invented testimonials, numbers or logos.
- [ ] Contact details, prices, hours, addresses and links checked with the owner.
- [ ] Privacy note if the site collects emails or form data; cookie banner only if you actually set non-essential cookies or trackers.

**Technical**
- [ ] `python3 tools/sitecheck.py site/ --strict` passes (or every remaining warning is accepted on purpose).
- [ ] QA checklist done at 375 / 768 / 1440 with zero console errors.
- [ ] Each page: specific `<title>`, meta description, `lang`, viewport, favicon.
- [ ] Social preview: `og:title`, `og:description`, `og:image` (1200x630, absolute https URL) on the home page at least.
- [ ] A `404.html` that matches the site and links home.
- [ ] No `noindex` left over (unless the site should stay out of search), no `localhost` URLs, no test data.
- [ ] No secrets in front-end code. API keys live in the host's environment settings, never in HTML/JS or the git repo (`.env` is in `.gitignore`).
- [ ] Forms deliver for real: submit a test entry and confirm it reaches the owner's inbox or sheet.
- [ ] Images compressed (sitecheck `image-heavy` clean), fonts as woff2, nothing over a few hundred KB without a reason.

## Deploy (ask the owner first: this publishes to the public internet)

The owner creates and logs into their own hosting account. Never ask for or type their password; let them log in in the browser window the CLI opens.

| Host | Best for | Command |
|---|---|---|
| Netlify | static sites, built-in forms | `npx netlify-cli deploy --dir=site` (preview), then `npx netlify-cli deploy --dir=site --prod` |
| Vercel | static sites and Next.js apps | `npx vercel` (preview), then `npx vercel --prod` |
| GitHub Pages | free static hosting from a repo | `gh repo create my-site --public --source=. --push`, then turn on Pages in the repo's Settings > Pages (branch `main`, folder `/` or `/docs`) |
| Cloudflare Pages | static sites, fast global CDN | `npx wrangler pages deploy site --project-name my-site` |

No CLI possible? Zip the `site/` folder and walk the owner through the host's drag-and-drop upload.

Custom domain: add it in the host's dashboard, then set the DNS records the host shows (usually an A record for the bare domain and a CNAME for `www`) at the owner's domain registrar. HTTPS is automatic on all four hosts once DNS resolves.

## After deploy

- [ ] `python3 tools/sitecheck.py https://the-live-url --external` passes.
- [ ] Screenshot pass on the live URL at 375 / 768 / 1440.
- [ ] Real phone check: open the live URL on an actual phone.
- [ ] Submit the live form once; confirm delivery.
- [ ] Paste the URL into a chat app to check the link preview.

## Handoff note (give this to the owner, plain English, one page)

```markdown
# <Site name>: how it works

**Live at:** https://...   **Hosted on:** <host>, account owned by <owner email>
**Code lives in:** <GitHub repo or folder path>

## Change common things
- Text and prices: edit <file>, search for the words you want to change, save, redeploy.
- Photos: replace the file in site/img/ with one of the same name (under 300 KB, about 2000px wide max).
- Redeploy: <exact command or "push to GitHub and it updates in about a minute">.

## Where things go
- Contact form messages go to: <inbox / service>.
- Analytics (if any): <link>.

## Costs and renewals
- Hosting: <free tier / price>. Domain: renews <date> at <registrar>.

## Don't touch
- <files or settings that break the site>

## Known limits and next steps
- <honest list: what is not built yet, what would need a developer>
```
