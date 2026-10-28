import unittest

from a4m.model import load_model
from a4m.paths import TOOL_ROOT
from a4m.rules import load_rules
from a4m.validate import validate
from a4m.views import view_members
from a4m.workspace import Workspace
from tests.helpers import WorkspaceTestCase

BASE = """
elements:
  - { id: app-a, type: ApplicationComponent, name: A }
  - { id: app-svc, type: ApplicationService, name: Service }
  - { id: infra-node, type: Node, name: Node }
relationships:
  - { type: Realization, source: app-a, target: app-svc }
  - { type: Realization, source: infra-node, target: app-a }
views:
  - { id: view-all, name: All, include_layers: [application, infrastructure] }
"""


class SampleModelTest(unittest.TestCase):
    def test_every_sample_sa_is_clean(self):
        for sa in Workspace(TOOL_ROOT).sas():
            with self.subTest(sa=sa):
                self.assertEqual([str(i) for i in validate(load_model(sa, TOOL_ROOT))], [])


class ValidationErrorsTest(WorkspaceTestCase):
    def test_base_fixture_is_clean(self):
        self.write_sa("s", {"a.yaml": BASE})
        self.assertEqual(self.codes("s"), [])

    def test_invalid_relationship_lists_alternatives(self):
        self.write_sa("s", {"a.yaml": BASE.replace(
            "  - { type: Realization, source: infra-node, target: app-a }",
            "  - { type: Assignment, source: infra-node, target: app-a }",
        )})
        issues = [i for i in validate(self.load("s")) if i.code == "invalid-relationship"]
        self.assertEqual(len(issues), 1)
        self.assertIn("Assignment Node→ApplicationComponent is not allowed", issues[0].message)
        self.assertIn("Realization", issues[0].message)

    def test_reversed_direction_hint(self):
        self.write_sa("s", {"a.yaml": BASE.replace(
            "  - { type: Realization, source: app-a, target: app-svc }",
            "  - { type: Realization, source: app-svc, target: app-a }",
        )})
        issue = next(i for i in validate(self.load("s")) if i.code == "invalid-relationship")
        self.assertIn("(reversed) is allowed", issue.message)

    def test_unknown_type_suggests(self):
        self.write_sa("s", {"a.yaml": BASE.replace("type: Node", "type: Nodes").replace("type: Realization, source: app-a", "type: Realisation, source: app-a")})
        issues = {i.code: i for i in validate(self.load("s")) if i.severity == "error" and i.code != "layer-folder"}
        self.assertEqual(set(issues), {"unknown-type", "unknown-relationship"})
        self.assertIn("did you mean Node", issues["unknown-type"].message)
        self.assertIn("did you mean Realization", issues["unknown-relationship"].message)

    def test_dangling_reference(self):
        self.write_sa("s", {"a.yaml": BASE.replace("target: app-svc }", "target: app-svcc }")})
        issue = next(i for i in validate(self.load("s")) if i.code == "dangling-ref")
        self.assertIn("did you mean app-svc", issue.message)

    def test_duplicate_id_across_files(self):
        self.write_sa("s", {"a.yaml": BASE, "b.yaml": "elements:\n  - { id: app-a, type: ApplicationComponent, name: Again }\n"})
        self.assertIn("duplicate-id", self.codes("s", "error"))

    def test_attribute_on_wrong_relationship(self):
        self.write_sa("s", {"a.yaml": BASE.replace(
            "  - { type: Realization, source: app-a, target: app-svc }",
            "  - { type: Realization, source: app-a, target: app-svc, access: read }",
        )})
        self.assertIn("bad-attribute", self.codes("s", "error"))

    def test_id_prefix_warning(self):
        self.write_sa("s", {"a.yaml": BASE.replace("id: infra-node", "id: node").replace("source: infra-node", "source: node")})
        self.assertIn("id-prefix", self.codes("s", "warning"))

    def test_orphans_and_unviewed(self):
        self.write_sa("s", {"a.yaml": BASE, "b.yaml": "elements:\n  - { id: bus-lonely, type: BusinessActor, name: Lonely }\n"})
        warnings = self.codes("s", "warning")
        self.assertIn("orphan", warnings)
        self.assertIn("not-in-view", warnings)

    def test_view_with_unknown_include(self):
        self.write_sa("s", {"a.yaml": BASE.replace("include_layers: [application, infrastructure]", "include: [app-a, app-zzz]")})
        self.assertIn("view-ref", self.codes("s", "error"))

    def test_yaml_syntax_error_is_reported_not_raised(self):
        self.write_sa("s", {"a.yaml": BASE, "broken.yaml": "elements: [ { id: x\n"})
        self.assertIn("yaml-syntax", self.codes("s", "error"))

    def test_schema_rejects_unknown_keys(self):
        self.write_sa("s", {"a.yaml": BASE.replace("name: A }", "name: A, colour: red }")})
        self.assertIn("schema", self.codes("s", "error"))


