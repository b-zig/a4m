import unittest

from a4m.rules import RELATIONSHIP_TYPES, load_rules


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.rules = load_rules()

    def test_every_matrix_concept_is_catalogued(self):
        concepts = {s for s, _ in self.rules.matrix} | {t for _, t in self.rules.matrix}
        self.assertEqual(concepts - {"Relationship"}, set(self.rules.types))

    def test_known_allowed(self):
        for source, rel, target in [
            ("Node", "Assignment", "SystemSoftware"),
            ("ApplicationComponent", "Realization", "ApplicationService"),
            ("ApplicationService", "Serving", "BusinessProcess"),
            ("BusinessActor", "Assignment", "BusinessRole"),
            ("Artifact", "Realization", "ApplicationComponent"),
            ("Driver", "Influence", "Goal"),
            ("WorkPackage", "Realization", "Deliverable"),
        ]:
            with self.subTest(source=source, rel=rel, target=target):
                self.assertTrue(self.rules.is_allowed(source, rel, target))

    def test_known_disallowed(self):
        for source, rel, target in [
            ("Node", "Assignment", "ApplicationComponent"),
            ("DataObject", "Serving", "BusinessActor"),
            ("Goal", "Assignment", "Node"),
            ("Resource", "Realization", "Capability"),
        ]:
            with self.subTest(source=source, rel=rel, target=target):
                self.assertFalse(self.rules.is_allowed(source, rel, target))

    def test_allowed_is_in_spec_order(self):
        allowed = self.rules.allowed("ApplicationComponent", "ApplicationService")
        self.assertEqual(allowed, sorted(allowed, key=RELATIONSHIP_TYPES.index))

    def test_association_always_allowed_between_elements(self):
        for source in ("Node", "Goal", "BusinessActor", "WorkPackage"):
            for target in ("Location", "Grouping", "DataObject"):
                self.assertIn("Association", self.rules.allowed(source, target))

    def test_type_suggestions(self):
        self.assertEqual(self.rules.suggest_type("applicationcomponent"), ["ApplicationComponent"])
        self.assertIn("Node", self.rules.suggest_type("Nod"))
        self.assertEqual(self.rules.suggest_relationship("serving"), ["Serving"])

    def test_every_type_has_a_known_layer_and_aspect(self):
        for t in self.rules.types.values():
            self.assertIn(t.layer, self.rules.layers)
            self.assertIn(t.aspect, ["active", "behavior", "passive", "motivation", "composite", "other"])


if __name__ == "__main__":
    unittest.main()
