# Code/SMT4ModPlant/SMT4ModPlant_main.py
import json
import math
import re
from z3 import Solver, Bool, Not, Sum, If, is_true, sat, And

# Global constants
TRANSPORT_CAPABILITIES = ["Dosing", "Transfer", "Discharge"]

# ---------------------------------------------------------
# HELPER FUNCTIONS (Condensed for brevity, logic unchanged)
# ---------------------------------------------------------

def load_json(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def capability_matching(recipe_sem_id, cap_entry):
    return _semantic_match_details(recipe_sem_id, cap_entry)[0]


def _semantic_id_list(values):
    if not isinstance(values, (list, tuple, set)):
        values = [values]

    normalized = []
    seen = set()
    for value in values:
        semantic_id = str(value).strip() if value is not None else ""
        if semantic_id and semantic_id not in seen:
            seen.add(semantic_id)
            normalized.append(semantic_id)
    return normalized


def _semantic_match_details(recipe_sem_id, cap_entry):
    """Match exact supplemental semantic IDs and report their provenance."""
    recipe_semantic_id = (
        str(recipe_sem_id).strip() if recipe_sem_id is not None else ""
    )
    cap_meta = (cap_entry.get("capability") or [{}])[0]

    direct_ids = _semantic_id_list(cap_meta.get("semantic_ids") or [])
    legacy_capability_id = cap_meta.get("capability_ID")
    if not direct_ids and legacy_capability_id:
        direct_ids = _semantic_id_list([legacy_capability_id])

    generalized_ids = _semantic_id_list(
        cap_entry.get("generalized_by_semantic_ids") or []
    )
    details = {
        "source": None,
        "direct_semantic_ids": direct_ids,
        "generalized_semantic_ids": generalized_ids,
        "generalization_resolution": list(
            cap_entry.get("generalization_resolution") or []
        ),
    }

    if recipe_semantic_id and recipe_semantic_id in direct_ids:
        details["source"] = "direct"
        return True, details
    if recipe_semantic_id and recipe_semantic_id in generalized_ids:
        details["source"] = "generalized"
        return True, details
    return False, details

_NUMERIC_CONSTRAINT_RE = re.compile(
    r"^\s*(>=|<=|==|!=|>|<|=)?\s*([-+]?(?:\d+(?:[\.,]\d*)?|[\.,]\d+))\s*$"
)


def _parameter_values(param_or_value):
    """Return normalized value dictionaries for legacy and multi-value parameters."""
    if isinstance(param_or_value, dict):
        values = param_or_value.get("Values")
        if isinstance(values, list) and values:
            return [value for value in values if isinstance(value, dict)]
        return [{
            "ValueString": param_or_value.get("ValueString"),
            "DataType": param_or_value.get("DataType"),
            "UnitOfMeasure": param_or_value.get("UnitOfMeasure"),
            "Key": param_or_value.get("Key"),
        }]

    if isinstance(param_or_value, (list, tuple)):
        return [
            value if isinstance(value, dict) else {"ValueString": value}
            for value in param_or_value
        ]

    return [{"ValueString": param_or_value}]


def _parse_numeric_constraints(param_or_value):
    constraints = []
    for value in _parameter_values(param_or_value):
        raw_value = value.get("ValueString")
        if raw_value is None or str(raw_value).strip() == "":
            continue
        match = _NUMERIC_CONSTRAINT_RE.fullmatch(str(raw_value))
        if not match:
            return None
        operator, number = match.groups()
        constraints.append((operator or "=", float(number.replace(",", "."))))
    return constraints


def _discrete_property_values(prop):
    values = []
    for key, raw_value in prop.items():
        if (
            key.startswith("value")
            and key not in {"valueType", "valueMin", "valueMax"}
            and raw_value not in (None, "")
        ):
            try:
                values.append(float(str(raw_value).replace(",", ".")))
            except (ValueError, TypeError):
                continue
    return values


def _optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _value_satisfies_constraints(value, constraints):
    for operator, required in constraints:
        if operator in ("=", "==") and value != required:
            return False
        if operator == "!=" and value == required:
            return False
        if operator == ">=" and value < required:
            return False
        if operator == ">" and value <= required:
            return False
        if operator == "<=" and value > required:
            return False
        if operator == "<" and value >= required:
            return False
    return True


def _ranges_intersect_constraints(resource_min, resource_max, constraints):
    lower = -math.inf if resource_min is None else resource_min
    upper = math.inf if resource_max is None else resource_max
    lower_inclusive = resource_min is not None
    upper_inclusive = resource_max is not None
    exact_value = None
    excluded_values = set()

    for operator, required in constraints:
        if operator in ("=", "=="):
            if exact_value is not None and exact_value != required:
                return False
            exact_value = required
        elif operator == "!=":
            excluded_values.add(required)
        elif operator in (">", ">="):
            inclusive = operator == ">="
            if required > lower:
                lower = required
                lower_inclusive = inclusive
            elif required == lower:
                lower_inclusive = lower_inclusive and inclusive
        elif operator in ("<", "<="):
            inclusive = operator == "<="
            if required < upper:
                upper = required
                upper_inclusive = inclusive
            elif required == upper:
                upper_inclusive = upper_inclusive and inclusive

    if exact_value is not None:
        if exact_value in excluded_values:
            return False
        if exact_value < lower or exact_value > upper:
            return False
        if exact_value == lower and not lower_inclusive:
            return False
        if exact_value == upper and not upper_inclusive:
            return False
        return True

    if lower < upper:
        return True
    if lower > upper:
        return False
    return lower_inclusive and upper_inclusive and lower not in excluded_values


def property_value_match(param_value, prop):
    """
    Check whether a property offers at least one value satisfying all recipe constraints.

    ``param_value`` accepts both the legacy scalar value and a full parameter dictionary
    containing the new ``Values`` list.
    """
    constraints = _parse_numeric_constraints(param_value)
    if constraints is None:
        return False
    if not constraints:
        return True

    discrete_values = _discrete_property_values(prop)
    if discrete_values:
        return any(
            _value_satisfies_constraints(value, constraints)
            for value in discrete_values
        )

    has_range = "valueMin" in prop or "valueMax" in prop
    if has_range:
        return _ranges_intersect_constraints(
            _optional_float(prop.get("valueMin")),
            _optional_float(prop.get("valueMax")),
            constraints,
        )

    return True

def properties_compatible(recipe_step, cap_entry):
    if "Parameters" not in recipe_step or not recipe_step["Parameters"]:
        return True, []
    matched_props = []
    for param in recipe_step["Parameters"]:
        param_values = _parameter_values(param)
        param_keys = {
            value.get("Key") for value in param_values if value.get("Key")
        } or {param.get("Key")}
        param_units = {
            value.get("UnitOfMeasure")
            for value in param_values
            if value.get("UnitOfMeasure")
        } or {param.get("UnitOfMeasure")}
        match_found = False
        for prop in cap_entry.get("properties", []):
            if any(key and prop.get("property_ID") != key for key in param_keys):
                continue
            if any(
                unit
                and prop.get("property_unit")
                and prop.get("property_unit") != unit
                for unit in param_units
            ):
                continue
            if property_value_match(param, prop):
                matched_props.append((param, prop))
                match_found = True
                break
        if not match_found:
            return False, []
    return True, matched_props


def _summarize_matched_properties(matched_props):
    """Convert raw (param, property) pairs into a JSON-friendly debug structure."""
    summary = []
    for param, prop in matched_props:
        summary.append({
            "parameter_id": param.get("ID"),
            "parameter_description": param.get("Description"),
            "parameter_key": param.get("Key"),
            "parameter_unit": param.get("UnitOfMeasure"),
            "parameter_value": param.get("ValueString"),
            "parameter_values": [
                value.get("ValueString") for value in _parameter_values(param)
            ],
            "property_id": prop.get("property_ID"),
            "property_name": prop.get("property_name"),
            "property_unit": prop.get("property_unit"),
            "value_min": prop.get("valueMin"),
            "value_max": prop.get("valueMax"),
        })
    return summary


def _analyze_capability_match(recipe_data, step, cap_entry):
    """
    Evaluate one capability against one recipe step and return debug details.

    Returns:
        debug_entry: dict describing semantic/property/precondition checks
        matched_props_local: list[(param, prop)] for successful property matches
    """
    sem_id = step.get("SemanticDescription", "")
    cap_meta = (cap_entry.get("capability") or [{}])[0]
    cap_name = cap_meta.get("capability_name", "Unknown")
    cap_id = cap_meta.get("capability_ID", "")
    is_assignable = cap_entry.get("is_assignable", True) is not False

    semantic_match, semantic_details = _semantic_match_details(
        sem_id, cap_entry
    )
    properties_match = False
    preconditions_match = False
    matched_props_local = []

    if semantic_match:
        properties_match, matched_props_local = properties_compatible(step, cap_entry)

    if semantic_match and properties_match:
        preconditions_match = check_preconditions_for_step(recipe_data, step, cap_entry)

    debug_entry = {
        "capability_name": cap_name,
        "capability_id": cap_id,
        "is_assignable": is_assignable,
        "assignment_exclusion_reason": (
            None if is_assignable else "not_assigned"
        ),
        "semantic_match": semantic_match,
        "semantic_match_source": semantic_details["source"],
        "semantic_ids_checked": {
            "direct": semantic_details["direct_semantic_ids"],
            "generalized": semantic_details["generalized_semantic_ids"],
        },
        "generalization_resolution": semantic_details[
            "generalization_resolution"
        ],
        "unresolved_generalizations": [
            resolution
            for resolution in semantic_details["generalization_resolution"]
            if not resolution.get("resolved", False)
        ],
        "properties_match": properties_match,
        "preconditions_match": preconditions_match,
        "matched_properties": _summarize_matched_properties(matched_props_local),
    }
    return debug_entry, matched_props_local

def check_preconditions_for_step(recipe, step, cap_entry):
    step_id = step['ID']
    links = recipe.get('DirectedLinks', [])
    input_material_ids = [link['FromID'] for link in links if link.get('ToID') == step_id]
    
    materials = recipe.get('Inputs', []) + recipe.get('Intermediates', [])
    input_materials = [mat for mat in materials if mat['ID'] in input_material_ids]
    
    for prop in cap_entry.get('properties', []):
        for constraint in prop.get('property_constraint', []):
            if constraint.get('conditional_type') == "Pre":
                constraint_id = constraint.get('property_constraint_ID')
                constraint_unit = constraint.get('property_constraint_unit')
                constraint_value_str = constraint.get('property_constraint_value')
                matched = False
                for mat in input_materials:
                    if mat.get('Key') == constraint_id and mat.get('UnitOfMeasure') == constraint_unit:
                        try:
                            import re
                            match = re.match(r'(>=|<=|>|<|=)?\s*([0-9\.,]+)', constraint_value_str)
                            if match:
                                op, val = match.groups()
                                op = op or '='
                                cval = float(val.replace(',', '.'))
                                mval = float(mat['Quantity'])
                                if ((op == '>=' and mval >= cval) or (op == '>' and mval > cval) or
                                    (op == '<=' and mval <= cval) or (op == '<' and mval < cval) or
                                    (op == '=' and mval == cval)):
                                    matched = True
                                    break
                        except Exception: continue
                if not matched: return False
    return True

def _selected_candidate(model, candidates):
    for candidate in candidates:
        if is_true(model[candidate["var"]]):
            return candidate
    return None


def is_materialflow_consistent(model, Assignment, process_steps, recipe):
    material_location = {inp['ID']: None for inp in recipe.get('Inputs', [])}
    material_location.update({interm['ID']: None for interm in recipe.get('Intermediates', [])})
    material_location.update({out['ID']: None for out in recipe.get('Outputs', [])})

    step_by_id = {step['ID']: idx for idx, step in enumerate(process_steps)}
    selected_by_step = {}

    for i, step in enumerate(process_steps):
        candidate = _selected_candidate(model, Assignment[i])
        if candidate is not None:
            selected_by_step[step['ID']] = candidate

    for link in recipe.get('DirectedLinks', []):
        from_id = link['FromID']
        to_id = link['ToID']

        if from_id in step_by_id and to_id in material_location:
            candidate = selected_by_step.get(from_id)
            if candidate is None:
                return False
            if candidate["capability_name"] in TRANSPORT_CAPABILITIES:
                material_location[to_id] = None
            else:
                material_location[to_id] = candidate["resource"]
            continue

        if from_id in material_location and to_id in step_by_id:
            candidate = selected_by_step.get(to_id)
            if candidate is None:
                return False
            assigned_res = candidate["resource"]
            from_res = material_location[from_id]
            if candidate["capability_name"] in TRANSPORT_CAPABILITIES:
                if from_res is not None and from_res != assigned_res:
                    return False
            else:
                if from_res is not None and from_res != assigned_res:
                    return False
                material_location[from_id] = assigned_res
    return True


def _property_realized_by(prop):
    return prop.get("propertyRealizedBy") or prop.get("property_realized_by") or ""


def solution_to_json(model, process_steps, Assignment, solution_id):
    """Convert the solution to JSON format"""
    solution_data = {
        "solution_id": solution_id,
        "assignments": [],
        "material_flow_consistent": True
    }

    for i, step in enumerate(process_steps):
        candidate = _selected_candidate(model, Assignment[i])
        if candidate is None:
            continue

        assignment_info = {
            "step_id": step['ID'],
            "step_description": step['Description'],
            "resource": candidate["resource"],
            "capabilities": [candidate["capability_name"]],
            "selected_capability": {
                "index": candidate["capability_index"],
                "name": candidate["capability_name"],
                "id": candidate["capability_id"],
                "realized_by": list(candidate["realized_by"]),
            },
            "parameter_matches": []
        }

        for param in step.get("Parameters", []):
            assignment_info["parameter_matches"].append({
                "description": param.get('Description'),
                "key": param.get('Key'),
                "unit": param.get('UnitOfMeasure'),
                "value": param.get('ValueString'),
                "values": [
                    value.get("ValueString") for value in _parameter_values(param)
                ],
            })

        cap_info = {
            "capability_name": candidate["capability_name"],
            "capability_id": candidate["capability_id"],
            "capability_index": candidate["capability_index"],
            "matched_properties": [],
        }
        for param, prop in candidate["matched_props"]:
            prop_info = {
                "property_id": prop.get('property_ID'),
                "property_name": prop.get('property_name'),
                "property_unit": prop.get('property_unit'),
                "property_realized_by": _property_realized_by(prop),
            }
            discrete_values = _discrete_property_values(prop)
            value_min = prop.get('valueMin')
            value_max = prop.get('valueMax')

            if discrete_values:
                if len(discrete_values) == 1:
                    prop_info["value"] = discrete_values[0]
                    prop_info["value_type"] = "exact"
                else:
                    prop_info["values"] = discrete_values
                    prop_info["value_type"] = "discrete_set"
            elif "valueMin" in prop or "valueMax" in prop:
                prop_info["value_min"] = value_min
                prop_info["value_max"] = value_max
                prop_info["value_type"] = "range"
            else:
                prop_info["value_type"] = "unspecified"
            cap_info["matched_properties"].append(prop_info)

        assignment_info["capability_details"] = [cap_info]
        solution_data["assignments"].append(assignment_info)
    return solution_data


def _parameter_requirement_text(param):
    values = [
        str(value.get("ValueString")).strip()
        for value in _parameter_values(param)
        if value.get("ValueString") not in (None, "")
    ]
    return " & ".join(values) if values else "?"


def _display_unit(unit):
    """Return a compact unit label for plain values and URI-based units."""
    if unit in (None, ""):
        return ""

    label = str(unit).strip().rstrip("/")
    if "#" in label:
        label = label.rsplit("#", 1)[-1]
    if "/" in label:
        label = label.rsplit("/", 1)[-1]
    return label


def _unit_suffix(unit):
    label = _display_unit(unit)
    return f" [{label}]" if label else ""


def _parameter_unit(param):
    for value in _parameter_values(param):
        unit = value.get("UnitOfMeasure")
        if unit not in (None, ""):
            return unit
    return param.get("UnitOfMeasure", "")


def format_required_capability(step):
    """Format a process step and all requested parameters for the result table."""
    step_description = step.get("Description") or step.get("ID") or "Process step"
    lines = [str(step_description)]

    for param in step.get("Parameters", []):
        parameter_id = param.get("ID") or "Parameter"
        requirement = _parameter_requirement_text(param)
        lines.append(
            f"    {parameter_id}: {requirement}{_unit_suffix(_parameter_unit(param))}"
        )

    return "\n".join(lines)


def format_capability_string(cap_prop_pairs):
    """Format only the values offered by the selected resource capability."""
    display_parts = []
    for cap_name, offered_props in cap_prop_pairs:
        param_strs = []
        for property_entry in offered_props:
            if (
                isinstance(property_entry, (list, tuple))
                and len(property_entry) == 2
            ):
                param, prop = property_entry
            else:
                param, prop = {}, property_entry

            if not isinstance(prop, dict):
                continue

            param_desc = prop.get("property_name") or param.get("ID") or "Parameter"
            res_val = "?"
            v_min = prop.get('valueMin')
            v_max = prop.get('valueMax')
            discrete_vals = [
                str(value)
                for key, value in prop.items()
                if key.startswith("value")
                and key not in {"valueType", "valueMin", "valueMax"}
                and value not in (None, "")
            ]
            if "valueMin" in prop or "valueMax" in prop:
                lower_bound = "-inf" if v_min in (None, "") else str(v_min)
                upper_bound = "inf" if v_max in (None, "") else str(v_max)
                res_val = f"{lower_bound} -> {upper_bound}"
            elif discrete_vals:
                res_val = f"{{{', '.join(discrete_vals)}}}"
            param_strs.append(
                f"    {param_desc}: {res_val}{_unit_suffix(prop.get('property_unit'))}"
            )
        if param_strs:
            display_parts.append("\n".join([cap_name, *param_strs]))
        else:
            display_parts.append(cap_name)
    return "\n".join(display_parts)

# ---------------------------------------------------------
# EXPORTED FUNCTION
# ---------------------------------------------------------

def _sanitize_resource_name(res: str) -> str:
    """Make resource names safe for use in Z3 variable identifiers."""
    return res.replace(":", "").replace(" ", "_")


def _match_step_to_resource_caps(
    recipe_data,
    step,
    res,
    capabilities_data,
):
    """
    Collect concrete capability candidates for a given (step, resource).

    Returns:
        candidates: list[dict] - one entry per matching capability
        capability_debug: list[dict] - capability-by-capability diagnostics
    """
    cap_list = capabilities_data[res]

    candidates = []
    capability_debug = []

    for capability_index, cap_entry in enumerate(cap_list):
        cap_debug, matched_props_local = _analyze_capability_match(recipe_data, step, cap_entry)
        cap_debug["capability_index"] = capability_index
        capability_debug.append(cap_debug)

        if not cap_debug["is_assignable"]:
            continue
        if not cap_debug["semantic_match"]:
            continue
        if not cap_debug["properties_match"]:
            continue
        if not cap_debug["preconditions_match"]:
            continue

        candidates.append({
            "capability_index": capability_index,
            "capability_name": cap_debug["capability_name"],
            "capability_id": cap_debug["capability_id"],
            "realized_by": list(cap_entry.get("realized_by") or []),
            "matched_props": matched_props_local,
            "offered_props": list(cap_entry.get("properties") or []),
        })

    return candidates, capability_debug


def _build_model_and_assignments(
    recipe_data,
    capabilities_data,
    process_steps,
    resources,
):
    """
    Build the SMT model skeleton:
      - Create assignment Bool variables for (step, resource, capability)
      - Keep every matching capability as a distinct selectable candidate
      - Store candidate metadata for reporting, export, and material-flow checks

    Returns:
        solver: z3.Solver
        Assignment: list[list[candidate dict]]
        matching_debug: list[dict] storing per-step/per-resource debug data
    """
    solver = Solver()
    Assignment = []
    matching_debug = []

    for i, step in enumerate(process_steps):
        step_candidates = []

        for j, res in enumerate(resources):
            candidates, capability_debug = _match_step_to_resource_caps(
                recipe_data=recipe_data,
                step=step,
                res=res,
                capabilities_data=capabilities_data,
            )

            invalid_reasons = []
            if not candidates:
                invalid_reasons.append("no_capability_match")

            valid = len(invalid_reasons) == 0

            matching_debug.append({
                "step_index": i,
                "step_id": step.get("ID"),
                "step_description": step.get("Description"),
                "step_semantic_description": step.get("SemanticDescription"),
                "resource_index": j,
                "resource": res,
                "candidate_valid": valid,
                "invalid_reasons": invalid_reasons,
                "matched_capabilities": [
                    candidate["capability_name"] for candidate in candidates
                ],
                "capability_checks": capability_debug,
            })

            for candidate in candidates:
                capability_index = candidate["capability_index"]
                varname = (
                    f"assign_{step['ID']}_r{j}_c{capability_index}_"
                    f"{_sanitize_resource_name(res)}"
                )
                step_candidates.append({
                    **candidate,
                    "step_index": i,
                    "resource_index": j,
                    "resource": res,
                    "var": Bool(varname),
                })

        Assignment.append(step_candidates)

    return solver, Assignment, matching_debug


def _add_exactly_one_candidate_per_step_constraints(solver, Assignment):
    """
    Enforce that each process step is executed on exactly one resource.
    If a step has zero candidates, the model becomes UNSAT immediately.
    """
    for step_candidates in Assignment:
        vars_for_step = [candidate["var"] for candidate in step_candidates]
        if vars_for_step:
            solver.add(Sum([If(v, 1, 0) for v in vars_for_step]) == 1)
        else:
            # No candidates => forced UNSAT.
            solver.add(False)


def _block_current_solution(solver, Assignment, model):
    """
    Block the current solution so the next SAT call finds a different assignment.
    We block the conjunction of all variables that were True in this solution.
    """
    true_vars = []
    for candidates in Assignment:
        for candidate in candidates:
            var = candidate["var"]
            if is_true(model[var]):
                true_vars.append(var)

    if true_vars:
        solver.add(Not(And(true_vars)))


def _append_solution_results_for_gui(
    all_results_for_gui,
    solution_id,
    process_steps,
    Assignment,
    model,
):
    """
    Convert one model solution into GUI rows and append into all_results_for_gui.
    """
    if solution_id > 1:
        # Keep your original GUI separation behavior between solutions.
        all_results_for_gui.append({})

    for i, step in enumerate(process_steps):
        candidate = _selected_candidate(model, Assignment[i])
        if candidate is None:
            continue
        formatted_cap_str = format_capability_string([(
            candidate["capability_name"],
            candidate["offered_props"],
        )])

        all_results_for_gui.append({
            "solution_id": solution_id,
            "step_id": step["ID"],
            "description": step["Description"],
            "required_capability": format_required_capability(step),
            "resource": candidate["resource"],
            "capability_name": candidate["capability_name"],
            "capabilities": formatted_cap_str,
            "status": "Matched"
        })


def run_optimization(recipe_data, capabilities_data, log_callback=print, generate_json=False, find_all_solutions=True):
    """
    Solve the recipe-to-resource assignment problem using SMT.

    Args:
        recipe_data: Parsed recipe structure (expects recipe_data['ProcessElements'])
        capabilities_data: Dict[resource_name -> list of capability entries]
        log_callback: Logger function (default: print)
        generate_json: If True, also build JSON solution objects
        find_all_solutions: If True, enumerate all solutions (with blocking clauses)

    Returns:
        (gui_results_list, all_solutions_json_list, debug_payload)
    """
    process_steps = recipe_data["ProcessElements"]
    resources = list(capabilities_data.keys())

    log_callback(f"Starting optimization (Find All: {find_all_solutions})...")

    # 1) Build model + assignment variables with early pruning rules.
    solver, Assignment, matching_debug = _build_model_and_assignments(
        recipe_data=recipe_data,
        capabilities_data=capabilities_data,
        process_steps=process_steps,
        resources=resources,
    )

    # 2) Select exactly one concrete resource/capability candidate per step.
    _add_exactly_one_candidate_per_step_constraints(solver, Assignment)

    try:
        smt_model = solver.to_smt2()
    except Exception:
        try:
            smt_model = solver.sexpr()
        except Exception:
            smt_model = ""

    log_callback("Solving constraints...")

    attempt_count = 0
    max_attempts = 2_000_000

    all_results_for_gui = []
    all_json_solutions = []
    valid_solution_count = 0

    # 3) Enumerate SAT models, filter by material-flow consistency, block each found model.
    while solver.check() == sat:
        model = solver.model()
        attempt_count += 1

        # Additional semantic/material-flow filter (outside SMT constraints).
        if is_materialflow_consistent(
            model, Assignment, process_steps, recipe_data
        ):
            valid_solution_count += 1
            log_callback(f"Solution {valid_solution_count} Found (Attempt {attempt_count})!")

            if generate_json:
                solution_json = solution_to_json(
                    model, process_steps, Assignment, valid_solution_count
                )
                all_json_solutions.append(solution_json)

            _append_solution_results_for_gui(
                all_results_for_gui=all_results_for_gui,
                solution_id=valid_solution_count,
                process_steps=process_steps,
                Assignment=Assignment,
                model=model,
            )

            if not find_all_solutions:
                break

        # Block current assignment and continue searching.
        _block_current_solution(solver, Assignment, model)

        if attempt_count >= max_attempts:
            break

    if valid_solution_count == 0:
        log_callback("UNSAT (No Solution Found).")
    else:
        log_callback(f"Search finished. Found {valid_solution_count} valid solution(s).")

    debug_payload = {
        "smt_model": smt_model,
        "matching_debug": matching_debug,
        "step_count": len(process_steps),
        "resource_count": len(resources),
    }

    return all_results_for_gui, all_json_solutions, debug_payload
