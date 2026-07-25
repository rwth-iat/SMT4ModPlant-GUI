import json
from datetime import datetime
import os
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom

# Unit mapping (MTP -> SI/QUDT IRIs -> label)
from .mtp_unit_mapping import map_unit as map_unit_from_table

# Namespace constants
B2MML_NS = "http://www.mesa.org/xml/B2MML"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = "http://www.mesa.org/xml/B2MML Schema/AllSchemas.xsd"


def generate_b2mml_master_recipe(
    resources_data,
    solutions_data_list,
    general_recipe_data,
    selected_solution_id,
    output_path=None,
    log_callback=None,
):
    """
    Generate a B2MML Master Recipe XML from in-memory data.

    Args:
        resources_data: Resource capability data parsed from AAS/XML.
        solutions_data_list: Optimization solutions as a list, a dict with
            'solutions', or a PlantConfigurations artifact with
            'plant_configurations'.
        general_recipe_data: General recipe data.
        selected_solution_id: The chosen optimal solution ID.
        output_path: Optional output file path. If None, returns the XML string.
        log_callback: Optional function receiving informational export messages.

    Returns:
        If output_path is None: Returns XML string.
        If output_path is provided: Writes XML to file and returns the file path (or XML string on write failure).
    """
    emit_log = log_callback if callable(log_callback) else print

    # --- Find the selected solution ---
    optimal_solution = None
    solutions_data = solutions_data_list

    if isinstance(solutions_data, dict) and "plant_configurations" in solutions_data:
        solutions_list = solutions_data["plant_configurations"]
    elif isinstance(solutions_data, dict) and "solutions" in solutions_data:
        solutions_list = solutions_data["solutions"]
    elif isinstance(solutions_data, list):
        solutions_list = solutions_data
    else:
        raise ValueError(f"Unsupported solutions data format: {type(solutions_data)}")

    for solution in solutions_list:
        if solution.get("solution_id") == selected_solution_id:
            optimal_solution = solution
            break

    if not optimal_solution:
        raise ValueError(f"Optimal solution {selected_solution_id} not found in solutions data")

    # --- Register namespaces to force prefix "b2mml" and keep "xsi" ---
    # IMPORTANT: Do this BEFORE creating any elements.
    ET.register_namespace("b2mml", B2MML_NS)
    ET.register_namespace("xsi", XSI_NS)

    # --- Element creation helper (B2MML namespace) ---
    def create_element(parent, tag, **kwargs):
        """Create a B2MML namespaced element."""
        return ET.SubElement(parent, f"{{{B2MML_NS}}}{tag}", **kwargs)

    # --- Create root (B2MML namespace) ---
    root = ET.Element(ET.QName(B2MML_NS, "BatchInformation"))
    # schemaLocation is an xsi attribute
    root.set(ET.QName(XSI_NS, "schemaLocation"), SCHEMA_LOCATION)

    # ListHeader
    list_header = create_element(root, "ListHeader")
    create_element(list_header, "ID").text = "ListHeadID"
    create_element(list_header, "CreateDate").text = datetime.now().isoformat() + "+01:00"

    # Description
    desc = create_element(root, "Description")
    desc.text = (
        "This Batch Information includes the Master Recipe based on General Recipe "
        f"{general_recipe_data.get('ID', 'Unknown')} and Optimal Solution {selected_solution_id}"
    )

    # MasterRecipe
    master_recipe = create_element(root, "MasterRecipe")
    create_element(master_recipe, "ID").text = f"MasterRecipe_{selected_solution_id}"
    create_element(master_recipe, "Version").text = "1.0.0"
    create_element(master_recipe, "VersionDate").text = datetime.now().isoformat() + "+01:00"

    recipe_desc = create_element(master_recipe, "Description")
    recipe_desc.text = (
        "Master recipe based on General Recipe "
        f"{general_recipe_data.get('ID', 'Unknown')} and optimized solution {selected_solution_id} "
        "using resources from optimization"
    )

    # Header
    header = create_element(master_recipe, "Header")
    create_element(header, "ProductID").text = "StirredHeatedWater"
    create_element(header, "ProductName").text = "Stirred and Heated Water"

    # EquipmentRequirement
    equipment_req = create_element(master_recipe, "EquipmentRequirement")
    create_element(equipment_req, "ID").text = "Equipment Requirement for the HCs"

    constraint = create_element(equipment_req, "Constraint")
    create_element(constraint, "ID").text = "Material constraint"
    create_element(constraint, "Condition").text = "Material == H2O"

    create_element(equipment_req, "Description").text = "Only water is allowed for the stirring and heating process"

    # Formula - Collect all parameters
    formula = create_element(master_recipe, "Formula")

    def find_selected_capability_entry(assignment):
        resource_name = assignment.get("resource", "")
        resource_caps = resources_data.get(resource_name)
        if not isinstance(resource_caps, list):
            return None

        selected = assignment.get("selected_capability") or {}
        capability_index = selected.get("index")
        if isinstance(capability_index, int) and 0 <= capability_index < len(resource_caps):
            indexed_entry = resource_caps[capability_index]
            indexed_meta = (indexed_entry.get("capability") or [{}])[0]
            selected_name = selected.get("name")
            selected_id = selected.get("id")
            if (
                (not selected_name or indexed_meta.get("capability_name") == selected_name)
                and (not selected_id or indexed_meta.get("capability_ID") == selected_id)
            ):
                return indexed_entry

        selected_name = selected.get("name")
        selected_id = selected.get("id")
        if not selected_name:
            capabilities = assignment.get("capabilities") or []
            selected_name = capabilities[0] if len(capabilities) == 1 else None

        for capability_data in resource_caps:
            cap_meta = (capability_data.get("capability") or [{}])[0]
            if selected_id and cap_meta.get("capability_ID") == selected_id:
                return capability_data
            if selected_name and cap_meta.get("capability_name") == selected_name:
                return capability_data

        return None

    def selected_capability_metadata(assignment):
        selected = dict(assignment.get("selected_capability") or {})
        capability_entry = find_selected_capability_entry(assignment)
        cap_meta = (
            (capability_entry.get("capability") or [{}])[0]
            if isinstance(capability_entry, dict)
            else {}
        )
        capabilities = assignment.get("capabilities") or []

        if not selected.get("name"):
            selected["name"] = (
                cap_meta.get("capability_name")
                or (capabilities[0] if len(capabilities) == 1 else "Unknown")
            )
        if not selected.get("id"):
            selected["id"] = cap_meta.get("capability_ID", "")
        if not selected.get("realized_by"):
            selected["realized_by"] = (
                list(capability_entry.get("realized_by") or [])
                if isinstance(capability_entry, dict)
                else []
            )
        return selected, capability_entry

    # Helper: Find propertyRealizedBy only inside the selected capability.
    def find_property_realized_by(capability_data, property_name):
        if not isinstance(capability_data, dict):
            return None

        for prop in capability_data.get("properties", []):
            if prop.get("property_name") == property_name:
                return prop.get("propertyRealizedBy") or prop.get("property_realized_by")

        for prop in capability_data.get("properties", []):
            if prop.get("property_name", "").lower() == property_name.lower():
                return prop.get("propertyRealizedBy") or prop.get("property_realized_by")

        return None

    def get_export_value(param):
        values = param.get("Values")
        if not isinstance(values, list) or not values:
            values = [{
                "ValueString": param.get("ValueString"),
                "DataType": param.get("DataType"),
                "UnitOfMeasure": param.get("UnitOfMeasure"),
            }]

        populated = [
            value for value in values
            if isinstance(value, dict) and value.get("ValueString") not in (None, "")
        ]
        if len(populated) != 1:
            return None

        raw_value = str(populated[0].get("ValueString")).strip()
        match = re.fullmatch(r"(==|=)?\s*(.+)", raw_value)
        if not match or raw_value.startswith((">=", "<=", ">", "<", "!=")):
            return None

        return {
            "ValueString": match.group(2),
            "DataType": populated[0].get("DataType") or param.get("DataType", ""),
            "UnitOfMeasure": populated[0].get("UnitOfMeasure") or param.get("UnitOfMeasure", ""),
        }

    # Map data types
    def map_data_type(json_type):
        mapping = {
            "xs:int": "integer",
            "xs:double": "double",
            "int": "integer",
            "double": "double",
            "duration": "duration",
        }
        return mapping.get(json_type, json_type)
    # Map units (via external mapping table)
    def map_unit(unit_uri):
        return map_unit_from_table(unit_uri)
    # Store parameter mapping - global parameter counter
    param_mapping = {}
    global_param_counter = 1

    # Validate general recipe structure
    if "ProcessElements" not in general_recipe_data:
        raise ValueError("General recipe data must contain 'ProcessElements'")

    # Process all parameters first, assign unique ID for each parameter
    for pe in general_recipe_data["ProcessElements"]:
        # Find corresponding assignment in the selected solution
        assignment = None
        for a in optimal_solution.get("assignments", []):
            if a.get("step_id") == pe.get("ID"):
                assignment = a
                break

        if not assignment:
            emit_log(f"Warning: No assignment found for process element {pe.get('ID')}")
            continue

        if "Parameters" not in pe:
            continue

        selected_capability, selected_capability_entry = selected_capability_metadata(assignment)
        selected_capability_name = selected_capability.get("name", "Unknown")

        for param in pe["Parameters"]:
            param_id = None

            # Special handling for Dosing
            if pe.get("ID") == "Dosing001" and param.get("ID") == "Dosing_Amount001":
                property_realized_by = find_property_realized_by(
                    selected_capability_entry,
                    "Litre",
                )
                param_id = property_realized_by
            else:
                # Find matching property in capability_details
                for capability_detail in assignment.get("capability_details", []):
                    for matched_prop in capability_detail.get("matched_properties", []):
                        if (
                            matched_prop.get("property_id") == param.get("Key")
                            and matched_prop.get("property_unit") == param.get("UnitOfMeasure")
                        ):
                            property_realized_by = (
                                matched_prop.get("property_realized_by")
                                or find_property_realized_by(
                                    selected_capability_entry,
                                    matched_prop.get("property_name", ""),
                                )
                            )
                            param_id = property_realized_by
                            break
                    if param_id:
                        break

            # Matching properties may intentionally have no executable reference.
            if not param_id:
                emit_log(
                    "Info: Parameter "
                    f"{param.get('ID')} matched capability {selected_capability_name}, "
                    "but is omitted from the Master Recipe because propertyRealizedBy is missing."
                )
                continue

            export_value = get_export_value(param)
            if export_value is None:
                emit_log(
                    "Info: Parameter "
                    f"{param.get('ID')} matched capability {selected_capability_name}, "
                    "but is omitted from the Master Recipe because it defines a range "
                    "and no concrete setpoint was selected."
                )
                continue

            formatted_param_id = f"{global_param_counter:03d}:{param_id}"
            param_mapping[param["ID"]] = formatted_param_id

            # Create Parameter element
            param_elem = create_element(formula, "Parameter")
            create_element(param_elem, "ID").text = formatted_param_id

            resource_short = assignment.get("resource", "").replace("resource: ", "").replace("2025-04_", "")
            param_desc = f"{resource_short}_{param.get('Description', '').replace(' ', '_')}"
            create_element(param_elem, "Description").text = param_desc

            create_element(param_elem, "ParameterType").text = "ProcessParameter"
            create_element(param_elem, "ParameterSubType").text = "ST"

            value_elem = create_element(param_elem, "Value")
            create_element(value_elem, "ValueString").text = export_value["ValueString"]
            create_element(value_elem, "DataInterpretation").text = "Constant"
            create_element(value_elem, "DataType").text = map_data_type(export_value["DataType"])
            create_element(value_elem, "UnitOfMeasure").text = map_unit(export_value["UnitOfMeasure"])

            global_param_counter += 1

    # ProcedureLogic
    procedure_logic = create_element(master_recipe, "ProcedureLogic")

    # Create step list
    steps = []

    # 1) Start step
    steps.append({"id": "S1", "recipe_element_id": "Init", "description": "Init"})

    # 2) Operation steps in ProcessElements order
    step_counter = 2
    recipe_element_counter = 1

    for pe in general_recipe_data["ProcessElements"]:
        step_id = f"S{step_counter}"

        assignment = None
        for a in optimal_solution.get("assignments", []):
            if a.get("step_id") == pe.get("ID"):
                assignment = a
                break

        if not assignment:
            emit_log(f"Warning: No assignment found for process element {pe.get('ID')}")
            continue

        resource_short = assignment.get("resource", "").replace("resource: ", "").replace("2025-04_", "")

        selected_capability, _ = selected_capability_metadata(assignment)
        capability_name = selected_capability.get("name", "Unknown")

        # Use only the explicitly selected capability realization.
        recipe_element_id = None
        realized_by_list = selected_capability.get("realized_by") or []
        if not realized_by_list:
            raise ValueError(
                "Cannot generate Master Recipe: CapabilityRealizedBy is missing "
                f"for process element {pe.get('ID')} on resource "
                f"{assignment.get('resource')}."
            )
        recipe_element_id = f"{recipe_element_counter:03d}:{realized_by_list[0]}"

        step_description = f"{recipe_element_counter:03d}:{resource_short}_{pe.get('Description', '')}:{capability_name}"

        steps.append(
            {
                "id": step_id,
                "recipe_element_id": recipe_element_id,
                "description": step_description,
                "process_element": pe,
                "assignment": assignment,
                "recipe_element_number": recipe_element_counter,
                "capability_name": capability_name,
            }
        )

        # Store for later RecipeElement creation
        pe["recipe_element_id"] = recipe_element_id
        pe["recipe_element_number"] = recipe_element_counter
        pe["capability_name"] = capability_name

        step_counter += 1
        recipe_element_counter += 1

    # 3) End step
    steps.append({"id": f"S{step_counter}", "recipe_element_id": "End", "description": "End"})

    # Create links (Step -> Transition -> Step) sequentially
    link_counter = 1
    for i in range(len(steps) - 1):
        # Step i -> Transition i+1
        link = create_element(procedure_logic, "Link")
        create_element(link, "ID").text = f"L{link_counter}"

        from_id = create_element(link, "FromID")
        create_element(from_id, "FromIDValue").text = steps[i]["id"]
        create_element(from_id, "FromType").text = "Step"
        create_element(from_id, "IDScope").text = "External"

        to_id = create_element(link, "ToID")
        create_element(to_id, "ToIDValue").text = f"T{i+1}"
        create_element(to_id, "ToType").text = "Transition"
        create_element(to_id, "IDScope").text = "External"

        create_element(link, "LinkType").text = "ControlLink"
        create_element(link, "Depiction").text = "LineAndArrow"
        create_element(link, "EvaluationOrder").text = "1"
        create_element(link, "Description").text = "string"

        link_counter += 1

        # Transition i+1 -> Step i+1
        link = create_element(procedure_logic, "Link")
        create_element(link, "ID").text = f"L{link_counter}"

        from_id = create_element(link, "FromID")
        create_element(from_id, "FromIDValue").text = f"T{i+1}"
        create_element(from_id, "FromType").text = "Transition"
        create_element(from_id, "IDScope").text = "External"

        to_id = create_element(link, "ToID")
        create_element(to_id, "ToIDValue").text = steps[i + 1]["id"]
        create_element(to_id, "ToType").text = "Step"
        create_element(to_id, "IDScope").text = "External"

        create_element(link, "LinkType").text = "ControlLink"
        create_element(link, "Depiction").text = "LineAndArrow"
        create_element(link, "EvaluationOrder").text = "1"
        create_element(link, "Description").text = "string"

        link_counter += 1

    # Create Step elements
    for step in steps:
        step_elem = create_element(procedure_logic, "Step")
        create_element(step_elem, "ID").text = step["id"]
        create_element(step_elem, "RecipeElementID").text = step["recipe_element_id"]
        create_element(step_elem, "RecipeElementVersion")
        create_element(step_elem, "Description").text = step["description"]

    # Create Transition elements
    for i in range(1, len(steps)):
        transition = create_element(procedure_logic, "Transition")
        create_element(transition, "ID").text = f"T{i}"

        if i == 1:
            create_element(transition, "Condition").text = "True"
        else:
            prev_step_desc = steps[i - 1]["description"]
            create_element(transition, "Condition").text = f"Step {prev_step_desc} is Completed"

    # RecipeElements: Begin and End
    for elem_type, elem_id in [("Begin", "Init"), ("End", "End")]:
        recipe_elem = create_element(master_recipe, "RecipeElement")
        create_element(recipe_elem, "ID").text = elem_id
        create_element(recipe_elem, "RecipeElementType").text = elem_type

    # RecipeElements for each ProcessElement (sorted by recipe_element_number)
    recipe_elements_sorted = sorted(
        [pe for pe in general_recipe_data["ProcessElements"] if "recipe_element_number" in pe],
        key=lambda x: x["recipe_element_number"],
    )

    for pe in recipe_elements_sorted:
        assignment = None
        for a in optimal_solution.get("assignments", []):
            if a.get("step_id") == pe.get("ID"):
                assignment = a
                break

        if not assignment:
            continue

        recipe_elem = create_element(master_recipe, "RecipeElement")
        create_element(recipe_elem, "ID").text = pe["recipe_element_id"]

        resource_short = assignment.get("resource", "").replace("resource: ", "").replace("2025-04_", "")
        capability_name = pe.get("capability_name", "Unknown")

        pe_name_map = {
            "Mixing_of_Liquids": "Mixing",
            "Dosing": "Dosing",
            "Heating_of_liquids": "Heating",
        }
        pe_short = pe_name_map.get(pe.get("Description", ""), pe.get("Description", ""))

        create_element(recipe_elem, "Description").text = f"{resource_short}_{pe_short}_Procedure:{capability_name}"
        create_element(recipe_elem, "RecipeElementType").text = "Operation"
        create_element(recipe_elem, "ActualEquipmentID").text = f"{resource_short}Instance"

        equipment_req_ref = create_element(recipe_elem, "EquipmentRequirement")
        create_element(equipment_req_ref, "ID").text = "Equipment Requirement for the HCs"

        # Parameter references (only those actually added)
        for param in pe.get("Parameters", []) or []:
            if param.get("ID") in param_mapping:
                param_ref = create_element(recipe_elem, "Parameter")
                create_element(param_ref, "ID").text = param_mapping[param["ID"]]
                create_element(param_ref, "ParameterType").text = "ProcessParameter"

    # --- Serialize XML (with declaration) ---
    # Use bytes output so xml_declaration is correct and stable.
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)

    # Pretty print
    try:
        dom = minidom.parseString(xml_bytes)
        pretty_xml = dom.toprettyxml(indent="\t", encoding="utf-8").decode("utf-8")
    except Exception as e:
        emit_log(f"Warning: Could not pretty-print XML: {e}")
        pretty_xml = xml_bytes.decode("utf-8")

    # Save or return
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(pretty_xml)
            emit_log(f"Successfully saved Master Recipe to: {output_path}")
            return output_path
        except Exception as e:
            emit_log(f"Error saving file: {e}")
            return pretty_xml

    return pretty_xml


