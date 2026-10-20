"""The user documentation points users to the studio and matches its behaviour (PO-10).

- docs/USER_GUIDE.md has the "Studio: System Composer workflow" chapter: it
  indexes every docs/features/*.md page and walks through a GUI-only
  tutorial (architecture → interfaces → profile → requirements → allocation
  → report); README.md links to that chapter and to every feature page.
- Relative links and in-page anchors of README.md, USER_GUIDE.md and
  EXTENDING.md resolve.
- Feature pages do not claim that undo is missing (every edit of every
  feature is a step of the global undo history) or that port directions and
  connectors are exported as SysML comments (they are real syntax).
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
FEATURES = sorted((DOCS / "features").glob("*.md"))
CHAPTER = "4. Studio: System Composer workflow"


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\- ]", "", s)
    return s.replace(" ", "-")


def anchors(text: str) -> set:
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6} (.+)$", text, flags=re.M)}


def links(text: str) -> list:
    """Markdown link targets outside code blocks."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.findall(r"\]\(([^)\s]+)\)", text)


def chapter_text(guide: str) -> str:
    start = guide.index(f"## {CHAPTER}")
    end = guide.index("\n## ", start + 3)
    return guide[start:end]


class StudioChapterTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.guide = (DOCS / "USER_GUIDE.md").read_text(encoding="utf-8")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_chapter_indexes_every_feature_page(self):
        self.assertIn(f"## {CHAPTER}", self.guide)
        chapter = chapter_text(self.guide)
        self.assertTrue(FEATURES, "docs/features/*.md exist")
        for page in FEATURES:
            self.assertIn(f"](features/{page.name})", chapter, f"chapter 4 links {page.name}")

    def test_tutorial_is_gui_only_and_complete(self):
        chapter = chapter_text(self.guide)
        tutorial = chapter[chapter.index("Tutorial"):]
        stages = ["New model", "functional architecture", "physical architecture", "Interface Editor",
                  "Profile Editor", "Apply stereotypes", "Requirements", "Req Perspective",
                  "Allocation", "Model Check", "Generate Report", "Save JSON", "Load JSON"]
        for stage in stages:
            self.assertIn(stage, tutorial, f"the tutorial covers: {stage}")
        # GUI only: no Python, HTTP or MCP steps.
        self.assertNotRegex(tutorial, r"```(python|bash|jsonc?)\b")
        self.assertNotRegex(tutorial, r"/api/|sysml_[a-z_]+|import engine")
        self.assertIn("99_avionics_e2e.mjs", tutorial, "the tutorial names the scenario that replays it")

    def test_readme_points_to_the_studio(self):
        self.assertIn(f"docs/USER_GUIDE.md#{slug(CHAPTER)}", self.readme)
        for page in FEATURES:
            self.assertIn(f"](docs/features/{page.name})", self.readme, f"README links {page.name}")

    def test_links_and_anchors_resolve(self):
        for doc in (ROOT / "README.md", DOCS / "USER_GUIDE.md", DOCS / "EXTENDING.md"):
            text = doc.read_text(encoding="utf-8")
            for target in links(text):
                if re.match(r"^[a-z]+:", target):            # http:, mailto:, ...
                    continue
                path, _, anchor = target.partition("#")
                dest = (doc.parent / path).resolve() if path else doc
                self.assertTrue(dest.exists(), f"{doc.name}: broken link {target}")
                if anchor and dest.suffix == ".md":
                    self.assertIn(anchor, anchors(dest.read_text(encoding="utf-8")),
                                  f"{doc.name}: no heading for #{anchor} in {dest.name}")


STALE_UNDO = [
    r"no (shared )?undo stack",
    r"undo stack yet",
    r"undo[ /-]*redo[^|\n]*\|\s*deferred",
    r"undo[^.\n]*(is|are) deferred",
]
EXPORTED_AS_SYNTAX = ("port direction", "connectors inside definitions", "usages with bodies", "usage bodies")


def stale_statements(text: str) -> list:
    """Sentences of a feature page that contradict the studio's behaviour."""
    found = [m.group(0) for p in STALE_UNDO for m in re.finditer(p, text, flags=re.I)]
    flat = re.sub(r"\s+", " ", text)
    for sentence in re.split(r"(?<=\.)\s+(?=[A-Z(\-\[])", flat):
        low = sentence.lower()
        if "comments" in low and any(c in low for c in EXPORTED_AS_SYNTAX):
            found.append(sentence[:160])
    return found


class FeaturePagesMatchBehaviourTests(unittest.TestCase):

    def test_no_stale_statements(self):
        for page in FEATURES:
            self.assertEqual(stale_statements(page.read_text(encoding="utf-8")), [], page.name)


if __name__ == "__main__":
    unittest.main()
