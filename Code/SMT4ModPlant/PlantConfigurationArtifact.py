from pathlib import Path


def _file_name(path):
    return Path(path).name if path else ""


def _resource_name(resource_key):
    prefix = "resource: "
    if isinstance(resource_key, str) and resource_key.startswith(prefix):
        return resource_key[len(prefix):]
    return resource_key


def _is_concrete_parameter(parameter_match):
    values = parameter_match.get("values")
    if not isinstance(values, list) or not values:
        values = [parameter_match.get("value")]

    populated = [value for value in values if value not in (None, "")]
    if len(populated) != 1:
        return False

    value = str(populated[0]).strip()
    return bool(value) and not value.startswith((">=", "<=", ">", "<", "!="))


def validate_plant_configurations(solutions):
    """Return blocking errors and non-blocking warnings for an export."""
    errors = []
    warnings = []

    if not isinstance(solutions, list) or not solutions:
        return ["No plant configurations are available for export."], warnings

    for configuration_index, configuration in enumerate(solutions, start=1):
        solution_id = configuration.get("solution_id", configuration_index)
        assignments = configuration.get("assignments")
        if not isinstance(assignments, list) or not assignments:
            errors.append(
                f"Plant configuration {solution_id} has no assignments."
            )
            continue

        for assignment_index, assignment in enumerate(assignments, start=1):
            step_id = assignment.get("step_id") or f"assignment {assignment_index}"
            resource = assignment.get("resource")
            selected = assignment.get("selected_capability") or {}
            capability = selected.get("id") or selected.get("name")
            realized_by = [
                value for value in (selected.get("realized_by") or []) if value
            ]

            if not resource:
                errors.append(
                    f"Plant configuration {solution_id}, step {step_id}: "
                    "assigned resource is missing."
                )
            if not capability:
                errors.append(
                    f"Plant configuration {solution_id}, step {step_id}: "
                    "selected capability is missing."
                )
            if not realized_by:
                errors.append(
                    f"Plant configuration {solution_id}, step {step_id}: "
                    "CapabilityRealizedBy is missing."
                )

            parameter_matches = {
                match.get("key"): match
                for match in assignment.get("parameter_matches", [])
                if match.get("key")
            }
            for capability_detail in assignment.get("capability_details", []):
                for prop in capability_detail.get("matched_properties", []):
                    if prop.get("property_realized_by"):
                        continue

                    parameter_key = prop.get("required_parameter_semantic_id")
                    parameter_match = parameter_matches.get(parameter_key, {})
                    message = (
                        f"Plant configuration {solution_id}, step {step_id}, "
                        f"parameter {parameter_key or prop.get('property_name')}: "
                        "PropertyRealizedBy is missing."
                    )
                    if parameter_match and _is_concrete_parameter(parameter_match):
                        errors.append(message)
                    else:
                        warnings.append(message)

    return errors, warnings


def build_plant_configurations_artifact(context_data):
    """Build the public PlantConfigurations export without mutating solver data."""
    recipe = context_data.get("recipe") or {}
    resources = context_data.get("resources") or {}
    resource_sources = context_data.get("resource_sources") or {}

    source_resources = []
    for resource_key in resources:
        source_resources.append({
            "resource": _resource_name(resource_key),
            "file": _file_name(resource_sources.get(resource_key)),
        })

    return {
        "artifact_type": "PlantConfigurations",
        "source": {
            "general_recipe": {
                "id": recipe.get("ID"),
                "file": _file_name(context_data.get("recipe_path")),
            },
            "resources": source_resources,
        },
        "process_context": {
            "directed_links": recipe.get("DirectedLinks") or [],
        },
        "plant_configurations": context_data.get("solutions") or [],
    }
