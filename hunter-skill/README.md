# The Hunter skill

Eleven Claude skills that land you the job. Free, MIT, no signup, no API key, nothing to connect.

`skills/hunter-scout` `skills/hunter-resume` `skills/hunter-research`
`skills/hunter-linkedin` `skills/hunter-connector` `skills/hunter-cover`
`skills/hunter-apply` `skills/hunter-interview` `skills/hunter-salary`
`skills/hunter-followup` `skills/hunter-tracker`

One finds the best job listings and ranks them by fit. One rewrites your resume for every role. One researches each company. One optimizes your LinkedIn for the job. And one is the connector: it finds the hiring manager, researches them, reaches out and books the coffee chat before your application is even sent.

So instead of sending thousands of resumes and never hearing back, you go in with a warm intro, a resume that reads like the job description, and the company's own interview loop in your head.

Nothing is ever sent or submitted without your yes. Claude drafts, you approve, it goes out from your own accounts.

## Install

Paste this repo link into Claude and say `install skill`:

```
https://github.com/Jakeschincariol/hunter-skill

install skill
```

Or as a plugin, in Claude Code:

```
/plugin marketplace add Jakeschincariol/hunter-skill
/plugin install hunter-skill@hunter-skill
```

Claude Code namespaces plugin skills, so installed as a plugin they show up as
`/hunter-skill:hunter-scout` and so on. Copy the folders instead if you want
plain `/hunter-scout`:

```bash
git clone https://github.com/Jakeschincariol/hunter-skill.git
cp -r hunter-skill/skills/hunter-* ~/.claude/skills/
```

No Claude Code at all? Paste any single `SKILL.md` at the top of a chat and it
runs as a mode. You lose the Python tools, but the method works. The tools need
Python 3.8 or newer. Nothing to pip install.

## The eleven

| skill | job | what it does |
| --- | --- | --- |
| `skills/hunter-scout` | Job Scout | Searches public job boards (Greenhouse, Lever, Ashby, NVIDIA, Netflix and 40+ companies) and ranks every listing by fit with your profile, with the reasons. |
| `skills/hunter-resume` | Resume Writer | Rewrites your resume for each role so it reads like the job description, scores it with a stated formula, and refuses anything you did not actually do. |
| `skills/hunter-research` | Company Researcher | Builds a brief on each company: the business, recent filings and news, the team, and the interview loop from the company's own prep pages. |
| `skills/hunter-linkedin` | LinkedIn Optimizer | Rewrites your headline, About and skills for the job you want, checked against LinkedIn's limits and the posting's keywords. |
| `skills/hunter-connector` | The Connector | Finds the hiring manager, researches their public work, drafts the LinkedIn note and the email, follows up politely and books the coffee chat. |
| `skills/hunter-cover` | Cover Letter Writer | Writes a specific cover letter for every application and checks it for clichés, placeholders and the wrong company's name. |
| `skills/hunter-apply` | Application Assistant | Fills each application form from your saved answers and stops before Submit, so you send it. |
| `skills/hunter-interview` | Interview Coach | Runs mock interviews with the question types each company says it asks, and checks your answers for STAR and a number. |
| `skills/hunter-salary` | Salary Negotiator | Works out total comp (base, bonus, equity, vesting), compares offers, benchmarks with public data and scripts your counter. |
| `skills/hunter-followup` | Follow-up Manager | Tells you what is due today and drafts the polite nudge, with stop rules so no one gets pestered. |
| `skills/hunter-tracker` | Pipeline Tracker | Tracks every role, contact and next step in one `hunter/pipeline.json`. |

## How to use it

Everything lands in a `hunter/` folder in your project, and each skill reads
what the last one wrote.

An example: Jordan Reyes, a Software Engineer in Chicago, going for Google.

1. **`hunter-scout`** searches the boards for backend and infrastructure
   roles, scores each against Jordan's profile and saves the best to
   `hunter/jobs.json`. Google's own careers site does not allow scripts, so
   the skill walks Jordan through a saved search there instead.
2. **`hunter-research`** builds `hunter/companies/google.md`: the business, the
   latest 10-K and earnings 8-K, the Cloud infrastructure team, and Google's
   hiring process from Google's own pages.