class C4ValidationTest(WorkspaceTestCase):
    C4 = """
elements:
  - { id: bus-user, type: BusinessActor, name: User, c4: person }
  - { id: app-sys, type: ApplicationComponent, name: System, c4: system }
  - { id: app-web, type: ApplicationComponent, name: Web, c4: container }
relationships:
  - { type: Composition, source: app-sys, target: app-web }
  - { type: Serving, source: app-web, target: bus-user }
views:
  - { id: c4-ctx, kind: c4-context, name: Context }
  - { id: c4-cont, kind: c4-container, name: Containers, scope: app-sys }
"""

    def test_clean(self):
        self.write_sa("s", {"a.yaml": self.C4})
        self.assertEqual(self.codes("s"), [])

    def test_container_without_parent(self):
        self.write_sa("s", {"a.yaml": self.C4.replace("  - { type: Composition, source: app-sys, target: app-web }\n", "")})
        issue = next(i for i in validate(self.load("s")) if i.code == "c4-parent")
        self.assertIn("type: Composition, source: <system-id>, target: app-web", issue.message)

    def test_wrong_type_for_tag(self):
        self.write_sa("s", {"a.yaml": self.C4.replace("{ id: bus-user, type: BusinessActor", "{ id: bus-user, type: BusinessObject")})
        self.assertIn("c4-type", self.codes("s", "error"))

    def test_scope_required_and_typed(self):
        self.write_sa("s", {"a.yaml": self.C4.replace("scope: app-sys", "scope: app-web")})
        self.assertIn("view-scope", self.codes("s", "error"))
        self.write_sa("s", {"a.yaml": self.C4.replace(", scope: app-sys", "")})
        self.assertIn("view-scope", self.codes("s", "error"))


PLATFORM_META = "name: Platform\nkind: platform\nstatus: implemented\nexports: [app-svc-bus]\n"
PLATFORM = """
elements:
  - { id: app-bus, type: ApplicationComponent, name: Event bus, c4: system }
  - { id: app-svc-bus, type: ApplicationService, name: Event streaming }
  - { id: infra-broker, type: Node, name: Broker }
relationships:
  - { type: Realization, source: app-bus, target: app-svc-bus }
  - { type: Realization, source: infra-broker, target: app-bus }
views:
  - { id: view-all, name: All, include_layers: [application, infrastructure] }
"""
SOLUTION = """
elements:
  - { id: app-orders, type: ApplicationComponent, name: Orders, c4: system }
relationships:
  - { type: Serving, source: plat/app-svc-bus, target: app-orders, name: publishes order events }
views:
  - { id: view-all, name: All, include_layers: [application] }
  - { id: c4-ctx, kind: c4-context, name: Context }
"""


