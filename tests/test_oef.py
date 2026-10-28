import os
import unittest
import xml.etree.ElementTree as ET

from a4m.export_oef import NS, XSI, export_oef
from a4m.import_oef import import_oef
from a4m.landscape import landscape_model
from a4m.model import load_model
from a4m.paths import TOOL_ROOT
from a4m.workspace import Workspace
from tests.helpers import WorkspaceTestCase, load_sample

X = f"{{{NS}}}"
T = f"{{{XSI}}}type"


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_sample("nextcloud")
        cls.xml = export_oef(cls.model)
        cls.root = ET.fromstring(cls.xml)

    def test_all_concepts_exported(self):
        self.assertEqual(len(self.root.findall(f"{X}elements/{X}element")), len(self.model.elements))
        self.assertEqual(len(self.root.findall(f"{X}relationships/{X}relationship")), len(self.model.relationships))
        views = [v.get("identifier") for v in self.root.findall(f"{X}views/{X}diagrams/{X}view")]
        # media proposes to read nextcloud's files, so the layered view also gets current/target copies
        self.assertEqual(sorted(views), sorted([*self.model.views, "view-layered--baseline", "view-layered--target"]))

    def test_identifiers_unique_and_references_resolve(self):
        for xml in (self.xml, export_oef(load_sample("backup")), export_oef(landscape_model(Workspace(TOOL_ROOT), with_sa_views=True))):
            root = ET.fromstring(xml)
            ids = [n.get("identifier") for n in root.iter() if n.get("identifier")]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertFalse([i for i in ids if "/" in i], "xs:ID cannot contain '/'")
            known = set(ids)
            for node in root.iter():
                for attr in ("source", "target", "elementRef", "relationshipRef", "propertyDefinitionRef"):
                    if node.get(attr):
                        self.assertIn(node.get(attr), known, f"{attr}={node.get(attr)}")

    def test_other_sas_elements_are_marked(self):
        pihole = next(e for e in self.root.iter(f"{X}element") if e.get("identifier") == "dns.app-pihole")
        names = {d.get("identifier"): d.findtext(f"{X}name") for d in self.root.iter(f"{X}propertyDefinition")}
        props = {names[p.get("propertyDefinitionRef")]: p.findtext(f"{X}value") for p in pihole.iter(f"{X}property")}
        self.assertEqual(props["a4m:sa"], "dns")

    def test_access_and_influence_attributes(self):
        root = ET.fromstring(export_oef(load_sample("enterprise")))
        rels = {r.get("identifier"): r for r in root.iter(f"{X}relationship")}
        self.assertEqual(rels["rel-bus-proc-share-access-bus-obj-photos"].get("accessType"), "ReadWrite")
        self.assertEqual(rels["rel-bus-drv-privacy-influence-bus-goal-reliable"].get("modifier"), "+")

    def test_c4_tags_travel_as_properties(self):
        names = {d.findtext(f"{X}name") for d in self.root.iter(f"{X}propertyDefinition")}
        self.assertTrue({"a4m:c4", "a4m:c4_shape", "a4m:sa"} <= names)

    def test_layer_groups_contain_elements_with_absolute_bounds(self):
        view = next(v for v in self.root.iter(f"{X}view") if v.get("identifier") == "view-layered")
        groups = [n for n in view.findall(f"{X}node") if n.get(T) == "Container"]
        self.assertEqual([g.findtext(f"{X}label") for g in groups], ["Business", "Information", "Application", "Infrastructure"])
        for group in groups:
            gx, gy, gw, gh = (int(group.get(k)) for k in "xywh")
            for child in group.findall(f"{X}node"):
                x, y = int(child.get("x")), int(child.get("y"))
                self.assertTrue(gx <= x < gx + gw and gy <= y < gy + gh, "child bounds must be absolute, inside the group")

    def test_changes_are_highlighted_with_state_copies(self):
        root = ET.fromstring(export_oef(load_sample("backup")))
        views = {v.get("identifier"): v for v in root.iter(f"{X}view")}
        self.assertTrue({"view-overview", "view-overview--baseline", "view-overview--target"} <= set(views))
        refs = lambda v: {n.get("elementRef") for n in v.iter(f"{X}node") if n.get("elementRef")}
        self.assertNotIn("app-offsite-hetzner", refs(views["view-overview--baseline"]))
        self.assertNotIn("app-offsite-b2", refs(views["view-overview--target"]))
        hetzner = next(n for n in views["view-overview"].iter(f"{X}node") if n.get("elementRef") == "app-offsite-hetzner")
        self.assertEqual(hetzner.find(f"{X}style/{X}lineColor").get("g"), "125")  # #2e7d32: new

    @unittest.skipUnless(os.environ.get("A4M_XSD"), "set A4M_XSD=<path to archimate3_Diagram.xsd> to validate against the schema")
    def test_against_open_group_xsd(self):
        import xmlschema  # optional dependency

        schema = xmlschema.XMLSchema(os.environ["A4M_XSD"])
        for xml in (self.xml, export_oef(load_sample("backup")), export_oef(landscape_model(Workspace(TOOL_ROOT), with_sa_views=True))):
            self.assertEqual([e.reason for e in schema.iter_errors(xml)], [])


