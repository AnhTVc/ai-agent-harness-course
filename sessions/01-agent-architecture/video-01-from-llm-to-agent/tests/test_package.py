"""Guard the handoff's learning links, source map, and English-only constraint."""

import re
import unittest
from pathlib import Path
from agent_lab.architecture import NODES, EDGES, MODE_VIEWS, MODE_EDGES
from agent_lab.runtime import Execution

LESSON = Path(__file__).resolve().parents[1]
ROOT = LESSON.parents[2]


class PackageTests(unittest.TestCase):
    """Validate learner-facing package invariants independently of rendering."""

    def test_local_markdown_links_resolve(self):
        for document in ROOT.rglob("*.md"):
            for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text()):
                if target.startswith(("https://", "http://", "#")):
                    continue
                path = target.split("#")[0]
                self.assertTrue(
                    (document.parent / path).exists(),
                    f"Broken link in {document.name}: {path}",
                )

    def test_diagram_nodes_have_real_source_and_ui_targets(self):
        ids = {node["id"] for node in NODES}
        for action in Execution.PLANS.values():
            self.assertIn(action[0], ids)
        for edge in EDGES:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)
            self.assertTrue(edge["path"].startswith("M"))
        for node in NODES:
            with self.subTest(node=node["id"]):
                self.assertEqual(len(node["position"]), 4)
                source = (LESSON / "src/agent_lab" / node["file"]).read_text()
                self.assertIn(node["symbol"], source)
                self.assertTrue(node["description"])

    def test_execution_modes_have_distinct_visible_control_paths(self):
        """Keep each teaching mode visually honest about who controls execution."""
        self.assertEqual(set(MODE_VIEWS), {"agent", "workflow", "chatbot"})
        all_node_ids = {node["id"] for node in NODES}
        all_edge_ids = {edge["id"] for edge in EDGES + MODE_EDGES}

        paths = []
        for mode, view in MODE_VIEWS.items():
            with self.subTest(mode=mode):
                self.assertTrue(view["decision_owner"])
                self.assertTrue(view["description"])
                self.assertTrue(set(view["node_ids"]) <= all_node_ids)
                self.assertTrue(set(view["edge_ids"]) <= all_edge_ids)
                paths.append(tuple(view["edge_ids"]))

        self.assertEqual(len(set(paths)), 3)
        self.assertNotIn("model", MODE_VIEWS["workflow"]["node_ids"])
        self.assertNotIn("executor", MODE_VIEWS["chatbot"]["node_ids"])
        self.assertIn("schema-model", MODE_VIEWS["agent"]["edge_ids"])
        self.assertIn("model-runtime", MODE_VIEWS["agent"]["edge_ids"])
        self.assertIn("environment-runtime", MODE_VIEWS["agent"]["edge_ids"])

    def test_each_execution_mode_has_a_distinct_layout_and_route(self):
        """Make control-pattern changes visible through both topology and placement."""
        layouts = [
            tuple(
                (node, tuple(view["positions"][node]))
                for node in sorted(view["positions"])
            )
            for view in MODE_VIEWS.values()
        ]
        routes = [
            tuple(sorted(view["edge_paths"].items())) for view in MODE_VIEWS.values()
        ]

        self.assertEqual(len(set(layouts)), len(MODE_VIEWS))
        self.assertEqual(len(set(routes)), len(MODE_VIEWS))
        for mode, view in MODE_VIEWS.items():
            with self.subTest(mode=mode):
                self.assertEqual(set(view["positions"]), {node["id"] for node in NODES})
                self.assertEqual(set(view["edge_paths"]), set(view["edge_ids"]))
                self.assertTrue(
                    all(path.startswith("M") for path in view["edge_paths"].values())
                )

    def test_web_provider_picker_exposes_cloudflare(self):
        """Keep the real remote provider discoverable in the runnable debugger."""
        page = (LESSON / "src/web/index.html").read_text()
        self.assertRegex(
            page,
            r'<option value="cloudflare">\s*Cloudflare Workers AI · hosted LLM\s*</option>',
        )
        self.assertIn('"config.py"', (LESSON / "src/agent_lab/server.py").read_text())

    def test_lesson_readme_maps_the_real_runtime_and_debugger_files(self):
        """Make the video guide a useful entry point into the implementation."""
        guide = (LESSON / "README.md").read_text()
        for source_path in (
            "src/agent_lab/runtime.py",
            "src/agent_lab/debugger.py",
            "src/agent_lab/providers.py",
            "src/agent_lab/tools.py",
            "src/agent_lab/architecture.py",
            "src/agent_lab/server.py",
            "src/web/app.js",
            "src/web/index.html",
            "src/web/style.css",
        ):
            with self.subTest(source_path=source_path):
                self.assertIn(source_path, guide)
        self.assertIn("one runtime boundary", guide.lower())
        self.assertIn("mermaid", guide.lower())

    def test_root_gitignore_protects_local_and_generated_files(self):
        """Keep credentials, local traces, and Python output out of Git handoff."""
        gitignore = (ROOT / ".gitignore").read_text()
        rules = {
            line.strip()
            for line in gitignore.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertIn("**/.env", rules)
        self.assertIn("**/artifacts/", rules)
        self.assertIn("**/.coverage", rules)
        self.assertIn("**/__pycache__/", rules)
        self.assertIn("**/.pytest_cache/", rules)
        self.assertIn("**/.venv/", rules)
        self.assertNotIn("**/.env*", rules)
        self.assertTrue((LESSON / ".env.example").is_file())

    def test_dev_requirements_install_test_and_format_tools(self):
        """Make the documented verification commands available in a fresh setup."""
        dependencies = {
            line.split("==", maxsplit=1)[0]
            for line in (LESSON / "requirements-dev.txt").read_text().splitlines()
            if line and not line.startswith("#")
        }

        self.assertTrue({"pytest", "pytest-cov", "coverage", "black"} <= dependencies)

    def test_artifacts_do_not_contain_vietnamese_characters(self):
        # This character check complements a manual English copy review; it is
        # not a general natural-language classifier. Paths outside ROOT are ignored.
        vietnamese = re.compile(
            "[\u0102\u0103\u0110\u0111\u0128\u0129\u0168\u0169\u01a0\u01a1\u01af\u01b0\u1ea0-\u1ef9]"
        )
        for path in ROOT.rglob("*"):
            # Source-slide UI and assets are supplied artwork; every Markdown
            # guide remains part of the English-only documentation contract.
            if "presentation" in path.relative_to(ROOT).parts and path.suffix != ".md":
                continue
            if path.is_file() and path.suffix in (
                ".py",
                ".js",
                ".css",
                ".html",
                ".md",
                ".json",
                ".yml",
                ".txt",
            ):
                self.assertIsNone(
                    vietnamese.search(path.read_text()), str(path.relative_to(ROOT))
                )


if __name__ == "__main__":
    unittest.main()
