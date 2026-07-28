import unittest

from Code.GUI.Logs import FlowNodeCard, MasterRecipeFlowView
from Code.GUI.Workers import SMTWorker


class MasterRecipePhasePreviewTests(unittest.TestCase):
    def test_flow_preview_uses_phase_nodes_and_labels(self):
        recipe = {
            "Inputs": [{"ID": "Input"}],
            "Outputs": [{"ID": "Output"}],
            "Intermediates": [],
            "ProcessElements": [{
                "ID": "Step-1",
                "Description": "Mix",
            }],
            "DirectedLinks": [
                {"FromID": "Input", "ToID": "Step-1"},
                {"FromID": "Step-1", "ToID": "Output"},
            ],
        }
        solutions = [{
            "solution_id": 1,
            "assignments": [{
                "step_id": "Step-1",
                "resource": "resource: HC10",
                "selected_capability": {"name": "Mixing"},
            }],
        }]

        nodes = SMTWorker._build_master_recipe_flow(recipe, solutions, 1)

        self.assertEqual([node["kind"] for node in nodes], ["start", "phase", "end"])
        self.assertEqual(FlowNodeCard._kind_label("phase"), "Phase")

        phase_count, summary, phase_chip_text = (
            MasterRecipeFlowView._phase_overview_content(nodes)
        )
        self.assertEqual(phase_count, 1)
        self.assertEqual(summary, '1 phase step between "Init" and "End".')
        self.assertEqual(phase_chip_text, "1 Phase")

        two_phase_nodes = nodes[:-1] + [dict(nodes[1])] + nodes[-1:]
        phase_count, summary, phase_chip_text = (
            MasterRecipeFlowView._phase_overview_content(two_phase_nodes)
        )
        self.assertEqual(phase_count, 2)
        self.assertEqual(summary, '2 phase steps between "Init" and "End".')
        self.assertEqual(phase_chip_text, "2 Phases")

    def test_flow_preview_uses_directed_links_order(self):
        recipe = {
            "Inputs": [{"ID": "Input"}],
            "Outputs": [{"ID": "Output"}],
            "Intermediates": [{"ID": "Mixed"}, {"ID": "Dosed"}],
            "ProcessElements": [
                {"ID": "Heating", "Description": "Heating"},
                {"ID": "Mixing", "Description": "Mixing"},
                {"ID": "Dosing", "Description": "Dosing"},
            ],
            "DirectedLinks": [
                {"FromID": "Dosed", "ToID": "Heating"},
                {"FromID": "Heating", "ToID": "Output"},
                {"FromID": "Input", "ToID": "Mixing"},
                {"FromID": "Mixed", "ToID": "Dosing"},
                {"FromID": "Dosing", "ToID": "Dosed"},
                {"FromID": "Mixing", "ToID": "Mixed"},
            ],
        }
        solutions = [{
            "solution_id": 1,
            "assignments": [
                {
                    "step_id": step_id,
                    "resource": f"resource: {step_id}",
                    "selected_capability": {"name": step_id},
                }
                for step_id in ("Heating", "Dosing", "Mixing")
            ],
        }]

        nodes = SMTWorker._build_master_recipe_flow(recipe, solutions, 1)

        self.assertEqual(
            [node["title"] for node in nodes],
            [
                "Init",
                "01. Mixing",
                "02. Dosing",
                "03. Heating",
                "End",
            ],
        )
        self.assertEqual(
            nodes[-1]["transition"],
            "Step Heating is Completed",
        )


if __name__ == "__main__":
    unittest.main()
