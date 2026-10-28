import datetime as dt
import io
import json
import unittest
from contextlib import redirect_stdout

from a4m import cli
from a4m.adr import new_adr
from a4m.build import MARKER, build, render_view
from a4m.export_mermaid import render_archimate
from a4m.landscape import build_landscape
from a4m.mcp_server import handle
from a4m.paths import SCHEMA_PATH
from a4m.rules import load_rules
from a4m.schema import schema_json
from a4m.views import view_members, view_relationships
from a4m.workspace import Workspace
from tests.helpers import WorkspaceTestCase, load_sample


class MermaidTest(unittest.TestCase):
    def test_flowchart_structure(self):
        model = load_sample("nextcloud")
        view = model.views["view-layered"]
        text = render_archimate(model, view)
        self.assertTrue(text.startswith("flowchart TB\n"))
        for layer in ("business", "information", "application", "infrastructure"):
            self.assertIn(f"subgraph layer_{layer}", text)
            self.assertIn(f"classDef {layer} fill:", text)
        edges = [line for line in text.splitlines() if "|\"" in line]
        members = view_members(model, view, load_rules())
        self.assertEqual(len(edges), len(view_relationships(model, members)))
        self.assertIn('app_nextcloud_web -.->|"reads/writes"| data_files', text)
        # other SAs' elements are captioned with their SA and drawn dashed
        self.assertIn('dns__app_svc_dns("DNS resolution and filtering<br/>«ApplicationService» · dns")', text)
        self.assertRegex(text, r"class .*dns__app_svc_dns.* foreign")

    def test_quotes_are_escaped(self):
        model = load_sample("nextcloud")
        model.elements["app-nextcloud"].name = 'Next "cloud"'
        text = render_archimate(model, model.views["view-layered"])
        self.assertIn("Next #quot;cloud#quot;", text)

    def test_change_highlighting(self):
        model = load_sample("backup")
        view = model.views["view-overview"]
        styled = render_view(model, view)
        self.assertIn("Backblaze B2<br/>«ApplicationComponent»<br/>RETIRING", styled)
        self.assertIn("class app_offsite_hetzner st_new", styled)
        self.assertRegex(styled, r"linkStyle \d+ stroke:#c62828")
        baseline, target = render_view(model, view, state="baseline"), render_view(model, view, state="target")
        self.assertIn("app_offsite_b2", baseline)
        self.assertNotIn("app_offsite_hetzner", baseline)
        self.assertNotIn("app_offsite_b2", target)
        self.assertNotIn("RETIRING", baseline + target)


class BuildTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.copy_samples()

    def test_build_writes_docs_and_prunes_stale(self):
        stale = self.root / "docs/nextcloud/view-gone.md"
        stale.parent.mkdir(parents=True)
        stale.write_text(MARKER + "\nold", encoding="utf-8")
        handwritten = self.root / "docs/nextcloud/notes.md"
        handwritten.write_text("# my notes", encoding="utf-8")
        result = build(self.load("nextcloud"), self.root)
        self.assertTrue(result.oef.exists())
        self.assertFalse(stale.exists())
        self.assertTrue(handwritten.exists())
        page = (self.root / "docs/nextcloud/c4-containers.md").read_text(encoding="utf-8")
        self.assertIn("```mermaid\nC4Container", page)
        self.assertIn("ADR-0001", page)  # related decisions are linked
        index = (self.root / "docs/nextcloud/README.md").read_text(encoding="utf-8")
        self.assertIn("**Used by:** [backup](../backup/README.md), [media](../media/README.md)", index)

    def test_view_page_shows_both_states_when_something_changes(self):
        build(self.load("backup"), self.root)
        page = (self.root / "docs/backup/view-overview.md").read_text(encoding="utf-8")
        self.assertEqual(page.count("```mermaid"), 3)
        self.assertIn("<details><summary>Target state</summary>", page)
        self.assertIn("| new | Flow | `app-backup` → `app-offsite-hetzner`", (self.root / "docs/backup/README.md").read_text(encoding="utf-8"))

    def test_landscape(self):
        gone = self.root / "docs/old-sa/README.md"
        gone.parent.mkdir(parents=True)
        gone.write_text(MARKER + "\nold", encoding="utf-8")
        result = build_landscape(Workspace(self.root), self.root)
        self.assertTrue((self.root / "build/_landscape.oef.xml").exists())
        self.assertFalse(gone.parent.exists())  # docs of a removed SA are pruned
        index = (self.root / "docs/README.md").read_text(encoding="utf-8")
        self.assertIn("| [Media streaming](media/README.md) (`media`) | solution | proposed |", index)
        self.assertIn('sa_media -.->|"1"| sa_nextcloud', index)  # all-new dependency is dashed
        consumers = (self.root / "docs/_landscape/consumers.md").read_text(encoding="utf-8")
        self.assertIn("## Nextcloud (`nextcloud`, solution)", consumers)
        self.assertIn("[media](../media/README.md)", consumers)
        self.assertEqual(len(result.docs), 4)


