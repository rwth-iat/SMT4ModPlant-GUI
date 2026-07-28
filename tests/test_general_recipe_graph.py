import copy
import importlib.util
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from Code.SMT4ModPlant.GeneralRecipeGraph import (
    order_process_elements_by_directed_links,
)
from Code.Transformator.MasterRecipeGenerator import (
    generate_b2mml_master_recipe,
)


B2MML_NS = "http://www.mesa.org/xml/B2MML"
NS = {"b2mml": B2MML_NS}


def _load_legacy_graph_module():
    module_path = (
        Path(__file__).resolve().parents[1]
        / "Others"
        / "general_recipe_graph.py"
    )
    spec = importlib.util.spec_from_file_location(
        "legacy_general_recipe_graph",
        module_path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parameter(step_id):
    return {
        "ID": f"{step_id}-Parameter",
        "Description": f"{step_id} parameter",
        "ValueString": "1",
        "DataType": "int",
        "UnitOfMeasure": "s",
        "Key": f"key-{step_id}",
    }


def _linear_recipe():
    return {
        "ID": "Recipe",
        "Description": "DirectedLinks recipe",
        "Inputs": [{"ID": "Input-1"}, {"ID": "Input-2"}],
        "Outputs": [{"ID": "Product"}],
        "Intermediates": [{"ID": "Mixed"}, {"ID": "Dosed"}],
        "ProcessElements": [
            {
                "ID": "Heating",
                "Description": "Heating",
                "Parameters": [_parameter("Heating")],
            },
            {
                "ID": "Mixing",
                "Description": "Mixing",
                "Parameters": [_parameter("Mixing")],
            },
            {
                "ID": "Dosing",
                "Description": "Dosing",
                "Parameters": [_parameter("Dosing")],
            },
        ],
        "DirectedLinks": [
            {"ID": "L6", "FromID": "Dosed", "ToID": "Heating"},
            {"ID": "L2", "FromID": "Input-2", "ToID": "Mixing"},
            {"ID": "L7", "FromID": "Heating", "ToID": "Product"},
            {"ID": "L4", "FromID": "Mixed", "ToID": "Dosing"},
            {"ID": "L1", "FromID": "Input-1", "ToID": "Mixing"},
            {"ID": "L5", "FromID": "Dosing", "ToID": "Dosed"},
            {"ID": "L3", "FromID": "Mixing", "ToID": "Mixed"},
        ],
    }


def _assignment(step_id, number):
    return {
        "step_id": step_id,
        "resource": f"resource: HC{number}0",
        "capabilities": [step_id],
        "selected_capability": {
            "name": step_id,
            "id": f"capability-{step_id}",
            "realized_by": [f"realized-{step_id}"],
        },
        "capability_details": [{
            "matched_properties": [{
                "property_id": f"key-{step_id}",
                "property_name": f"{step_id} property",
                "property_unit": "s",
                "property_realized_by": f"parameter-{step_id}",
            }],
        }],
    }


class GeneralRecipeGraphTests(unittest.TestCase):
    def test_orders_process_elements_through_material_nodes(self):
        recipe = _linear_recipe()
        source_objects = {
            element["ID"]: element
            for element in recipe["ProcessElements"]
        }

        ordered = order_process_elements_by_directed_links(recipe)

        self.assertEqual(
            [element["ID"] for element in ordered],
            ["Mixing", "Dosing", "Heating"],
        )
        self.assertIs(ordered[0], source_objects["Mixing"])
        self.assertIs(ordered[1], source_objects["Dosing"])
        self.assertIs(ordered[2], source_objects["Heating"])

    def test_allows_recipe_without_process_elements(self):
        recipe = {
            "Inputs": [],
            "Outputs": [],
            "Intermediates": [],
            "ProcessElements": [],
            "DirectedLinks": [],
        }
        self.assertEqual(
            order_process_elements_by_directed_links(recipe),
            [],
        )

    def test_legacy_graph_helper_uses_the_same_order(self):
        legacy_module = _load_legacy_graph_module()
        ordered = legacy_module.order_process_elements_by_directed_links(
            _linear_recipe()
        )
        self.assertEqual(
            [element["ID"] for element in ordered],
            ["Mixing", "Dosing", "Heating"],
        )

    def test_rejects_invalid_graphs(self):
        cases = []

        missing_links = _linear_recipe()
        missing_links["DirectedLinks"] = []
        cases.append((missing_links, "no links"))

        unknown_endpoint = _linear_recipe()
        unknown_endpoint["DirectedLinks"][0]["ToID"] = "Unknown"
        cases.append((unknown_endpoint, "unknown ToID"))

        duplicate_node = _linear_recipe()
        duplicate_node["Outputs"][0]["ID"] = "Input-1"
        cases.append((duplicate_node, "duplicate node ID"))

        duplicate_link = _linear_recipe()
        duplicate_link["DirectedLinks"][1]["ID"] = "L6"
        cases.append((duplicate_link, "duplicate link ID"))

        cycle = _linear_recipe()
        cycle["Intermediates"].append({"ID": "Cycle"})
        cycle["DirectedLinks"].extend([
            {"ID": "L8", "FromID": "Heating", "ToID": "Cycle"},
            {"ID": "L9", "FromID": "Cycle", "ToID": "Dosing"},
        ])
        cases.append((cycle, "cycle"))

        branch = _linear_recipe()
        branch["Intermediates"].append({"ID": "CoolingInput"})
        branch["Outputs"].append({"ID": "CooledProduct"})
        branch["ProcessElements"].append({
            "ID": "Cooling",
            "Description": "Cooling",
            "Parameters": [],
        })
        branch["DirectedLinks"].extend([
            {"ID": "L8", "FromID": "Mixing", "ToID": "CoolingInput"},
            {"ID": "L9", "FromID": "CoolingInput", "ToID": "Cooling"},
            {"ID": "L10", "FromID": "Cooling", "ToID": "CooledProduct"},
        ])
        cases.append((branch, "branches"))

        join = _linear_recipe()
        join["Inputs"].append({"ID": "CoolingInput"})
        join["Intermediates"].append({"ID": "Cooled"})
        join["ProcessElements"].append({
            "ID": "Cooling",
            "Description": "Cooling",
            "Parameters": [],
        })
        join["DirectedLinks"].extend([
            {"ID": "L8", "FromID": "CoolingInput", "ToID": "Cooling"},
            {"ID": "L9", "FromID": "Cooling", "ToID": "Cooled"},
            {"ID": "L10", "FromID": "Cooled", "ToID": "Heating"},
        ])
        cases.append((join, "joins"))

        unanchored = _linear_recipe()
        unanchored["DirectedLinks"] = [
            link
            for link in unanchored["DirectedLinks"]
            if link["FromID"] not in {"Input-1", "Input-2"}
        ]
        cases.append((unanchored, "not reachable from a recipe input"))

        no_output_path = _linear_recipe()
        no_output_path["DirectedLinks"] = [
            link
            for link in no_output_path["DirectedLinks"]
            if link["ToID"] != "Product"
        ]
        cases.append((no_output_path, "cannot reach a recipe output"))

        independent_chains = _linear_recipe()
        independent_chains["Inputs"].append({"ID": "SecondInput"})
        independent_chains["Outputs"].append({"ID": "SecondOutput"})
        independent_chains["ProcessElements"].append({
            "ID": "Cooling",
            "Description": "Cooling",
            "Parameters": [],
        })
        independent_chains["DirectedLinks"].extend([
            {"ID": "L8", "FromID": "SecondInput", "ToID": "Cooling"},
            {"ID": "L9", "FromID": "Cooling", "ToID": "SecondOutput"},
        ])
        cases.append((independent_chains, "one linear chain"))

        for recipe, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    order_process_elements_by_directed_links(recipe)

    def test_generator_numbers_and_links_phases_in_graph_order(self):
        recipe = _linear_recipe()
        solution = {
            "solution_id": 1,
            "assignments": [
                _assignment("Heating", 3),
                _assignment("Dosing", 2),
                _assignment("Mixing", 1),
            ],
        }

        xml = generate_b2mml_master_recipe(
            resources_data={},
            solutions_data_list={"plant_configurations": [solution]},
            general_recipe_data=copy.deepcopy(recipe),
            selected_solution_id=1,
            output_path=None,
            log_callback=lambda _message: None,
        )
        root = ET.fromstring(xml)

        step_recipe_element_ids = [
            element.text
            for element in root.findall(
                ".//b2mml:ProcedureLogic/b2mml:Step/"
                "b2mml:RecipeElementID",
                NS,
            )
        ]
        self.assertEqual(
            step_recipe_element_ids,
            [
                "Init",
                "001:realized-Mixing",
                "002:realized-Dosing",
                "003:realized-Heating",
                "End",
            ],
        )

        parameter_ids = [
            element.text
            for element in root.findall(
                ".//b2mml:Formula/b2mml:Parameter/b2mml:ID",
                NS,
            )
        ]
        self.assertEqual(
            parameter_ids,
            [
                "001:parameter-Mixing",
                "002:parameter-Dosing",
                "003:parameter-Heating",
            ],
        )

        conditions = [
            element.text
            for element in root.findall(
                ".//b2mml:ProcedureLogic/b2mml:Transition/"
                "b2mml:Condition",
                NS,
            )
        ]
        self.assertEqual(
            conditions,
            [
                "True",
                "Step 001:HC10_Mixing:Mixing is Completed",
                "Step 002:HC20_Dosing:Dosing is Completed",
                "Step 003:HC30_Heating:Heating is Completed",
            ],
        )

        phase_ids = [
            element.findtext("b2mml:ID", namespaces=NS)
            for element in root.findall(
                ".//b2mml:MasterRecipe/b2mml:RecipeElement",
                NS,
            )
            if element.findtext(
                "b2mml:RecipeElementType",
                namespaces=NS,
            ) == "Phase"
        ]
        self.assertEqual(
            phase_ids,
            [
                "001:realized-Mixing",
                "002:realized-Dosing",
                "003:realized-Heating",
            ],
        )


if __name__ == "__main__":
    unittest.main()
