import xml.etree.ElementTree as ET
import json
import zipfile
import os
import io
import re
from pathlib import Path


_CAEX_ID = re.compile(
    r"^CAEX@ID\s*=\s*[\"'\u2018\u2019\u201c\u201d]?"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"[\"'\u2018\u2019\u201c\u201d]?$",
    re.IGNORECASE,
)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _extract_realized_by_reference(relationship_element, ns):
    """Return the target ID from a RealizedBy relationship reference."""
    if relationship_element is None:
        return ""

    for reference_key in relationship_element.findall(
        "aas:second/aas:keys/aas:key", ns
    ):
        reference_type = reference_key.findtext(
            "aas:type", default="", namespaces=ns
        )
        if reference_type != "FragmentReference":
            continue

        value = reference_key.findtext(
            "aas:value", default="", namespaces=ns
        ).strip()
        caex_match = _CAEX_ID.fullmatch(value)
        if caex_match:
            return caex_match.group(1)
        if _UUID.fullmatch(value):
            return value

    return ""


def _parse_capability_qualifiers(capability_element, ns):
    """Extract capability role qualifiers and derive direct assignability."""
    qualifiers = []
    is_assignable = True

    for qualifier in capability_element.findall(
        "aas:qualifiers/aas:qualifier", ns
    ):
        qualifier_type = qualifier.findtext("aas:type", default="", namespaces=ns)
        qualifier_value = qualifier.findtext(
            "aas:value", default="", namespaces=ns
        )
        qualifier_entry = {
            "kind": qualifier.findtext("aas:kind", default="", namespaces=ns),
            "type": qualifier_type,
            "value_type": qualifier.findtext(
                "aas:valueType", default="", namespaces=ns
            ),
            "value": qualifier_value,
            "semantic_ids": [
                value.text
                for value in qualifier.findall("aas:semanticId//aas:value", ns)
                if value.text
            ],
        }
        qualifiers.append(qualifier_entry)

        if (
            qualifier_type.strip().lower() == "notassigned"
            and qualifier_value.strip().lower() in {"true", "1"}
        ):
            is_assignable = False

    return qualifiers, is_assignable


def _nonempty_reference_values(element, path, ns):
    '''Return unique, non-empty reference values while preserving XML order.'''
    values = []
    seen = set()
    for value_element in element.findall(path, ns):
        value = (value_element.text or '').strip()
        if value and value not in seen:
            seen.add(value)
            values.append(value)
    return values


def _model_reference_path(reference_element, ns):
    '''Return a complete AAS ModelReference key path as a hashable tuple.'''
    if reference_element is None:
        return ()

    path = []
    for key_element in reference_element.findall('aas:keys/aas:key', ns):
        key_type = key_element.findtext(
            'aas:type', default='', namespaces=ns
        ).strip()
        key_value = key_element.findtext(
            'aas:value', default='', namespaces=ns
        ).strip()
        if not key_type or not key_value:
            return ()
        path.append((key_type, key_value))
    return tuple(path)


def _capability_model_reference_path(
    capability_submodel,
    capability_set,
    capability_container,
    capability_element,
    ns,
):
    '''Build the canonical path used by ModelReferences to a capability.'''
    parts = (
        ('Submodel', capability_submodel.findtext(
            'aas:id', default='', namespaces=ns
        )),
        ('SubmodelElementCollection', capability_set.findtext(
            'aas:idShort', default='', namespaces=ns
        )),
        ('SubmodelElementCollection', capability_container.findtext(
            'aas:idShort', default='', namespaces=ns
        )),
        ('Capability', capability_element.findtext(
            'aas:idShort', default='', namespaces=ns
        )),
    )
    normalized = tuple(
        (key_type, (value or '').strip()) for key_type, value in parts
    )
    if any(not value for _, value in normalized):
        return ()
    return normalized


def _reference_path_payload(reference_path):
    return [
        {'type': key_type, 'value': key_value}
        for key_type, key_value in reference_path
    ]


