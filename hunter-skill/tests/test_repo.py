import json
import os
import re
import unittest

from _load import ROOT, SKILLS as SKILL_DIR

SKILLS = ["hunter-scout", "hunter-resume", "hunter-research", "hunter-linkedin", "hunter-connector",
          "hunter-cover", "hunter-apply", "hunter-interview", "hunter-salary", "hunter-followup",
          "hunter-tracker"]
ABOUT = ("11 Claude skills that land you the job: listings, resume, research, LinkedIn and warm intros "
         "to the hiring manager.")
# skills that can send or submit something on the user's behalf carry the consent rule
SENDS = ["hunter-connector", "hunter-apply", "hunter-followup"]


def frontmatter(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    return (m.group(1) if m else ""), text


def every_text_file():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for f in files:
            if f.endswith((".md", ".py", ".json", ".csv", ".txt", ".xml", ".html")) or f == "LICENSE":
                yield os.path.join(base, f)


class Repo(unittest.TestCase):
    def test_eleven_skill_folders(self):
        found = sorted(d for d in os.listdir(SKILL_DIR)
                       if os.path.isfile(os.path.join(SKILL_DIR, d, "SKILL.md")))
        self.assertEqual(found, sorted(SKILLS))

    def test_root_matches_the_reel(self):
        root = sorted(d for d in os.listdir(ROOT) if not d.startswith(".git"))
        self.assertEqual(root, sorted([".claude-plugin", "LICENSE", "README.md", "skills", "tests"]))

    def test_frontmatter_name_and_description(self):
        for s in SKILLS:
            fm, text = frontmatter(os.path.join(SKILL_DIR, s, "SKILL.md"))
            self.assertIn("name: %s\n" % s, fm + "\n", s)
            self.assertRegex(fm, r"description: ", s)
            self.assertGreater(len(fm), 200, "%s description is too thin" % s)
            self.assertGreater(len(text.splitlines()), 60, s)

    def test_sending_skills_ask_first(self):
        for s in SENDS:
            _, text = frontmatter(os.path.join(SKILL_DIR, s, "SKILL.md"))
            low = " ".join(text.lower().split())
            self.assertIn("yes", low, s)
            self.assertRegex(low, r"never (send|sends|submit|submits)", s)

    def test_plugin_manifests(self):
        with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as fh:
            plugin = json.load(fh)
        self.assertEqual(plugin["name"], "hunter-skill")
        self.assertEqual(plugin["description"], ABOUT)
        with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as fh:
            market = json.load(fh)
        self.assertEqual(market["name"], "hunter-skill")
        self.assertEqual(market["plugins"][0]["name"], "hunter-skill")

    def test_readme_carries_the_reel_copy(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
            readme = " ".join(fh.read().split())
        self.assertTrue(readme.startswith("# The Hunter skill"))
        for line in ("Eleven Claude skills that land you the job. Free, MIT, no signup, no API key, nothing to connect.",
                     "https://github.com/Jakeschincariol/hunter-skill install skill",
                     "/plugin marketplace add Jakeschincariol/hunter-skill",
                     "/plugin install hunter-skill@hunter-skill",
                     "## Fine print"):
            self.assertIn(line, readme)
        for s in SKILLS:
            self.assertIn("skills/" + s, readme, s)

    def test_no_em_dashes_and_no_personal_email(self):
        for path in every_text_file():
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            self.assertNotIn("\u2014", text, rel)
            self.assertNotIn("jakeschincariol" + "@" + "gmail.com", text, rel)


if __name__ == "__main__":
    unittest.main()