def save_b2mml_xml(xml_content, filename="MasterRecipe_B2MML.xml"):
    """Save the B2MML XML to a file (legacy helper)."""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"B2MML Master Recipe saved to {filename}")
    return filename


def main():
    """Main function for standalone execution."""
    try:
        print("Loading data files...")

        required_files = [
            "parsed_resource_capabilities_output.json",
            "solutions.json",
            "optimization_report.json",
            "parsed_recipe_output.json",
        ]
        for fn in required_files:
            if not os.path.exists(fn):
                print(f"Error: {fn} not found")
                return

        with open("parsed_resource_capabilities_output.json", "r", encoding="utf-8") as f:
            resources = json.load(f)

        with open("solutions.json", "r", encoding="utf-8") as f:
            solutions = json.load(f)

        with open("optimization_report.json", "r", encoding="utf-8") as f:
            optimization = json.load(f)

        with open("parsed_recipe_output.json", "r", encoding="utf-8") as f:
            general_recipe = json.load(f)

        optimal_solution_id = optimization["optimal_solution"]["solution_id"]

        print("Generating B2MML Master Recipe...")

        solutions_data = {"solutions": solutions.get("solutions", [])}

        result = generate_b2mml_master_recipe(
            resources_data=resources,
            solutions_data_list=solutions_data,
            general_recipe_data=general_recipe,
            selected_solution_id=optimal_solution_id,
            output_path="MasterRecipe_B2MML.xml",
        )

        print("\nB2MML Master Recipe Generation Complete!")
        print(f"\nUsing Optimal Solution: {optimal_solution_id}")
        print(f"Composite Score: {optimization['optimal_solution']['composite_score']}")

        print("\nResource Usage:")
        for resource, count in optimization["optimal_solution"]["resource_usage"].items():
            resource_short = resource.replace("resource: ", "").replace("2025-04_", "")
            print(f"  {resource_short}: {count} step(s)")

        print(f"\nTotal Energy Cost: {optimization['optimal_solution']['total_energy_cost']}")
        print(f"Total Use Cost: {optimization['optimal_solution']['total_use_cost']}")
        print(f"Total CO2 Footprint: {optimization['optimal_solution']['total_co2_footprint']}")
        print(f"Material Flow Consistent: {optimization['optimal_solution']['material_flow_consistent']}")

        if isinstance(result, str) and result.endswith(".xml"):
            print(f"\nOutput file: {result}")

    except FileNotFoundError as e:
        print(f"Error: Required data file not found: {str(e)}")
        print("Please ensure all required JSON files are in the current directory:")
        for fn in [
            "parsed_resource_capabilities_output.json",
            "solutions.json",
            "optimization_report.json",
            "parsed_recipe_output.json",
        ]:
            print(f" - {fn}")
    except Exception as e:
        print(f"Error generating B2MML Master Recipe: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