def _resolve_generalizations(capabilities):
    '''Resolve GeneralizedBy references and collect inherited semantic IDs.'''
    path_index = {}
    for capability_index, capability in enumerate(capabilities):
        reference_path = capability.get('_model_reference_path') or ()
        if reference_path:
            path_index.setdefault(reference_path, []).append(capability_index)

    adjacency = [[] for _ in capabilities]
    for capability_index, capability in enumerate(capabilities):
        resolution_entries = []
        for target_reference in capability.get(
            '_direct_generalization_references', []
        ):
            indexed_targets = path_index.get(target_reference, [])
            resolution = {
                'target_reference': _reference_path_payload(target_reference),
                'resolved': False,
                'target_capability': '',
                'semantic_ids': [],
                'reason': None,
            }

            if not target_reference:
                resolution['reason'] = 'incomplete_reference'
            elif not indexed_targets:
                resolution['reason'] = 'target_not_found'
            elif len(indexed_targets) > 1:
                resolution['reason'] = 'ambiguous_target'
            else:
                target_index = indexed_targets[0]
                target_meta = (
                    capabilities[target_index].get('capability') or [{}]
                )[0]
                target_semantic_ids = list(
                    target_meta.get('semantic_ids') or []
                )
                resolution.update({
                    'resolved': True,
                    'target_capability': target_meta.get(
                        'capability_name', ''
                    ),
                    'semantic_ids': target_semantic_ids,
                    'reason': (
                        None
                        if target_semantic_ids
                        else 'target_missing_supplemental_semantic_id'
                    ),
                })
                adjacency[capability_index].append(target_index)

            resolution_entries.append(resolution)

        capability['generalization_resolution'] = resolution_entries

    for capability_index, capability in enumerate(capabilities):
        inherited_semantic_ids = []
        seen_semantic_ids = set()
        visited_capabilities = {capability_index}
        pending = list(adjacency[capability_index])

        while pending:
            target_index = pending.pop(0)
            if target_index in visited_capabilities:
                continue
            visited_capabilities.add(target_index)

            target_meta = (
                capabilities[target_index].get('capability') or [{}]
            )[0]
            for semantic_id in target_meta.get('semantic_ids') or []:
                if semantic_id not in seen_semantic_ids:
                    seen_semantic_ids.add(semantic_id)
                    inherited_semantic_ids.append(semantic_id)

            pending.extend(adjacency[target_index])

        capability['generalized_by_semantic_ids'] = inherited_semantic_ids
        capability.pop('_model_reference_path', None)
        capability.pop('_direct_generalization_references', None)


def parse_capabilities_robust(file_path):
    """
    Parse an AAS file (XML, AASX, or JSON via basyx) and extract capabilities.
    JSON inputs are converted to XML in memory so the downstream parser can stay unchanged.

    Args:
        file_path: Path to an AAS file (.xml, .aasx, or .json).

    Returns:
        List of capability dictionaries compatible with the SMT pipeline.
    """
    
    tree = None
    file_path_str = str(file_path)
    
    # -------------------------------------------------------
    # Handle JSON with basyx (converted to XML in-memory)
    # -------------------------------------------------------
    if file_path_str.lower().endswith('.json'):
        try:
            from basyx.aas.adapter.json import read_aas_json_file
            from basyx.aas.adapter.xml import write_aas_xml_file
        except ImportError:
            print("Error: basyx-python-sdk is required to read JSON AAS files. Please install it via pip.")
            return []
        try:
            # Load AAS structures from JSON then emit equivalent XML into a buffer
            shells, assets, submodels, concept_descriptions = read_aas_json_file(file_path_str)
            buf = io.BytesIO()
            write_aas_xml_file(buf, shells, assets, submodels, concept_descriptions)
            buf.seek(0)
            tree = ET.parse(buf)
        except Exception as e:
            print(f"Error converting JSON AAS file {file_path} to XML: {e}")
            return []
    
    # -------------------------------------------------------
    # Handle .aasx (ZIP archive) and standard .xml
    # -------------------------------------------------------
    elif file_path_str.lower().endswith('.aasx'):
        try:
            with zipfile.ZipFile(file_path, 'r') as z:
                # Find the main XML file inside the archive
                xml_files = [
                    f for f in z.namelist() 
                    if f.endswith('.xml') 
                    and not f.startswith('_rels') 
                    and '[Content_Types]' not in f
                ]
                
                if not xml_files:
                    print(f"Warning: No valid XML found in AASX package: {file_path}")
                    return []
                
                # Use the first found XML file
                target_xml = xml_files[0]
                
                # Read and parse directly from the zip stream
                with z.open(target_xml) as f:
                    tree = ET.parse(f)
        except zipfile.BadZipFile:
            print(f"Error: File is corrupted or not a valid AASX package: {file_path}")
            return []
        except Exception as e:
            print(f"Error processing AASX file {file_path}: {e}")
            return []
    else:
        # Standard XML file parsing
        try:
            tree = ET.parse(file_path)
        except ET.ParseError as e:
            print(f"Error parsing XML file {file_path}: {e}")
            return []
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return []

    if tree is None:
        return []

    return _extract_capabilities_from_etree(tree)


