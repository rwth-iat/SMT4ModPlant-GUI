import unittest

from Code.GUI.Logs import FlowNodeCard, MasterRecipeFlowView
from Code.GUI.Workers import SMTWorker


class MasterRecipePhasePreviewTests(unittest.TestCase):
    def test_flow_preview_uses_phase_nodes_and_labels(self):
        recipe = {
            "ProcessElements": [{
                "ID": "Step-1",
                "Description": "Mix",
            }],
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


if __name__ == "__main__":
    unittest.main()