class RoundTripTest(WorkspaceTestCase):
    def setUp(self):
        super().setUp()
        self.copy_samples()

    def test_import_into_existing_sa_is_lossless(self):
        for sa in ("nextcloud", "backup", "media", "enterprise"):
            with self.subTest(sa=sa):
                before = export_oef(self.load(sa))
                oef = self.root / f"{sa}.xml"
                oef.write_text(before, encoding="utf-8")
                result = import_oef(oef, sa, self.root)
                self.assertEqual(result.renamed, {})
                after_model = self.load(sa)
                self.assertEqual(export_oef(after_model), before)
        nextcloud = self.load("nextcloud")
        # concepts stay in their original files; other SAs' elements are not copied in
        self.assertEqual(nextcloud.elements["app-nextcloud"].file, "models/nextcloud/application/nextcloud.yaml")
        self.assertFalse(list((self.root / "models/nextcloud").rglob("imported.yaml")))
        self.assertEqual(nextcloud.views["c4-deployment"].kind, "c4-deployment")
        self.assertEqual(nextcloud.views["view-layered"].include_layers, ["business", "information", "application", "infrastructure"])
        self.assertEqual(nextcloud.views["view-layered"].layout, {})
        self.assertEqual(self.load("backup").elements["app-offsite-b2"].state, "retiring")

    def test_import_new_sa_from_archi_style_ids(self):
        sample = self.load("nextcloud")
        xml = export_oef(sample)
        # Simulate an element created in Archi: uuid-style identifier.
        xml = xml.replace('"app-svc-file-sync"', '"id-0123456789abcdef0123456789abcdef"')
        oef = self.root / "archi.xml"
        oef.write_text(xml, encoding="utf-8")
        result = import_oef(oef, "fresh", self.root)
        self.assertEqual(result.renamed.pop("id-0123456789abcdef0123456789abcdef"), "app-file-sync-and-share")
        # relationships of the renamed element get new default ids (rel-<source>-<type>-<target>)
        self.assertTrue(result.renamed and all(new.startswith("rel-app-file-sync-and-share-") for new in result.renamed.values()))
        imported = load_model("fresh", self.root)
        self.assertEqual(len(imported.own_elements()), len(sample.own_elements()))
        self.assertEqual(len(imported.own_relationships()), len(sample.own_relationships()))
        self.assertEqual(imported.elements["app-nextcloud"].c4, "system")
        self.assertIn("dns/app-svc-dns", imported.referenced)  # references to other SAs survive
        self.assertTrue((self.root / "models/fresh/application/imported.yaml").exists())

    def test_moved_nodes_are_kept_as_layout(self):
        xml = export_oef(self.load("nextcloud"))
        xml = xml.replace('elementRef="app-nextcloud-web" xsi:type="Element" x="', 'elementRef="app-nextcloud-web" xsi:type="Element" x="9', 1)
        oef = self.root / "moved.xml"
        oef.write_text(xml, encoding="utf-8")
        import_oef(oef, "nextcloud", self.root)
        view = self.load("nextcloud").views["view-layered"]
        self.assertIn("app-nextcloud-web", view.layout)
        self.assertTrue(str(view.layout["app-nextcloud-web"][0]).startswith("9"))


if __name__ == "__main__":
    unittest.main()