class AdrTest(WorkspaceTestCase):
    BASE = "elements:\n  - { id: app-a, type: ApplicationComponent, name: A }\nviews:\n  - { id: view-a, name: A, include: [app-a] }\n"

    def adr(self, number, front):
        return {f"decisions/ADR-{number:04d}-x.md": f"---\nid: ADR-{number:04d}\ntitle: T\ndate: 2026-01-01\n{front}---\nbody\n"}

    def test_valid(self):
        self.write_sa("s", {"a.yaml": self.BASE, **self.adr(1, "status: accepted\naffects: [app-a]\n")})
        self.assertEqual(self.codes("s"), ["orphan"])

    def test_unknown_reference_and_status(self):
        self.write_sa("s", {"a.yaml": self.BASE, **self.adr(1, "status: done\naffects: [app-zzz]\n")})
        codes = self.codes("s", "error")
        self.assertIn("adr-unknown-ref", codes)
        self.assertIn("adr-status", codes)

    def test_supersession_and_numbering(self):
        self.write_sa("s", {
            "a.yaml": self.BASE,
            **self.adr(1, "status: superseded\naffects: [app-a]\n"),
            **self.adr(3, "status: accepted\naffects: [app-a]\nsupersedes: [ADR-0001]\n"),
        })
        self.assertIn("adr-supersession", self.codes("s", "error"))
        self.assertIn("adr-numbering", self.codes("s", "warning"))

    def test_new_adr_numbers_sequentially(self):
        sa = self.write_sa("s", {"a.yaml": self.BASE, **self.adr(1, "status: accepted\naffects: [app-a]\n")})
        path = new_adr(sa, "Use: colons safely", today=dt.date(2026, 10, 23))
        self.assertEqual(path.name, "ADR-0002-use-colons-safely.md")
        record = next(r for r in self.load("s").adrs if r.id == "ADR-0002")
        self.assertEqual(record.title, "Use: colons safely")


class SchemaTest(unittest.TestCase):
    def test_committed_schema_is_current(self):
        self.assertEqual(SCHEMA_PATH.read_text(encoding="utf-8"), schema_json(), "run `python3 -m a4m schema --write`")


class CliTest(unittest.TestCase):
    def run_cli(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.main(list(argv))
        return code, out.getvalue()

    def test_validate_all(self):
        code, out = self.run_cli("validate")
        self.assertEqual(code, 0)
        self.assertIn("OK: nextcloud", out)
        self.assertIn("OK: enterprise", out)

    def test_validate_json(self):
        code, out = self.run_cli("validate", "nextcloud", "--format", "json")
        self.assertTrue(json.loads(out)["ok"])

    def test_sas_and_impact(self):
        code, out = self.run_cli("sas")
        self.assertRegex(out, r"media\s+solution\s+proposed")
        code, out = self.run_cli("impact", "dns/app-svc-dns")
        for consumer in ("home-automation", "media", "nextcloud"):
            self.assertIn(f"{consumer} (", out)
        self.assertIn("[new]", out)  # media's dependency is proposed

    def test_allowed(self):
        code, out = self.run_cli("allowed", "Node", "ApplicationComponent", "--format", "json")
        self.assertNotIn("Assignment", json.loads(out)["allowed"])


class McpTest(unittest.TestCase):
    def call(self, method, params=None, msg_id=1):
        return handle({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})

    def tool(self, name, **arguments):
        result = self.call("tools/call", {"name": name, "arguments": arguments})["result"]
        return result, result["content"][0]["text"]

    def test_handshake_and_listing(self):
        init = self.call("initialize", {"protocolVersion": "2025-03-26"})["result"]
        self.assertEqual(init["protocolVersion"], "2025-03-26")
        self.assertIn("tools", init["capabilities"])
        names = {t["name"] for t in self.call("tools/list")["result"]["tools"]}
        self.assertTrue({"a4m_validate", "a4m_list_sas", "a4m_impact"} <= names)
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools(self):
        result, text = self.tool("a4m_allowed", source_type="Node", target_type="SystemSoftware")
        self.assertIn("Assignment", json.loads(text)["allowed"])
        result, text = self.tool("a4m_validate")
        self.assertTrue(json.loads(text)["ok"])
        result, text = self.tool("a4m_render_view", sa="nextcloud", view="c4-context")
        self.assertTrue(text.startswith("C4Context"))
        result, text = self.tool("a4m_get", id="dns/app-pihole")
        self.assertEqual(json.loads(text)["c4"], "system")
        result, text = self.tool("a4m_get", sa="nextcloud", id="nope")
        self.assertTrue(result["isError"])
        result, text = self.tool("a4m_render_view", view="c4-context")
        self.assertTrue(result["isError"])  # sa is required: there are several

    def test_cross_sa_tools(self):
        result, text = self.tool("a4m_search", query="docker")
        hit = next(h for h in json.loads(text)["matches"] if h["id"] == "compute/infra-docker")
        self.assertEqual((hit["sa"], hit["exported"]), ("compute", True))
        result, text = self.tool("a4m_impact", ref="nextcloud")
        self.assertEqual({u["consumer"] for u in json.loads(text)}, {"backup", "media"})
        result, text = self.tool("a4m_list_sas")
        media = next(s for s in json.loads(text) if s["sa"] == "media")
        self.assertEqual((media["status"], media["used_by"]), ("proposed", []))

    def test_unknown_method(self):
        self.assertEqual(self.call("resources/list")["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
