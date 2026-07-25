# Code/GUI/Workers.py
import sys
import os
import copy
import traceback
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

try:
    from Code.SMT4ModPlant.GeneralRecipeParser import parse_general_recipe
    from Code.SMT4ModPlant.AASxmlCapabilityParser import parse_capabilities_robust
    from Code.SMT4ModPlant.SMT4ModPlant_main import run_optimization
    from Code.Optimizer.Optimization import SolutionOptimizer
    from Code.Transformator.MasterRecipeGenerator import generate_b2mml_master_recipe
except ImportError as e:
    print("Import Error inside Workers.py: Could not load backend modules.")
    print(f"Specific Error: {e}")

class SMTWorker(QThread):
    """Background thread that handles parsing inputs, running calculation, and optional weighted sorting."""
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)
    # [MODIFIED] Signal now carries (gui_data_list, context_dict)
    finished_signal = pyqtSignal(list, dict)
    error_signal = pyqtSignal(str)

    def __init__(self, recipe_path, resource_dir, mode_index, weights):
        super().__init__()
        self.recipe_path = recipe_path
        self.resource_dir = resource_dir
        self.mode_index = mode_index  # 0: all results, 1: weighted sorted all results
        self.weights = weights 

    @staticmethod
    def _select_preview_solution_id(json_solutions, mode_index, evaluated_solutions=None):
        """Pick the most relevant solution for Master Recipe preview."""
        if mode_index == 1 and evaluated_solutions:
            return evaluated_solutions[0].get("solution_id")
        if json_solutions:
            return json_solutions[0].get("solution_id")
        return None

    @staticmethod
    def _build_master_recipe_flow(recipe_data, json_solutions, selected_solution_id):
        """Create a compact flow representation for the log-page graphics tab."""
        if not selected_solution_id:
            return []

        solution_lookup = {}
        for solution in json_solutions or []:
            solution_lookup[solution.get("solution_id")] = solution

        solution = solution_lookup.get(selected_solution_id)
        if not solution:
            return []

        assignment_by_step = {}
        for assignment in solution.get("assignments", []):
            assignment_by_step[assignment.get("step_id")] = assignment

        flow_nodes = [
            {
                "kind": "start",
                "title": "Init",
                "subtitle": "Master Recipe start",
                "meta": "",
                "transition": "",
            }
        ]

        previous_step_label = "Init"
        for index, step in enumerate(recipe_data.get("ProcessElements", []), start=1):
            assignment = assignment_by_step.get(step.get("ID"), {})
            selected_capability = assignment.get("selected_capability") or {}
            capability_name = selected_capability.get("name")
            if not capability_name:
                capabilities = assignment.get("capabilities") or []
                capability_name = capabilities[0] if capabilities else "No capability"
            resource_name = assignment.get("resource", "No resource")
            step_label = step.get("Description", step.get("ID", "Step"))

            flow_nodes.append({
                "kind": "operation",
                "title": f"{index:02d}. {step_label}",
                "subtitle": resource_name,
                "meta": capability_name,
                "transition": "True" if index == 1 else f"Step {previous_step_label} is Completed",
            })
            previous_step_label = step_label

        flow_nodes.append({
            "kind": "end",
            "title": "End",
            "subtitle": f"Preview solution {selected_solution_id}",
            "meta": "",
            "transition": f"Step {previous_step_label} is Completed" if len(flow_nodes) > 1 else "True",
        })
        return flow_nodes

    def run(self):
        """Execute the end-to-end workflow: parse inputs, solve constraints, and optionally sort by weighted cost."""
        try:
            current_phase = "Recipe"
            # 1. Parsing
            self.log_signal.emit(f"Parsing Recipe: {self.recipe_path}")
            recipe_data = parse_general_recipe(self.recipe_path)
            self.progress_signal.emit(10, 100)

            # Build list of supported resource files up front to fail fast if empty
            current_phase = "AAS"
            self.log_signal.emit(f"Scanning resource directory: {self.resource_dir}")
            resource_files = [
                f for f in os.listdir(self.resource_dir)
                if f.lower().endswith(('.xml', '.aasx', '.json'))
            ]
            
            if not resource_files:
                raise FileNotFoundError("No .xml, .aasx, or .json files found in the selected directory.")

            all_capabilities = {}
            resource_sources = {}
            total_files = len(resource_files)
            
            for idx, filename in enumerate(resource_files):
                full_path = os.path.join(self.resource_dir, filename)
                res_name = Path(filename).stem
                self.log_signal.emit(f"Parsing resource file: {filename}")
                
                try:
                    caps = parse_capabilities_robust(full_path)
                    if caps:
                        key_name = f"resource: {res_name}" 
                        all_capabilities[key_name] = caps
                        resource_sources[key_name] = filename
                except Exception as parse_err:
                    # Keep running but warn; a hard failure will be caught later
                    self.log_signal.emit(f"Warning: Failed to parse {filename}: {parse_err}")

                progress = 10 + int((idx + 1) / total_files * 20)
                self.progress_signal.emit(progress, 100)

            self.log_signal.emit(f"Loaded {len(all_capabilities)} valid resources.")
            if not all_capabilities: raise ValueError("No valid resources loaded.")

            # 2. Calculation mode configuration
            current_phase = "Calculation"
            find_all = True  # both modes need the full solution set
            is_opt = (self.mode_index == 1)
            
            mode_names = ["All Results", "Weighted Sorted Results"]
            self.log_signal.emit(f"Starting Calculation (Mode: {mode_names[self.mode_index]})...")
            
            # SMT run
            # Note: run_optimization returns (gui_results, json_solutions)
            # We force generate_json=True internally so we always have data for export, 
            # even in Fast/Pro mode if user wants to export.
            # Wait, user requirement: "Fast" finds 1 solution. 
            # Optimization logic in main: if generate_json=True, it builds the struct.
            # Let's ALWAYS generate the json struct in memory so export works for any valid solution found.
            
            gui_results, json_solutions, debug_payload = run_optimization(
                recipe_data, 
                all_capabilities, 
                log_callback=self.log_signal.emit, 
                generate_json=True, # Always generate structure for export capability
                find_all_solutions=find_all
            )
            
            self.progress_signal.emit(60, 100)

            # 3. Weighted mode: rank all solutions; default mode shows raw all results
            evaluated_solutions = []
            if is_opt and json_solutions:
                self.log_signal.emit("Weighted mode: Calculating costs and sorting all solutions...")
                
                optimizer = SolutionOptimizer()
                optimizer.set_weights(*self.weights)
                optimizer.load_resource_costs_from_dir(self.resource_dir)
                
                evaluated_solutions = optimizer.optimize_solutions_from_memory(json_solutions)
                
                sorted_gui_results = []
                
                for idx, eval_sol in enumerate(evaluated_solutions):
                    sol_id = eval_sol['solution_id']
                    rows = [r for r in gui_results if r.get('solution_id') == sol_id]
                    if not rows:
                        continue

                    # Header row per solution (replaces old blank spacer row)
                    sorted_gui_results.append({
                        "is_solution_header": True,
                        "solution_id": sol_id,
                        "composite_score": eval_sol['composite_score'],
                    })
                    
                    for row in rows:
                        row_copy = dict(row)
                        row_copy['composite_score'] = eval_sol['composite_score']

                        # Per-operation values (based on this row's assigned resource),
                        # not the whole solution aggregate.
                        resource_str = str(row_copy.get('resource', ''))
                        resource_name = resource_str.split(': ')[1] if ': ' in resource_str else resource_str
                        cost_data = optimizer.resource_costs.get(resource_name, {})
                        energy_raw = float(cost_data.get('EnergyCost', 0.0))
                        use_raw = float(cost_data.get('UseCost', 0.0))
                        co2_raw = float(cost_data.get('CO2Footprint', 0.0))
                        row_copy['energy_cost'] = energy_raw * optimizer.weights["EnergyCost"]
                        row_copy['use_cost'] = use_raw * optimizer.weights["UseCost"]
                        row_copy['co2_footprint'] = co2_raw * optimizer.weights["CO2Footprint"]
                        sorted_gui_results.append(row_copy)
                
                gui_results = sorted_gui_results
                if evaluated_solutions:
                    self.log_signal.emit(f"Weighted sorting complete. Top Solution ID: {evaluated_solutions[0]['solution_id']}")

            self.progress_signal.emit(100, 100)

            preview_solution_id = self._select_preview_solution_id(
                json_solutions=json_solutions,
                mode_index=self.mode_index,
                evaluated_solutions=evaluated_solutions,
            )

            master_recipe_preview_xml = ""
            master_recipe_flow = []
            if preview_solution_id:
                try:
                    preview_recipe_data = copy.deepcopy(recipe_data)
                    master_recipe_preview_xml = generate_b2mml_master_recipe(
                        resources_data=all_capabilities,
                        solutions_data_list=json_solutions,
                        general_recipe_data=preview_recipe_data,
                        selected_solution_id=preview_solution_id,
                        output_path=None,
                        log_callback=self.log_signal.emit,
                    )
                    master_recipe_flow = self._build_master_recipe_flow(
                        recipe_data=recipe_data,
                        json_solutions=json_solutions,
                        selected_solution_id=preview_solution_id,
                    )
                except Exception as preview_err:
                    self.log_signal.emit(f"Warning: Failed to build Master Recipe preview: {preview_err}")
            
            # [NEW] Pack context for export
            # We need: Resources (all_capabilities), Solutions (json_solutions), General Recipe (recipe_data)
            context_data = {
                'resources': all_capabilities,
                'solutions': json_solutions,
                'resource_sources': resource_sources,
                'recipe': recipe_data,
                'recipe_path': self.recipe_path,
                'resource_dir': self.resource_dir,
                'mode_index': self.mode_index,
                'mode_name': mode_names[self.mode_index],
                'preview_solution_id': preview_solution_id,
                'master_recipe_preview_xml': master_recipe_preview_xml,
                'master_recipe_flow': master_recipe_flow,
                'smt_model': (debug_payload or {}).get('smt_model', ''),
                'matching_debug': (debug_payload or {}).get('matching_debug', []),
            }
            
            self.finished_signal.emit(gui_results, context_data)

        except Exception as e:
            # Map technical errors to user-friendly phases
            phase = locals().get("current_phase", "Calculation")
            if phase == "Recipe":
                user_msg = "General Recipe read error"
            elif phase == "AAS":
                user_msg = "AAS file read error"
            else:
                user_msg = "Calculation error"
            self.error_signal.emit(user_msg)
            self.log_signal.emit(traceback.format_exc())
