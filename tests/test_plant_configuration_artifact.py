import json
import unittest

from Code.SMT4ModPlant.PlantConfigurationArtifact import (
    build_plant_configurations_artifact,
    validate_plant_configurations,
)
from Code.Transformator.MasterRecipeGenerator import (
    generate_b2mml_master_recipe,
)


def _assignment(realized_by=None, property_realized_by="property-ref", value="15"):
    return {
        "step_id": "Step-1",
        "step_description": "Mix",
        "required_capability_semantic_id": "urn:test#Mixing",
        "resource": "resource: HC10",
        "capabilities": ["Mixing"],
        "selected_capability": {
            "index": 0,
            "name": "Mixing",
            "id": "urn:test#Mixing",
            "realized_by": realized_by
            if realized_by is not None
            else ["capability-ref"],
        },
        "parameter_matches": [{
            "description": "Duration",
            "key": "urn:test#Duration",
            "unit": "s",
            "value": value,
            "values": [value],
        }],
        "capability_details": [{
            "capability_name": "Mixing",
            "capability_id": "urn:test#Mixing",
            "capability_index": 0,
            "capability_generalized_by_id": [
                "urn:test#GeneralizedMixing",
            ],
            "matched_properties": [{
                "required_parameter_id": "Duration-1",
                "required_parameter_semantic_id": "urn:test#Duration",
                "property_id": "urn:test#Duration",
                "property_name": "Duration",
                "property_unit": "s",
                "property_realized_by": property_realized_by,
                "value_type": "range",
                "value_min": "0",
                "value_max": "60",
            }],
        }],
    }


def _solution(assignment=None):
    return {
        "solution_id": 1,
        "assignments": [assignment or _assignment()],
        "material_flow_consistent": True,
    }


class PlantConfigurationArtifactTests(unittest.TestCase):
    def test_builds_named_artifact_without_hashes_or_absolute_paths(self):
        solutions = [_solution()]
        context_data = {
            "recipe": {
                "ID": "Recipe-1",
                "DirectedLinks": [{
                    "ID": "Link-1",
                    "FromID": "Input-1",
                    "ToID": "Step-1",
                }],
            },
            "recipe_path": "C:/private/input/GeneralRecipe.xml",
            "resources": {"resource: HC10": []},
            "resource_sources": {
                "resource: HC10": "C:/private/input/HC10_AAS.xml",
            },
            "solutions": solutions,
        }

        artifact = build_plant_configurations_artifact(context_data)

        self.assertEqual(artifact["artifact_type"], "PlantConfigurations")
        self.assertNotIn("schema_version", artifact)
        self.assertNotIn("generated_at", artifact)
        self.assertEqual(
            artifact["source"]["general_recipe"],
            {"id": "Recipe-1", "file": "GeneralRecipe.xml"},
        )
        self.assertEqual(
            artifact["source"]["resources"],
            [{"resource": "HC10", "file": "HC10_AAS.xml"}],
        )
        self.assertEqual(
            artifact["process_context"]["directed_links"],
            context_data["recipe"]["DirectedLinks"],
        )
        self.assertEqual(artifact["plant_configurations"], solutions)

        serialized = json.dumps(artifact)
        self.assertNotIn("sha256", serialized.lower())
        self.assertNotIn("C:/private", serialized)

    def test_constraint_without_property_reference_is_only_a_warning(self):
        assignment = _assignment(
            property_realized_by="",
            value=">=10",
        )
        assignment["parameter_matches"][0]["values"] = [">=10", "<=20"]

        errors, warnings = validate_plant_configurations([
            _solution(assignment)
        ])

        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 1)
        self.assertIn("PropertyRealizedBy is missing", warnings[0])

    def test_missing_execution_references_are_blocking(self):
        assignment = _assignment(
            realized_by=[],
            property_realized_by="",
            value="15",
        )

        errors, warnings = validate_plant_configurations([
            _solution(assignment)
        ])

        self.assertEqual(warnings, [])
        self.assertTrue(any("CapabilityRealizedBy" in error for error in errors))
        self.assertTrue(any("PropertyRealizedBy" in error for error in errors))

    def test_master_recipe_accepts_new_and_legacy_solution_containers(self):
        recipe = {
            "ID": "Recipe-1",
            "Description": "Empty recipe",
            "Inputs": [],
            "Outputs": [],
            "Intermediates": [],
            "ProcessElements": [],
            "DirectedLinks": [],
        }
        solutions = [{"solution_id": 1, "assignments": []}]

        formats = (
            solutions,
            {"solutions": solutions},
            {"plant_configurations": solutions},
        )
        for solutions_data in formats:
            xml = generate_b2mml_master_recipe(
                resources_data={},
                solutions_data_list=solutions_data,
                general_recipe_data=recipe,
                selected_solution_id=1,
                output_path=None,
            )
            self.assertIn("MasterRecipe_1", xml)

    def test_master_recipe_rejects_missing_capability_realization(self):
        recipe = {
            "ID": "Recipe-1",
            "Description": "Recipe",
            "Inputs": [],
            "Outputs": [],
            "Intermediates": [],
            "ProcessElements": [{
                "ID": "Step-1",
                "Description": "Mix",
                "Parameters": [],
                "SemanticDescription": "urn:test#Mixing",
            }],
            "DirectedLinks": [],
        }
        solution = _solution(_assignment(realized_by=[]))

        with self.assertRaisesRegex(ValueError, "CapabilityRealizedBy"):
            generate_b2mml_master_recipe(
                resources_data={},
                solutions_data_list={
                    "plant_configurations": [solution],
                },
                general_recipe_data=recipe,
                selected_solution_id=1,
                output_path=None,
            )


if __name__ == "__main__":
    unittest.main()