class CrossSaTest(WorkspaceTestCase):
    """Two SAs: a platform exporting a service, a solution using it."""

    def setUp(self):
        super().setUp()
        self.platform(PLATFORM)
        self.solution(SOLUTION)

    def platform(self, text, meta=PLATFORM_META):
        self.write_sa("plat", {"a.yaml": text})
        (self.root / "models/plat/model.yaml").write_text(meta, encoding="utf-8")

    def solution(self, text, meta="name: Orders\n"):
        self.write_sa("sol", {"a.yaml": text})
        (self.root / "models/sol/model.yaml").write_text(meta, encoding="utf-8")

    def test_clean_and_attached(self):
        self.assertEqual(self.codes("sol"), [])
        self.assertEqual(self.codes("plat"), [])
        model = self.load("sol")
        self.assertTrue(model.elements["plat/app-svc-bus"].foreign)
        self.assertTrue(model.elements["plat/app-bus"].foreign)  # stands behind the service (Realization)
        self.assertIn("plat/infra-broker", model.elements)  # behind the system (Realization): deployment views need it
        self.assertEqual(model.referenced, {"plat/app-svc-bus"})

    def test_layer_view_shows_only_direct_neighbours(self):
        model = self.load("sol")
        members = view_members(model, model.views["view-all"], load_rules())
        self.assertEqual(members, ["app-orders", "plat/app-svc-bus"])

    def test_c4_resolves_the_service_to_its_system(self):
        from a4m.c4 import C4Projector

        diagram = C4Projector(self.load("sol"), load_rules()).project(self.load("sol").views["c4-ctx"])
        self.assertEqual([(r.source, r.target, r.label) for r in diagram.rels], [("app-orders", "plat/app-bus", "Uses — publishes order events")])

    def test_provider_sees_its_consumers(self):
        model = self.load("plat")
        rel = model.relationships["sol/rel-plat/app-svc-bus-serving-app-orders"]
        self.assertEqual((rel.source, rel.target, rel.foreign), ("app-svc-bus", "sol/app-orders", True))

    def test_not_exported(self):
        self.solution(SOLUTION.replace("plat/app-svc-bus", "plat/infra-broker"))
        issue = next(i for i in validate(self.load("sol")) if i.code == "not-exported")
        self.assertIn("plat/app-svc-bus", issue.message)  # lists what it could use instead

    def test_unknown_sa_and_unknown_element(self):
        self.solution(SOLUTION.replace("plat/app-svc-bus", "plats/app-svc-bus"))
        self.assertIn("did you mean plat?", next(i for i in validate(self.load("sol")) if i.code == "unknown-sa").message)
        self.solution(SOLUTION.replace("plat/app-svc-bus", "plat/app-svc-buss"))
        self.assertIn("did you mean plat/app-svc-bus", next(i for i in validate(self.load("sol")) if i.code == "dangling-ref").message)

    def test_archimate_rules_apply_across_sas(self):
        self.solution(SOLUTION.replace("type: Serving, source: plat/app-svc-bus", "type: Assignment, source: plat/app-svc-bus"))
        self.assertIn("invalid-relationship", self.codes("sol", "error"))

    def test_bad_export(self):
        self.platform(PLATFORM, PLATFORM_META.replace("[app-svc-bus]", "[app-svc-bus, app-nope]"))
        self.assertIn("bad-export", self.codes("plat", "error"))

    def test_own_prefix_is_just_a_local_id(self):
        self.solution(SOLUTION.replace("target: app-orders", "target: sol/app-orders"))
        self.assertEqual(self.codes("sol"), [])

    def test_relationship_between_two_other_sas(self):
        self.solution(SOLUTION.replace("target: app-orders, name", "target: plat/app-svc-bus, name"))
        self.assertIn("foreign-relationship", self.codes("sol", "warning"))

    def test_duplicate_across_sas(self):
        self.solution(SOLUTION.replace("name: Orders, c4: system }", "name: Orders, c4: system }\n  - { id: app-bus2, type: ApplicationComponent, name: event  bus }"))
        issue = next(i for i in validate(self.load("sol")) if i.code == "duplicate-across-sas")
        self.assertIn("plat/app-bus", issue.message)

    def test_state_mismatch_within_an_sa(self):
        self.platform(PLATFORM.replace("name: Broker }", "name: Broker, state: new }"))
        issue = next(i for i in validate(self.load("plat")) if i.code == "state-mismatch")
        self.assertIn("mark the relationship `state: new`", issue.message)

    def test_retiring_a_used_element_warns_both_sides(self):
        self.platform(PLATFORM.replace("name: Event streaming }", "name: Event streaming, state: retiring }")
                      .replace("target: app-svc-bus }", "target: app-svc-bus, state: retiring }"))
        provider = [i for i in validate(self.load("plat")) if i.code == "consumer-impact"]
        consumer = [i for i in validate(self.load("sol")) if i.code == "consumer-impact"]
        self.assertEqual(len(provider), 1)
        self.assertIn("sol still depends on it", provider[0].message)
        self.assertEqual(len(consumer), 1)
        self.assertIn("plan the change with plat", consumer[0].message)
        self.assertEqual(self.codes("sol", "error"), [])  # a warning: another team's change must not block this SA

    def test_sa_metadata(self):
        self.solution(SOLUTION, "name: Orders\nkind: app\nstatus: proposed\n")
        codes = self.codes("sol")
        self.assertIn("sa-meta", codes)  # unknown kind
        self.assertIn("sa-status", codes)  # proposed, but nothing changes

    def test_impact(self):
        usages = Workspace(self.root).consumers_of("plat/app-svc-bus")
        self.assertEqual([(u.consumer, u.rel.type) for u in usages], [("sol", "Serving")])
        self.assertEqual(Workspace(self.root).dependencies()["sol"].keys(), {"plat"})


class LayerFolderTest(WorkspaceTestCase):
    """Elements live in models/<sa>/<layer>/: business, information, application, infrastructure."""

    def issues(self, files):
        self.write_sa("s", files)
        return [i for i in validate(self.load("s")) if i.code == "layer-folder"]

    def test_right_folders(self):
        self.assertEqual(self.issues({
            "business/a.yaml": "elements:\n  - { id: bus-goal, type: Goal, name: G }\n",
            "information/a.yaml": "elements:\n  - { id: data-x, type: DataObject, name: X }\n",
            "application/a.yaml": "elements:\n  - { id: app-x, type: ApplicationComponent, name: X }\n",
            "infrastructure/a.yaml": "elements:\n  - { id: infra-x, type: Equipment, name: X }\n  - { id: j, type: Junction, name: J }\n",
        }), [])

    def test_wrong_folder_names_the_right_one(self):
        [issue] = self.issues({"application/a.yaml": "elements:\n  - { id: data-x, type: DataObject, name: X }\n"})
        self.assertEqual(issue.severity, "error")
        self.assertIn("move it to models/s/information/", issue.message)
        self.assertIn("(it is in application/)", issue.message)

    def test_sa_root_and_old_folders(self):
        issues = self.issues({
            "a.yaml": "elements:\n  - { id: bus-a, type: BusinessActor, name: A }\n",
            "technology/a.yaml": "elements:\n  - { id: infra-n, type: Node, name: N }\n",
            "views/j.yaml": "elements:\n  - { id: j, type: Junction, name: J }\n",
        })
        messages = {i.ref: i.message for i in issues}
        self.assertIn("(it is in the SA root)", messages["bus-a"])
        self.assertIn("models/s/infrastructure/", messages["infra-n"])
        self.assertIn("business/ or information/ or application/ or infrastructure/", messages["j"])

if __name__ == "__main__":
    unittest.main()