3. **`hunter-resume`** rewrites Jordan's resume against the posting. The match
   score goes from 54 to 96, and every number and skill in the new version is
   traced back to the old one.
4. **`hunter-linkedin`** rewrites the headline and About for the role and fills
   the skills the posting asks for.
5. **`hunter-connector`** finds the hiring manager from the posting and the
   team page, researches their public talks and posts, guesses their work
   email with a confidence score, and drafts a 74-character LinkedIn note and
   a short email. Jordan says yes to each one. Two polite follow-ups at most,
   then it stops. When the manager replies, it books the coffee chat on
   Jordan's calendar, with Jordan's OK.
6. **`hunter-cover`**, **`hunter-apply`**: the letter, then the form filled and
   left for Jordan to submit.
7. **`hunter-interview`** runs the loop: coding, system design, behavioral.
8. **`hunter-salary`** when the offer comes: total comp by year, the counter.
9. **`hunter-followup`** and **`hunter-tracker`** keep every thread moving.

## The tools

All standard-library Python. The network tools read public pages and APIs only,
identify themselves, and go slowly.

```bash
python3 skills/hunter-scout/jobs.py search                          # ranked listings -> hunter/jobs.json
python3 skills/hunter-research/brief.py build --company Google --role "Software Engineer"
python3 skills/hunter-resume/ats.py score hunter/resumes/base.md --jd hunter/resumes/google.jd.md
python3 skills/hunter-linkedin/profile.py keywords --job hunter/jd/google-swe.txt
python3 skills/hunter-connector/emails.py --help                    # likely addresses + confidence
python3 skills/hunter-connector/outreach.py --help                  # drafts, yeses, follow-ups
python3 skills/hunter-cover/cover.py cliches
python3 skills/hunter-apply/answers.py --help
python3 skills/hunter-interview/star.py loop --company google
python3 skills/hunter-salary/offer.py total hunter/offers/google.json
python3 skills/hunter-followup/followup.py due
python3 skills/hunter-tracker/pipeline.py init
```

```bash
python3 -m unittest discover -s tests -v
```

## Fine print

**Nothing goes out without your yes.** Every message, follow-up and application
is a draft until you approve that exact one. Emails go through your own email
as drafts first. LinkedIn messages are sent by you: LinkedIn's terms forbid bots
and automated messaging, so Claude drafts and you click Send. Application forms
are filled and left for you to submit.

**Public, professional information only.** The connector researches a person's
public work: their profile, posts, talks, papers, the company site. Never their
personal life, family, home or private accounts. Guessed email addresses are
marked as guesses with a confidence, never as verified.

**Stop rules.** At the first "no" or any sign they are not interested, it stops.
Two follow-ups at most. Nothing after 21 days of silence. A request to stop is
honoured forever.

**Never invents anything.** No made-up jobs, titles, degrees, dates or numbers on
a resume, a cover letter, LinkedIn or a form. It rewrites and reorders what is
true, and asks when something is missing.

**Sources are cited.** Interview loops come from each company's own published
prep pages, and anything else is marked community-reported. Salary benchmarks
come from public data (BLS) or ranges you supply, with the source shown.

**No guarantees.** It makes you better prepared and better connected. It cannot
promise an interview, an offer or a number.

## Files

```
skills/hunter-scout/       SKILL.md, jobs.py, boards.json
skills/hunter-resume/      SKILL.md, ats.py, terms.json, examples/
skills/hunter-research/    SKILL.md, brief.py, brief.template.md, companies.json, loops.json
skills/hunter-linkedin/    SKILL.md, profile.py, limits.json, linkedin.example.json
skills/hunter-connector/   SKILL.md, emails.py, outreach.py
skills/hunter-cover/       SKILL.md, cover.py, example-cover.md
skills/hunter-apply/       SKILL.md, answers.py, profile.example.json
skills/hunter-interview/   SKILL.md, star.py, questions.json, example-answer.md
skills/hunter-salary/      SKILL.md, offer.py, offer.example.json, competing.example.json, bench.example.json
skills/hunter-followup/    SKILL.md, followup.py, templates.json
skills/hunter-tracker/     SKILL.md, pipeline.py, pipeline.example.json
tests/                     unittest suite + offline fixtures
```

MIT. Made by [Jake Schincariol](https://opusjake.ai).
