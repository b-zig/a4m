import unittest

from a4m.c4 import C4Projector
from a4m.export_c4 import render_c4
from a4m.landscape import landscape_model
from a4m.paths import TOOL_ROOT
from a4m.rules import load_rules
from a4m.state import at_state, display_state
from a4m.workspace import Workspace
from tests.helpers import WorkspaceTestCase, load_sample


def rels(diagram):
    return {(r.source, r.target): r.label for r in diagram.rels}


class SampleC4Test(unittest.TestCase):
    """The nextcloud SA: its own systems plus what it uses from (and is used by) other SAs."""

    @classmethod
    def setUpClass(cls):
        cls.model = load_sample("nextcloud")
        cls.projector = C4Projector(cls.model, load_rules())

    def project(self, view_id):
        return self.projector.project(self.model.views[view_id])

    def test_context_collapses_service_role_chain_across_sas(self):
        # enterprise: Family -Assignment-> Service user -Assignment-> Share process
        # nextcloud: Share process <-Serving- File sync <-Realization- web container
        self.assertEqual(rels(self.project("c4-context"))[("enterprise/bus-family", "app-nextcloud")], "Uses")

    def test_context_flips_serving_and_keeps_name(self):
        self.assertEqual(rels(self.project("c4-context"))[("app-nextcloud", "dns/app-pihole")], "Uses — DNS lookups")

    def test_context_shows_consumers_from_other_sas(self):
        self.assertEqual(rels(self.project("c4-context"))[("app-nextcloud", "backup/app-backup")], "Nightly dump")

    def test_context_boundary_holds_only_own_systems(self):
        diagram = self.project("c4-context")
        macro, _, members = diagram.boundary
        self.assertEqual(macro, "Boundary")
        self.assertEqual(members, ["app-nextcloud"])

    def test_container_view(self):
        diagram = self.project("c4-containers")
        macro, scope, members = diagram.boundary
        self.assertEqual((macro, scope), ("System_Boundary", "app-nextcloud"))
        self.assertEqual(set(members), {"app-nextcloud-web", "app-nextcloud-db", "app-nextcloud-cache"})
        r = rels(diagram)
        self.assertIn(("enterprise/bus-family", "app-nextcloud-web"), r)
        self.assertIn(("app-nextcloud-db", "backup/app-backup"), r)  # other systems stay at system level

    def test_deployment_on_another_sas_platform(self):
        diagram = self.project("c4-deployment")
        self.assertEqual(diagram.roots, ["network/infra-loc-home"])
        self.assertIn("compute/infra-vm-docker", diagram.children["compute/infra-pve-01"])
        self.assertEqual(diagram.children["compute/infra-vm-docker"], ["compute/infra-docker"])
        # compute/infra-docker -Assignment-> Artifact (nextcloud) -Realization-> container
        self.assertEqual(set(diagram.hosted["compute/infra-docker"]), {"app-nextcloud-web", "app-nextcloud-db", "app-nextcloud-cache"})

    def test_render_uses_db_shape_and_draws_other_sas_as_external(self):
        self.assertIn("ContainerDb(app_nextcloud_db", render_c4(self.model, self.model.views["c4-containers"]))
        text = render_c4(self.model, self.model.views["c4-context"])
        self.assertIn('System_Ext(dns__app_pihole, "Pi-hole", "[dns] ', text)
        self.assertIn('Boundary(boundary_nextcloud, "Nextcloud") {', text)