def _extract_capabilities_from_etree(tree: ET.ElementTree):
    """
    Core parsing logic shared by XML/AASX and JSON (converted to XML).

    Args:
        tree: Parsed ElementTree of an Asset Administration Shell.

    Returns:
        List of capability dictionaries with properties and relations.
    """
    root = tree.getroot()
    ns = {'aas': 'https://admin-shell.io/aas/3/0'}

    capabilities = []

    # Iterate through all Submodels
    for capability_SM in root.findall(".//aas:submodel", ns):
        capability_SM_value = capability_SM.find(".//aas:value", ns)
        
        if capability_SM_value is not None and ("https://admin-shell.io/idta/CapabilityDescription/1/0/Submodel" in capability_SM_value.text or "https://admin-shell.io/idta/SubmodelTemplate/CapabilityDescription/1/0" in capability_SM_value.text):
            
            for capability_sets in capability_SM.findall("aas:submodelElements/aas:submodelElementCollection", ns):
                for capability_container in capability_sets.findall("aas:value/aas:submodelElementCollection", ns):
                    for capability_element in capability_container.findall("aas:value/aas:capability", ns):
                        if capability_element is not None:
                            capability_element_name = capability_element.find("aas:idShort", ns)
                            capability_comment = capability_container.find("aas:value/aas:multiLanguageProperty/aas:value//aas:text", ns)
                            capability_qualifiers, is_assignable = (
                                _parse_capability_qualifiers(
                                    capability_element, ns
                                )
                            )
                            capability_semantic_ids = _nonempty_reference_values(
                                capability_element,
                                'aas:supplementalSemanticIds//aas:value',
                                ns,
                            )
                            
                            capability = {
                                'capability': [],
                                'properties': [],
                                'generalized_by': [],
                                'generalized_by_semantic_ids': [],
                                'generalization_resolution': [],
                                'realized_by': [],
                                'capability_qualifiers': capability_qualifiers,
                                'is_assignable': is_assignable,
                                '_model_reference_path': (
                                    _capability_model_reference_path(
                                        capability_SM,
                                        capability_sets,
                                        capability_container,
                                        capability_element,
                                        ns,
                                    )
                                ),
                                '_direct_generalization_references': [],
                            }

                            capability['capability'].append({
                                'capability_name': capability_element_name.text if capability_element_name is not None else "Unknown",
                                'capability_comment': capability_comment.text if capability_comment is not None else "",
                                'capability_ID': (
                                    capability_semantic_ids[0]
                                    if capability_semantic_ids else ''
                                ),
                                'semantic_ids': capability_semantic_ids,
                            })

                            # Process Properties
                            for property_sets in capability_container.findall(".//aas:submodelElementCollection", ns):
                                property_sets_value = property_sets.find(".//aas:value", ns)
                                if property_sets_value is not None and "https://admin-shell.io/idta/CapabilityDescription/PropertySet/1/0" in property_sets_value.text:
                                    for property_container in property_sets.findall(".//aas:submodelElementCollection", ns):

                                        # Scalar Properties
                                        property_type_scalar = property_container.find(
                                            "aas:value/aas:property", ns
                                        )
                                        if property_type_scalar is not None:
                                            prop_name = property_type_scalar.find("aas:idShort", ns)
                                            prop_id = property_type_scalar.find(
                                                "aas:supplementalSemanticIds//aas:value", ns
                                            )
                                            unit = property_type_scalar.find(
                                                "aas:embeddedDataSpecifications//aas:value", ns
                                            )
                                            vtype = property_type_scalar.find("aas:valueType", ns)
                                            scalar_value = property_type_scalar.find("aas:value", ns)
                                            prop_comment = property_container.find(
                                                "aas:value/aas:multiLanguageProperty/"
                                                "aas:value//aas:text",
                                                ns,
                                            )
                                            prop_rel_by = property_container.find(
                                                "aas:value/aas:relationshipElement",
                                                ns,
                                            )

                                            capability["properties"].append({
                                                "property_name": (
                                                    prop_name.text
                                                    if prop_name is not None else ""
                                                ),
                                                "property_comment": (
                                                    prop_comment.text
                                                    if prop_comment is not None else ""
                                                ),
                                                "property_ID": (
                                                    prop_id.text
                                                    if prop_id is not None else ""
                                                ),
                                                "property_unit": (
                                                    unit.text
                                                    if unit is not None else ""
                                                ),
                                                "valueType": (
                                                    vtype.text
                                                    if vtype is not None else ""
                                                ),
                                                "value0": (
                                                    scalar_value.text
                                                    if scalar_value is not None else ""
                                                ),
                                                "propertyRealizedBy": (
                                                    _extract_realized_by_reference(
                                                        prop_rel_by, ns
                                                    )
                                                ),
                                                "property_constraint": [],
                                            })

                                        # Range Properties
                                        property_type_range = property_container.find("aas:value/aas:range", ns)
                                        if property_type_range is not None:
                                            # ... (Extraction logic identical to previous versions) ...
                                            prop_name = property_type_range.find("aas:idShort", ns)
                                            prop_id = property_type_range.find("aas:supplementalSemanticIds//aas:value", ns)
                                            unit = property_type_range.find("aas:embeddedDataSpecifications//aas:value", ns)
                                            vtype = property_type_range.find("aas:valueType", ns)
                                            min_val = property_type_range.find("aas:min", ns)
                                            max_val = property_type_range.find("aas:max", ns)
                                            prop_comment = property_container.find("aas:value/aas:multiLanguageProperty/aas:value//aas:text", ns)
                                            prop_relBy = property_container.find(
                                                "aas:value/aas:relationshipElement", ns
                                            )

                                            prop_entry = {
                                                'property_name': prop_name.text if prop_name is not None else "",
                                                'property_comment': prop_comment.text if prop_comment is not None else "",
                                                'property_ID': prop_id.text if prop_id is not None else "",
                                                'property_unit': unit.text if unit is not None else "",
                                                'valueType': vtype.text if vtype is not None else "",
                                                'valueMin': min_val.text if min_val is not None else "",
                                                'valueMax': max_val.text if max_val is not None else "",
                                                'propertyRealizedBy': _extract_realized_by_reference(prop_relBy, ns),
                                                'property_constraint': []
                                            }
                                            
                                            # Constraints Logic
                                            for capability_relations in capability_container.findall(".//aas:submodelElementCollection", ns):
                                                capability_relations_semantic_id = capability_relations.find("aas:semanticId//aas:value", ns)
                                                if capability_relations_semantic_id is not None and "https://admin-shell.io/idta/CapabilityDescription/CapabilityRelations/1/0" in capability_relations_semantic_id.text:
                                                    for constraint_sets in capability_relations.findall("aas:value/aas:submodelElementCollection", ns):
                                                        constraint_set_semantic_id = constraint_sets.find("aas:semanticId//aas:value", ns)
                                                        if constraint_set_semantic_id is not None and "https://admin-shell.io/idta/CapabilityDescription/ConstraintSet/1/0" in constraint_set_semantic_id.text:
                                                            for constraint_set in constraint_sets.findall("aas:value/aas:submodelElementCollection", ns):
                                                                constraint_set_semantic_id = constraint_set.find("aas:semanticId//aas:value", ns)
                                                                if constraint_set_semantic_id is not None and "https://admin-shell.io/idta/CapabilityDescription/PropertyConstraintContainer/1/0" in constraint_set_semantic_id.text:
                                                                    for relationship_constraint in constraint_set.findall("aas:value/aas:submodelElementCollection/aas:value/aas:relationshipElement", ns):
                                                                        second_keys = relationship_constraint.find("aas:second/aas:keys", ns)
                                                                        if second_keys is not None:
                                                                            key_elements = second_keys.findall("aas:key", ns)
                                                                            if key_elements:
                                                                                last_key = key_elements[-1]
                                                                                last_value = last_key.find("aas:value", ns)
                                                                                if last_value is not None and prop_name is not None and last_value.text == prop_name.text:
                                                                                    # Parse constraint details
                                                                                    constraint_type = None
                                                                                    conditional_type = None
                                                                                    property_constraint_ID = None
                                                                                    property_constraint_unit = None
                                                                                    property_constraint_value = None

                                                                                    for property_elements in constraint_set.findall("aas:value/aas:property", ns):
                                                                                        property_element_semantic_id = property_elements.find("aas:semanticId//aas:value", ns)
                                                                                        if property_element_semantic_id is not None:
                                                                                            sid_text = property_element_semantic_id.text
                                                                                            if "ConstraintType/1/0" in sid_text:
                                                                                                val = property_elements.find("aas:value", ns)
                                                                                                constraint_type = val.text if val is not None else ""
                                                                                            elif "PropertyConditionalType/1/0" in sid_text:
                                                                                                val = property_elements.find("aas:value", ns)
                                                                                                conditional_type = val.text if val is not None else ""
                                                                                            elif "BasicConstraint/1/0" in sid_text:
                                                                                                cid = property_elements.find("aas:supplementalSemanticIds//aas:value", ns)
                                                                                                u = property_elements.find("aas:embeddedDataSpecifications//aas:value", ns)
                                                                                                q = property_elements.find("aas:qualifiers//aas:value", ns)
                                                                                                cv = property_elements.find("aas:value", ns)
                                                                                                property_constraint_ID = cid.text if cid is not None else ""
                                                                                                property_constraint_unit = u.text if u is not None else ""
                                                                                                raw_val = cv.text if cv is not None else ""
                                                                                                q_val = q.text if q is not None else ""
                                                                                                if q_val == "GREATER_THAN_0": property_constraint_value = ">" + raw_val
                                                                                                elif q_val == "GREATER_EQUAL_1": property_constraint_value = ">=" + raw_val
                                                                                                elif q_val == "EQUAL_2": property_constraint_value = "==" + raw_val
                                                                                                elif q_val == "NOT_EQUAL_3": property_constraint_value = "!=" + raw_val
                                                                                                elif q_val == "LESS_EQUAL_4": property_constraint_value = "<=" + raw_val
                                                                                                elif q_val == "LESS_THAN_5": property_constraint_value = "<" + raw_val
                                                                                                else: property_constraint_value = raw_val

                                                                                    constraint = {
                                                                                        'conditional_type': conditional_type if conditional_type else "",
                                                                                        'constraint_type': constraint_type if constraint_type else "",
                                                                                        'property_constraint_ID': property_constraint_ID if property_constraint_ID else "",
                                                                                        'property_constraint_unit': property_constraint_unit if property_constraint_unit else "",
                                                                                        'property_constraint_value': property_constraint_value if property_constraint_value else ""
                                                                                    }
                                                                                    if any(v != "" for v in constraint.values()):
                                                                                        prop_entry['property_constraint'].append(constraint)
                                            capability['properties'].append(prop_entry)

                                        # SubmodelElementList Properties
                                        property_type_submodelElementList = property_container.find("aas:value/aas:submodelElementList", ns)
                                        if property_type_submodelElementList is not None:
                                            prop_name = property_type_submodelElementList.find("aas:idShort", ns)
                                            prop_id = property_type_submodelElementList.find("aas:supplementalSemanticIds//aas:value", ns)
                                            unit = property_type_submodelElementList.find("aas:embeddedDataSpecifications//aas:value", ns)
                                            vtype = property_type_submodelElementList.find("aas:valueTypeListElement", ns)
                                            prop_comment = property_container.find("aas:value/aas:multiLanguageProperty/aas:value//aas:text", ns)
                                            prop_relBy = property_container.find(
                                                "aas:value/aas:relationshipElement", ns
                                            )

                                            result = {
                                                'property_name': prop_name.text if prop_name is not None else "",
                                                'property_comment': prop_comment.text if prop_comment is not None else "",
                                                'property_ID': prop_id.text if prop_id is not None else "",
                                                'property_unit': unit.text if unit is not None else "",
                                                'valueType': vtype.text if vtype is not None else ""
                                            }
                                            value_list = property_type_submodelElementList.findall("aas:value/aas:property", ns)
                                            for i, val_elem in enumerate(value_list):
                                                val = val_elem.find("aas:value", ns)
                                                result[f"value{i}"] = val.text if val is not None else ""
                                            result['propertyRealizedBy'] = _extract_realized_by_reference(prop_relBy, ns)
                                            capability['properties'].append(result)

                            # Relations (GeneralizedBy / RealizedBy)
                            for capability_relations in capability_container.findall(".//aas:submodelElementCollection", ns):
                                capability_relations_semantic_id = capability_relations.find("aas:semanticId//aas:value", ns)
                                if capability_relations_semantic_id is not None and "https://admin-shell.io/idta/CapabilityDescription/CapabilityRelations/1/0" in capability_relations_semantic_id.text:
                                    for generalized_by_sets in capability_relations.findall("aas:value/aas:submodelElementCollection", ns):
                                        generalized_by_semantic_id = generalized_by_sets.find("aas:semanticId//aas:value", ns)
                                        if generalized_by_semantic_id is not None and "GeneralizedBySet/1/0" in generalized_by_semantic_id.text:
                                            for relationship_generalized_by in generalized_by_sets.findall("aas:value/aas:relationshipElement", ns):
                                                second_keys = relationship_generalized_by.find("aas:second/aas:keys", ns)
                                                if second_keys is not None:
                                                    key_elements = second_keys.findall("aas:key", ns)
                                                    if key_elements:
                                                        last_key = key_elements[-1]
                                                        last_value = last_key.find("aas:value", ns)
                                                        if last_value is not None:
                                                            capability['generalized_by'].append(last_value.text)
                                            for relationship_generalized_by in generalized_by_sets.findall(
                                                'aas:value/aas:relationshipElement', ns
                                            ):
                                                target_reference = _model_reference_path(
                                                    relationship_generalized_by.find(
                                                        'aas:second', ns
                                                    ),
                                                    ns,
                                                )
                                                capability[
                                                    '_direct_generalization_references'
                                                ].append(target_reference)
                                    for realized_by in capability_relations.findall("aas:value/aas:relationshipElement", ns):
                                        realized_by_semantic_id = realized_by.find("aas:semanticId//aas:value", ns)
                                        if realized_by_semantic_id is not None and "CapabilityRealizedBy/1/0" in realized_by_semantic_id.text:
                                            realized_by_value = _extract_realized_by_reference(
                                                realized_by, ns
                                            )
                                            if realized_by_value:
                                                capability['realized_by'].append(realized_by_value)

                            capabilities.append(capability)

    _resolve_generalizations(capabilities)
    return capabilities