class LandscapeC4Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = landscape_model(Workspace(TOOL_ROOT))
        cls.projector = C4Projector(cls.model, load_rules())

    def test_systems_grouped_by_sa_inside_the_enterprise(self):
        diagram = self.projector.project(self.model.views["landscape-context"])
        self.assertEqual(diagram.boundary[0], "Enterprise_Boundary")
        groups = {sa: ids for sa, _, ids in diagram.groups}
        self.assertEqual(groups["nextcloud"], ["nextcloud/app-nextcloud"])
        self.assertNotIn("backup/app-offsite-b2", diagram.boundary[2])  # external

    def test_deployment_across_sas(self):
        diagram = self.projector.project(self.model.views["landscape-deployment"])
        self.assertEqual(diagram.hosted["home-automation/infra-vm-haos"], ["home-automation/app-home-assistant"])
        self.assertIn("media/app-jellyfin", diagram.hosted["compute/infra-docker"])

    def test_target_needs_approval(self):
        target = set(at_state(self.model, "target").elements)
        baseline = set(at_state(self.model, "baseline").elements)
        # backup is approved: B2 retires, Hetzner arrives
        self.assertIn("backup/app-offsite-b2", baseline)
        self.assertNotIn("backup/app-offsite-b2", target)
        self.assertIn("backup/app-offsite-hetzner", target)
        # media is only proposed: Jellyfin is in neither state, and shows as "proposed"
        self.assertNotIn("media/app-jellyfin", baseline | target)
        self.assertEqual(display_state(self.model, self.model.elements["media/app-jellyfin"]), "proposed")
        text = render_c4(self.model, self.model.views["landscape-context"], styled=True)
        self.assertIn('Jellyfin [PROPOSED]', text)
        self.assertIn('UpdateElementStyle(backup__app_offsite_b2, $borderColor="#c62828"', text)


class ComponentViewTest(WorkspaceTestCase):
    MODEL = """
elements:
  - { id: bus-user, type: BusinessActor, name: User, c4: person }
  - { id: app-shop, type: ApplicationComponent, name: Shop, c4: system }
  - { id: app-api, type: ApplicationComponent, name: API, c4: container }
  - { id: app-db, type: ApplicationComponent, name: DB, c4: container, c4_shape: database }
  - { id: app-orders, type: ApplicationComponent, name: Orders, c4: component }
  - { id: app-auth, type: ApplicationComponent, name: Auth, c4: component }
  - { id: app-pay, type: ApplicationComponent, name: Payments, c4: system, external: true }
  - { id: app-if-rest, type: ApplicationInterface, name: REST }
relationships:
  - { type: Composition, source: app-shop, target: app-api }
  - { type: Composition, source: app-shop, target: app-db }
  - { type: Composition, source: app-api, target: app-orders }
  - { type: Composition, source: app-api, target: app-auth }
  - { type: Composition, source: app-orders, target: app-if-rest }
  - { type: Serving, source: app-if-rest, target: bus-user }
  - { type: Flow, source: app-orders, target: app-db, name: SQL }
  - { type: Flow, source: app-orders, target: app-auth, name: Checks token }
  - { type: Flow, source: app-orders, target: app-pay, name: Charges card }
views:
  - { id: c4-api, kind: c4-component, name: API components, scope: app-api }
  - { id: c4-ctx, kind: c4-context, name: Context, scope: app-shop }
"""

    def setUp(self):
        super().setUp()
        self.write_sa("s", {"m.yaml": self.MODEL})
        self.model = self.load("s")
        self.projector = C4Projector(self.model, load_rules())

    def test_component_view(self):
        diagram = self.projector.project(self.model.views["c4-api"])
        self.assertEqual(diagram.boundary[0], "Container_Boundary")
        r = rels(diagram)
        self.assertEqual(r[("bus-user", "app-orders")], "Uses")  # via the untagged interface
        self.assertEqual(r[("app-orders", "app-db")], "SQL")  # sibling container stays a container
        self.assertEqual(r[("app-orders", "app-auth")], "Checks token")
        self.assertEqual(r[("app-orders", "app-pay")], "Charges card")

    def test_context_rolls_components_up_to_system(self):
        r = rels(self.projector.project(self.model.views["c4-ctx"]))
        self.assertEqual(set(r), {("bus-user", "app-shop"), ("app-shop", "app-pay")})

    def test_rendered_component_diagram(self):
        text = render_c4(self.model, self.model.views["c4-api"])
        self.assertTrue(text.startswith("C4Component\n"))
        self.assertIn("Container_Boundary(boundary_app_api", text)
        self.assertIn('Component(app_orders, "Orders"', text)


if __name__ == "__main__":
    unittest.main()
