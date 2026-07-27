import copy
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from Code.SMT4ModPlant.AASxmlCapabilityParser import parse_capabilities_robust
from Code.SMT4ModPlant.AASxmlCapabilityParser import _resolve_generalizations
from Code.SMT4ModPlant.GeneralRecipeParser import parse_general_recipe
from Code.SMT4ModPlant.SMT4ModPlant_main import (
    capability_matching,
    format_capability_string,
    format_required_capability,
    property_value_match,
    run_optimization,
)
from Code.Optimizer.Optimization import SolutionOptimizer
from Code.Transformator.MasterRecipeGenerator import generate_b2mml_master_recipe


B2MML_NS = "http://www.mesa.org/xml/B2MML"
AAS_NS = "https://admin-shell.io/aas/3/0"


def _minimal_capability_xml(capability_name, qualifier_xml=""):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<environment xmlns="{AAS_NS}">
  <submodels>
    <submodel>
      <semanticId>
        <type>ExternalReference</type>
        <keys>
          <key>
            <type>GlobalReference</type>
            <value>https://admin-shell.io/idta/CapabilityDescription/1/0/Submodel</value>
          </key>
        </keys>
      </semanticId>
      <submodelElements>
        <submodelElementCollection>
          <idShort>CapabilitySet</idShort>
          <value>
            <submodelElementCollection>
              <idShort>{capability_name}Container</idShort>
              <value>
                <capability>
                  <idShort>{capability_name}</idShort>
                  <supplementalSemanticIds>
                    <reference>
                      <type>ExternalReference</type>
                      <keys>
                        <key>
                          <type>GlobalReference</type>
                          <value>urn:test#{capability_name}</value>
                        </key>
                      </keys>
                    </reference>
                  </supplementalSemanticIds>
                  {qualifier_xml}
                </capability>
              </value>
            </submodelElementCollection>
          </value>
        </submodelElementCollection>
      </submodelElements>
    </submodel>
  </submodels>
</environment>
"""


def _qualifier_xml(qualifier_type, value, semantic_id="urn:test#role"):
    return f"""
<qualifiers>
  <qualifier>
    <semanticId>
      <type>ExternalReference</type>
      <keys>
        <key>
          <type>GlobalReference</type>
          <value>{semantic_id}</value>
        </key>
      </keys>
    </semanticId>
    <kind>ValueQualifier</kind>
    <type>{qualifier_type}</type>
    <valueType>xs:boolean</valueType>
    <value>{value}</value>
  </qualifier>
</qualifiers>
"""


def _generalized_capability_xml(target_semantic_id):
    supplemental_xml = ""
    if target_semantic_id is not None:
        supplemental_xml = f"""
                  <supplementalSemanticIds>
                    <reference>
                      <type>ExternalReference</type>
                      <keys><key><type>GlobalReference</type><value>{target_semantic_id}</value></key></keys>
                    </reference>
                  </supplementalSemanticIds>"""

    return f"""<?xml version="1.0" encoding="utf-8"?>
<environment xmlns="{AAS_NS}">
  <submodels>
    <submodel>
      <id>urn:test:capability-submodel</id>
      <semanticId><type>ExternalReference</type><keys><key>
        <type>GlobalReference</type>
        <value>https://admin-shell.io/idta/CapabilityDescription/1/0/Submodel</value>
      </key></keys></semanticId>
      <submodelElements>
        <submodelElementCollection>
          <idShort>CapabilitySet</idShort>
          <value>
            <submodelElementCollection>
              <idShort>ChildContainer</idShort>
              <value>
                <capability><idShort>FreelyNamedChild</idShort></capability>
                <submodelElementCollection>
                  <idShort>CapabilityRelations</idShort>
                  <semanticId><type>ExternalReference</type><keys><key>
                    <type>GlobalReference</type>
                    <value>https://admin-shell.io/idta/CapabilityDescription/CapabilityRelations/1/0</value>
                  </key></keys></semanticId>
                  <value>
                    <submodelElementCollection>
                      <idShort>GeneralizedBySet</idShort>
                      <semanticId><type>ExternalReference</type><keys><key>
                        <type>GlobalReference</type>
                        <value>https://admin-shell.io/idta/CapabilityDescription/GeneralizedBySet/1/0</value>
                      </key></keys></semanticId>
                      <value>
                        <relationshipElement>
                          <idShort>ChildGeneralizedByTarget</idShort>
                          <second><type>ModelReference</type><keys>
                            <key><type>Submodel</type><value>urn:test:capability-submodel</value></key>
                            <key><type>SubmodelElementCollection</type><value>CapabilitySet</value></key>
                            <key><type>SubmodelElementCollection</type><value>TargetContainer</value></key>
                            <key><type>Capability</type><value>FreelyNamedTarget</value></key>
                          </keys></second>
                        </relationshipElement>
                      </value>
                    </submodelElementCollection>
                  </value>
                </submodelElementCollection>
              </value>
            </submodelElementCollection>
            <submodelElementCollection>
              <idShort>TargetContainer</idShort>
              <value>
                <capability>
                  <idShort>FreelyNamedTarget</idShort>{supplemental_xml}
                </capability>
              </value>
            </submodelElementCollection>
          </value>
        </submodelElementCollection>
      </submodelElements>
    </submodel>
  </submodels>
</environment>
"""


def _parse_capability_xml(xml):
    with tempfile.TemporaryDirectory() as temp_dir:
        resource_path = Path(temp_dir) / "resource.xml"
        resource_path.write_text(xml, encoding="utf-8")
        return parse_capabilities_robust(resource_path)


def _parse_capability_aasx(xml):
    with tempfile.TemporaryDirectory() as temp_dir:
        resource_path = Path(temp_dir) / "resource.aasx"
        with zipfile.ZipFile(resource_path, "w") as package:
            package.writestr("aas.xml", xml)
        return parse_capabilities_robust(resource_path)


def _rotation_parameter():
    return {
        "ID": "RotationSpeed001",
        "Description": "Rotation speed requirement",
        "ValueString": ">=50",
        "DataType": "int",
        "UnitOfMeasure": "rpm",
        "Key": "rotation",
        "Values": [
            {
                "ValueString": ">=50",
                "DataType": "int",
                "UnitOfMeasure": "rpm",
                "Key": "rotation",
            },
            {
                "ValueString": "<=300",
                "DataType": "int",
                "UnitOfMeasure": "rpm",
                "Key": "rotation",
            },
        ],
    }


def _duration_parameter():
    return {
        "ID": "MixingDuration001",
        "Description": "Mixing duration",
        "ValueString": "15",
        "DataType": "int",
        "UnitOfMeasure": "second",
        "Key": "duration",
        "Values": [
            {
                "ValueString": "15",
                "DataType": "int",
                "UnitOfMeasure": "second",
                "Key": "duration",
            }
        ],
    }


def _capability(name, capability_id, realized_by):
    properties = [
        {
            "property_name": "RotationSpeed",
            "property_ID": "rotation",
            "property_unit": "rpm",
            "valueType": "xs:int",
            "value0": "100",
            "value1": "150",
            "propertyRealizedBy": "",
        },
        {
            "property_name": "StirringDuration",
            "property_ID": "duration",
            "property_unit": "second",
            "valueType": "xs:int",
            "valueMin": "0",
            "valueMax": "",
            "propertyRealizedBy": f"{name}-duration-property",
            "property_constraint": [],
        },
    ]
    if name == "StirringPulseDuration":
        properties.extend([
            {
                "property_name": "CycleTime",
                "property_ID": "cycle-time",
                "property_unit": "second",
                "valueType": "xs:int",
                "valueMin": "1",
                "valueMax": "20",
                "propertyRealizedBy": "",
                "property_constraint": [],
            },
            {
                "property_name": "DutyCycle",
                "property_ID": "duty-cycle",
                "property_unit": "percent",
                "valueType": "xs:int",
                "valueMin": "0",
                "valueMax": "100",
                "propertyRealizedBy": "",
                "property_constraint": [],
            },
        ])

    return {
        "capability": [{
            "capability_name": name,
            "capability_ID": capability_id,
            "semantic_ids": [capability_id] if capability_id else [],
            "capability_comment": "",
        }],
        "properties": properties,
        "generalized_by": ["MixingOfLiquids"],
        "generalized_by_semantic_ids": ["urn:test#MixingOfLiquids"],
        "generalization_resolution": [],
        "realized_by": [realized_by],
    }


def _capability_reference_path(container, capability_name, set_name="CapabilitySet"):
    return (
        ("Submodel", "urn:test:capability-submodel"),
        ("SubmodelElementCollection", set_name),
        ("SubmodelElementCollection", container),
        ("Capability", capability_name),
    )


def _semantic_graph_entry(
    capability_name,
    semantic_ids=(),
    container=None,
    targets=(),
    assignable=True,
):
    semantic_ids = list(semantic_ids)
    reference_path = _capability_reference_path(
        container or f"{capability_name}Container",
        capability_name,
    )
    return {
        "capability": [{
            "capability_name": capability_name,
            "capability_ID": semantic_ids[0] if semantic_ids else "",
            "semantic_ids": semantic_ids,
            "capability_comment": "",
        }],
        "properties": [],
        "generalized_by": [target[-1][1] for target in targets],
        "generalized_by_semantic_ids": [],
        "generalization_resolution": [],
        "realized_by": [],
        "capability_qualifiers": [],
        "is_assignable": assignable,
        "_model_reference_path": reference_path,
        "_direct_generalization_references": list(targets),
    }


class GeneralRecipeParserTests(unittest.TestCase):
    def test_preserves_all_parameter_values(self):
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<b2mml:GeneralRecipe xmlns:b2mml="{B2MML_NS}">
  <b2mml:ID>Recipe</b2mml:ID>
  <b2mml:Description>Test recipe</b2mml:Description>
  <b2mml:ProcessElement>
    <b2mml:ID>MixingOfLiquids001</b2mml:ID>
    <b2mml:Description>MixingOfLiquids</b2mml:Description>
    <b2mml:ProcessElementParameter>
      <b2mml:ID>RotationSpeed001</b2mml:ID>
      <b2mml:Description>Rotation speed</b2mml:Description>
      <b2mml:Value>
        <b2mml:ValueString>&gt;=50</b2mml:ValueString>
        <b2mml:DataType>int</b2mml:DataType>
        <b2mml:UnitOfMeasure>rpm</b2mml:UnitOfMeasure>
        <b2mml:Key>rotation</b2mml:Key>
      </b2mml:Value>
      <b2mml:Value>
        <b2mml:ValueString>&lt;=300</b2mml:ValueString>
        <b2mml:DataType>int</b2mml:DataType>
        <b2mml:UnitOfMeasure>rpm</b2mml:UnitOfMeasure>
        <b2mml:Key>rotation</b2mml:Key>
      </b2mml:Value>
    </b2mml:ProcessElementParameter>
    <b2mml:OtherInformation>
      <b2mml:OtherValue>
        <b2mml:ValueString>urn:test#MixingOfLiquids</b2mml:ValueString>
      </b2mml:OtherValue>
    </b2mml:OtherInformation>
  </b2mml:ProcessElement>
</b2mml:GeneralRecipe>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            recipe_path = Path(temp_dir) / "recipe.xml"
            recipe_path.write_text(xml, encoding="utf-8")
            recipe = parse_general_recipe(recipe_path)

        parameter = recipe["ProcessElements"][0]["Parameters"][0]
        self.assertEqual(parameter["ValueString"], ">=50")
        self.assertEqual(
            [value["ValueString"] for value in parameter["Values"]],
            [">=50", "<=300"],
        )


class AASCapabilityParserTests(unittest.TestCase):
    def test_resolves_generalized_by_target_to_supplemental_id(self):
        capabilities = _parse_capability_xml(
            _generalized_capability_xml("urn:test#MixingOfLiquids")
        )
        by_name = {
            entry["capability"][0]["capability_name"]: entry
            for entry in capabilities
        }
        child = by_name["FreelyNamedChild"]

        self.assertEqual(
            child["generalized_by_semantic_ids"],
            ["urn:test#MixingOfLiquids"],
        )
        self.assertTrue(child["generalization_resolution"][0]["resolved"])
        self.assertTrue(capability_matching(
            "urn:test#MixingOfLiquids", child
        ))

    def test_resolved_target_without_supplemental_id_does_not_match(self):
        capabilities = _parse_capability_xml(
            _generalized_capability_xml(None)
        )
        child = next(
            entry for entry in capabilities
            if entry["capability"][0]["capability_name"]
            == "FreelyNamedChild"
        )

        self.assertEqual(child["generalized_by_semantic_ids"], [])
        self.assertEqual(
            child["generalization_resolution"][0]["reason"],
            "target_missing_supplemental_semantic_id",
        )
        self.assertFalse(capability_matching(
            "urn:test#MixingOfLiquids", child
        ))

    def test_capability_without_qualifier_remains_assignable(self):
        capability = _parse_capability_xml(
            _minimal_capability_xml("LegacyCapability")
        )[0]
        self.assertEqual(capability["capability_qualifiers"], [])
        self.assertTrue(capability["is_assignable"])

    def test_offered_true_remains_assignable_and_preserves_qualifier(self):
        capability = _parse_capability_xml(_minimal_capability_xml(
            "ConveyingEmpty",
            _qualifier_xml("Offered", "true", "urn:test#Offered"),
        ))[0]
        self.assertTrue(capability["is_assignable"])
        self.assertEqual(capability["capability_qualifiers"], [{
            "kind": "ValueQualifier",
            "type": "Offered",
            "value_type": "xs:boolean",
            "value": "true",
            "semantic_ids": ["urn:test#Offered"],
        }])

    def test_not_assigned_true_disables_direct_assignment(self):
        capability = _parse_capability_xml(_minimal_capability_xml(
            "Conveying",
            _qualifier_xml("NotAssigned", "true", "urn:test#Offered"),
        ))[0]
        self.assertFalse(capability["is_assignable"])
        self.assertEqual(
            capability["capability_qualifiers"][0]["semantic_ids"],
            ["urn:test#Offered"],
        )

    def test_not_assigned_boolean_variants(self):
        cases = [
            ("NotAssigned", "false", True),
            ("NotAssigned", "0", True),
            ("NotAssigned", "1", False),
            ("nOtAsSiGnEd", "TRUE", False),
        ]
        for qualifier_type, value, expected in cases:
            with self.subTest(qualifier_type=qualifier_type, value=value):
                capability = _parse_capability_xml(_minimal_capability_xml(
                    "Capability",
                    _qualifier_xml(qualifier_type, value),
                ))[0]
                self.assertEqual(capability["is_assignable"], expected)

    def test_not_assigned_true_wins_over_offered_true(self):
        qualifier_xml = (
            _qualifier_xml("Offered", "true")
            + _qualifier_xml("NotAssigned", "true")
        )
        capability = _parse_capability_xml(_minimal_capability_xml(
            "AbstractCapability", qualifier_xml
        ))[0]
        self.assertFalse(capability["is_assignable"])

    def test_parses_scalar_property_into_discrete_value_format(self):
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<environment xmlns="{AAS_NS}">
  <submodels>
    <submodel>
      <semanticId>
        <type>ExternalReference</type>
        <keys>
          <key>
            <type>GlobalReference</type>
            <value>https://admin-shell.io/idta/CapabilityDescription/1/0/Submodel</value>
          </key>
        </keys>
      </semanticId>
      <submodelElements>
        <submodelElementCollection>
          <idShort>CapabilitySet</idShort>
          <value>
            <submodelElementCollection>
              <idShort>StirringDurationContainer</idShort>
              <value>
                <capability>
                  <idShort>StirringDuration</idShort>
                  <supplementalSemanticIds>
                    <reference>
                      <type>ExternalReference</type>
                      <keys>
                        <key>
                          <type>GlobalReference</type>
                          <value>urn:test#StirringDuration</value>
                        </key>
                      </keys>
                    </reference>
                  </supplementalSemanticIds>
                </capability>
                <submodelElementCollection>
                  <idShort>PropertySet</idShort>
                  <semanticId>
                    <type>ExternalReference</type>
                    <keys>
                      <key>
                        <type>GlobalReference</type>
                        <value>https://admin-shell.io/idta/CapabilityDescription/PropertySet/1/0</value>
                      </key>
                    </keys>
                  </semanticId>
                  <value>
                    <submodelElementCollection>
                      <idShort>RotationSpeedContainer</idShort>
                      <value>
                        <property>
                          <idShort>RotationSpeed</idShort>
                          <supplementalSemanticIds>
                            <reference>
                              <type>ExternalReference</type>
                              <keys>
                                <key>
                                  <type>GlobalReference</type>
                                  <value>rotation</value>
                                </key>
                              </keys>
                            </reference>
                          </supplementalSemanticIds>
                          <embeddedDataSpecifications>
                            <embeddedDataSpecification>
                              <dataSpecification>
                                <type>ExternalReference</type>
                                <keys>
                                  <key>
                                    <type>GlobalReference</type>
                                    <value>rpm</value>
                                  </key>
                                </keys>
                              </dataSpecification>
                            </embeddedDataSpecification>
                          </embeddedDataSpecifications>
                          <valueType>xs:int</valueType>
                          <value>250</value>
                        </property>
                        <multiLanguageProperty>
                          <idShort>PropertyComment</idShort>
                          <value>
                            <langStringTextType>
                              <language>en</language>
                              <text>Rotation speed</text>
                            </langStringTextType>
                          </value>
                        </multiLanguageProperty>
                        <relationshipElement>
                          <idShort>PropertyRealizedByRotationSpeed</idShort>
                          <second>
                            <type>ExternalReference</type>
                            <keys>
                              <key>
                                <type>GlobalReference</type>
                                <value>rotation-speed-runtime-id</value>
                              </key>
                            </keys>
                          </second>
                        </relationshipElement>
                      </value>
                    </submodelElementCollection>
                  </value>
                </submodelElementCollection>
              </value>
            </submodelElementCollection>
          </value>
        </submodelElementCollection>
      </submodelElements>
    </submodel>
  </submodels>
</environment>
"""
        with tempfile.TemporaryDirectory() as temp_dir:
            resource_path = Path(temp_dir) / "resource.xml"
            resource_path.write_text(xml, encoding="utf-8")
            capabilities = parse_capabilities_robust(resource_path)

        self.assertEqual(len(capabilities), 1)
        scalar_property = capabilities[0]["properties"][0]
        self.assertEqual(scalar_property["property_name"], "RotationSpeed")
        self.assertEqual(scalar_property["property_ID"], "rotation")
        self.assertEqual(scalar_property["property_unit"], "rpm")
        self.assertEqual(scalar_property["valueType"], "xs:int")
        self.assertEqual(scalar_property["value0"], "250")
        self.assertEqual(scalar_property["propertyRealizedBy"], "")
        self.assertEqual(scalar_property["property_constraint"], [])
        self.assertTrue(property_value_match(
            _rotation_parameter(), scalar_property
        ))

    def test_parses_expanded_realized_by_references_to_caex_ids(self):
        property_id = "1c777591-d6fb-47ad-af94-af3f73229017"
        capability_id = "ef111e89-8362-41c2-a915-c2dbf2e3b102"
        realized_by_xml = f"""
                <submodelElementCollection>
                  <idShort>PropertySet</idShort>
                  <semanticId>
                    <type>ExternalReference</type>
                    <keys>
                      <key>
                        <type>GlobalReference</type>
                        <value>https://admin-shell.io/idta/CapabilityDescription/PropertySet/1/0</value>
                      </key>
                    </keys>
                  </semanticId>
                  <value>
                    <submodelElementCollection>
                      <idShort>DurationContainer</idShort>
                      <value>
                        <property>
                          <idShort>Duration</idShort>
                          <valueType>xs:int</valueType>
                          <value>10</value>
                        </property>
                        <relationshipElement>
                          <idShort>PropertyRealizedByDuration</idShort>
                          <second>
                            <type>ModelReference</type>
                            <keys>
                              <key>
                                <type>Submodel</type>
                                <value>https://admin-shell.io/idta/SubmodelTemplate/ModuleTypePackage/1/0</value>
                              </key>
                              <key>
                                <type>File</type>
                                <value>MTPFile</value>
                              </key>
                              <key>
                                <type>FragmentReference</type>
                                <value>CAEX@ID=&#x2019;{property_id}&#x2019;</value>
                              </key>
                            </keys>
                          </second>
                        </relationshipElement>
                      </value>
                    </submodelElementCollection>
                  </value>
                </submodelElementCollection>
                <submodelElementCollection>
                  <idShort>CapabilityRelations</idShort>
                  <semanticId>
                    <type>ExternalReference</type>
                    <keys>
                      <key>
                        <type>GlobalReference</type>
                        <value>https://admin-shell.io/idta/CapabilityDescription/CapabilityRelations/1/0</value>
                      </key>
                    </keys>
                  </semanticId>
                  <value>
                    <relationshipElement>
                      <idShort>CapabilityRealizedByStirringPulseDuration</idShort>
                      <semanticId>
                        <type>ExternalReference</type>
                        <keys>
                          <key>
                            <type>GlobalReference</type>
                            <value>https://admin-shell.io/idta/CapabilityDescription/CapabilityRealizedBy/1/0</value>
                          </key>
                        </keys>
                      </semanticId>
                      <second>
                        <type>ModelReference</type>
                        <keys>
                          <key>
                            <type>Submodel</type>
                            <value>https://admin-shell.io/idta/SubmodelTemplate/ModuleTypePackage/1/0</value>
                          </key>
                          <key>
                            <type>File</type>
                            <value>MTPFile</value>
                          </key>
                          <key>
                            <type>FragmentReference</type>
                            <value>CAEX@ID=&#x2019;{capability_id}&#x2019;</value>
                          </key>
                        </keys>
                      </second>
                    </relationshipElement>
                  </value>
                </submodelElementCollection>
"""
        xml = _minimal_capability_xml("StirringPulseDuration").replace(
            "</capability>",
            f"</capability>{realized_by_xml}",
            1,
        )

        plain_reference_xml = xml.replace(
            f"CAEX@ID=&#x2019;{property_id}&#x2019;",
            property_id,
        ).replace(
            f"CAEX@ID=&#x2019;{capability_id}&#x2019;",
            capability_id,
        )

        for source_xml in (xml, plain_reference_xml):
            for parser in (_parse_capability_xml, _parse_capability_aasx):
                capability = parser(source_xml)[0]
                self.assertEqual(
                    capability["properties"][0]["propertyRealizedBy"],
                    property_id,
                )
                self.assertEqual(capability["realized_by"], [capability_id])

        invalid_reference_xml = plain_reference_xml.replace(
            property_id,
            "not-a-property-uuid",
        ).replace(
            capability_id,
            "not-a-capability-uuid",
        )
        capability = _parse_capability_xml(invalid_reference_xml)[0]
        self.assertEqual(capability["properties"][0]["propertyRealizedBy"], "")
        self.assertEqual(capability["realized_by"], [])


class SemanticMatchingTests(unittest.TestCase):
    def test_direct_match_requires_exact_full_supplemental_id(self):
        capability = _semantic_graph_entry(
            "FreelyChosenName",
            semantic_ids=("urn:test#MixingOfLiquids", "urn:test#Alias"),
        )
        _resolve_generalizations([capability])

        self.assertTrue(capability_matching(
            " urn:test#MixingOfLiquids ", capability
        ))
        self.assertTrue(capability_matching("urn:test#Alias", capability))
        self.assertFalse(capability_matching(
            "urn:other#MixingOfLiquids", capability
        ))
        self.assertFalse(capability_matching(
            "urn:test#mixingofliquids", capability
        ))
        self.assertFalse(capability_matching(
            "urn:test#FreelyChosenName", capability
        ))

    def test_idshort_without_supplemental_id_does_not_match(self):
        capability = _semantic_graph_entry("MixingOfLiquids")
        _resolve_generalizations([capability])

        self.assertFalse(capability_matching(
            "urn:test#MixingOfLiquids", capability
        ))

    def test_generalized_capability_inherits_target_semantic_id(self):
        target_path = _capability_reference_path(
            "MixingContainer", "ArbitraryTargetName"
        )
        child = _semantic_graph_entry(
            "StirringDuration", targets=(target_path,)
        )
        target = _semantic_graph_entry(
            "ArbitraryTargetName",
            semantic_ids=("urn:test#MixingOfLiquids",),
            container="MixingContainer",
            assignable=False,
        )
        _resolve_generalizations([child, target])

        self.assertTrue(capability_matching(
            "urn:test#MixingOfLiquids", child
        ))
        self.assertEqual(
            child["generalized_by_semantic_ids"],
            ["urn:test#MixingOfLiquids"],
        )
        self.assertTrue(child["generalization_resolution"][0]["resolved"])

    def test_target_without_supplemental_id_does_not_match(self):
        target_path = _capability_reference_path(
            "MixingContainer", "MixingOfLiquids"
        )
        child = _semantic_graph_entry(
            "StirringDuration", targets=(target_path,)
        )
        target = _semantic_graph_entry(
            "MixingOfLiquids", container="MixingContainer"
        )
        _resolve_generalizations([child, target])

        self.assertFalse(capability_matching(
            "urn:test#MixingOfLiquids", child
        ))
        self.assertEqual(
            child["generalization_resolution"][0]["reason"],
            "target_missing_supplemental_semantic_id",
        )

    def test_transitive_generalization_is_cycle_safe(self):
        middle_path = _capability_reference_path(
            "StirringContainer", "Stirring"
        )
        target_path = _capability_reference_path(
            "MixingContainer", "MixingOfLiquids"
        )
        child = _semantic_graph_entry(
            "StirringDuration", targets=(middle_path,)
        )
        middle = _semantic_graph_entry(
            "Stirring", container="StirringContainer", targets=(target_path,)
        )
        target = _semantic_graph_entry(
            "MixingOfLiquids",
            semantic_ids=("urn:test#MixingOfLiquids",),
            container="MixingContainer",
            targets=(middle_path,),
        )
        _resolve_generalizations([child, middle, target])

        self.assertTrue(capability_matching(
            "urn:test#MixingOfLiquids", child
        ))
        self.assertEqual(
            child["generalized_by_semantic_ids"],
            ["urn:test#MixingOfLiquids"],
        )

    def test_unresolved_target_is_reported_and_does_not_match(self):
        missing_path = _capability_reference_path(
            "MissingContainer", "MissingTarget"
        )
        child = _semantic_graph_entry(
            "StirringDuration", targets=(missing_path,)
        )
        _resolve_generalizations([child])

        self.assertFalse(capability_matching(
            "urn:test#MixingOfLiquids", child
        ))
        self.assertEqual(
            child["generalization_resolution"][0]["reason"],
            "target_not_found",
        )

    def test_duplicate_idshort_is_resolved_by_complete_path(self):
        good_path = _capability_reference_path(
            "GoodContainer", "MixingOfLiquids"
        )
        child = _semantic_graph_entry(
            "StirringDuration", targets=(good_path,)
        )
        good_target = _semantic_graph_entry(
            "MixingOfLiquids",
            semantic_ids=("urn:test#MixingOfLiquids",),
            container="GoodContainer",
        )
        other_target = _semantic_graph_entry(
            "MixingOfLiquids",
            semantic_ids=("urn:other#MixingOfLiquids",),
            container="OtherContainer",
        )
        _resolve_generalizations([child, good_target, other_target])

        self.assertTrue(capability_matching(
            "urn:test#MixingOfLiquids", child
        ))
        self.assertFalse(capability_matching(
            "urn:other#MixingOfLiquids", child
        ))


class PropertyMatchingTests(unittest.TestCase):
    def test_discrete_values_use_constraint_intersection(self):
        parameter = _rotation_parameter()
        self.assertTrue(property_value_match(
            parameter, {"value0": "100", "value1": "150"}
        ))
        self.assertFalse(property_value_match(
            parameter, {"value0": "20", "value1": "400"}
        ))
        self.assertTrue(property_value_match(
            parameter, {"value0": "20", "value1": "100", "value2": "400"}
        ))

    def test_resource_ranges_must_intersect_requested_range(self):
        parameter = _rotation_parameter()
        self.assertFalse(property_value_match(
            parameter, {"valueMin": "0", "valueMax": "40"}
        ))
        self.assertFalse(property_value_match(
            parameter, {"valueMin": "301", "valueMax": "400"}
        ))
        self.assertTrue(property_value_match(
            parameter, {"valueMin": "250", "valueMax": "400"}
        ))


class AssignabilityTests(unittest.TestCase):
    def test_abstract_conveying_halves_eight_combinations_to_four(self):
        recipe = {
            "ID": "Recipe",
            "Description": "Capability combination recipe",
            "Inputs": [],
            "Outputs": [],
            "Intermediates": [],
            "DirectedLinks": [],
            "ProcessElements": [
                {
                    "ID": "MixingOfLiquids001",
                    "Description": "MixingOfLiquids",
                    "Parameters": [
                        _rotation_parameter(),
                        _duration_parameter(),
                    ],
                    "SemanticDescription": "urn:test#MixingOfLiquids",
                },
                {
                    "ID": "Conveying001",
                    "Description": "Conveying",
                    "Parameters": [],
                    "SemanticDescription": "urn:test#Conveying",
                },
            ],
        }
        resources = {
            "resource: HC30": [
                *[
                    _capability(
                        f"MixingVariant{index}",
                        f"urn:test#MixingVariant{index}",
                        f"mixing-operation-{index}",
                    )
                    for index in range(4)
                ],
                {
                    "capability": [{
                        "capability_name": "ConveyingEmpty",
                        "capability_ID": "urn:test#ConveyingEmpty",
                        "semantic_ids": ["urn:test#ConveyingEmpty"],
                        "capability_comment": "",
                    }],
                    "properties": [],
                    "generalized_by": ["Conveying"],
                    "generalized_by_semantic_ids": ["urn:test#Conveying"],
                    "realized_by": ["conveying-empty-operation"],
                    "capability_qualifiers": [],
                    "is_assignable": True,
                },
                {
                    "capability": [{
                        "capability_name": "Conveying",
                        "capability_ID": "urn:test#Conveying",
                        "semantic_ids": ["urn:test#Conveying"],
                        "capability_comment": "",
                    }],
                    "properties": [],
                    "generalized_by": [],
                    "generalized_by_semantic_ids": [],
                    "realized_by": [],
                    "capability_qualifiers": [{
                        "kind": "ValueQualifier",
                        "type": "NotAssigned",
                        "value_type": "xs:boolean",
                        "value": "true",
                        "semantic_ids": ["urn:test#Offered"],
                    }],
                    "is_assignable": False,
                },
            ]
        }

        gui_rows, solutions, debug = run_optimization(
            recipe,
            resources,
            generate_json=True,
            find_all_solutions=True,
        )

        self.assertEqual(len(solutions), 4)
        self.assertEqual(
            {
                assignment["selected_capability"]["name"]
                for solution in solutions
                for assignment in solution["assignments"]
                if assignment["step_id"] == "Conveying001"
            },
            {"ConveyingEmpty"},
        )
        self.assertNotIn(
            "Conveying",
            {
                row["capability_name"]
                for row in gui_rows
                if row.get("capability_name")
            },
        )

        conveying_debug = next(
            entry
            for entry in debug["matching_debug"]
            if entry["step_id"] == "Conveying001"
        )
        abstract_check = next(
            check
            for check in conveying_debug["capability_checks"]
            if check["capability_name"] == "Conveying"
        )
        self.assertEqual(
            abstract_check["assignment_exclusion_reason"],
            "not_assigned",
        )

    def test_not_assigned_capability_is_kept_but_not_selected(self):
        recipe = {
            "ID": "Recipe",
            "Description": "Conveying recipe",
            "Inputs": [],
            "Outputs": [],
            "Intermediates": [],
            "DirectedLinks": [],
            "ProcessElements": [{
                "ID": "Conveying001",
                "Description": "Conveying",
                "Parameters": [],
                "SemanticDescription": "urn:test#Conveying",
            }],
        }
        resources = {
            "resource: HC30": [
                {
                    "capability": [{
                        "capability_name": "ConveyingEmpty",
                        "capability_ID": "urn:test#ConveyingEmpty",
                        "semantic_ids": ["urn:test#ConveyingEmpty"],
                        "capability_comment": "",
                    }],
                    "properties": [],
                    "generalized_by": ["Conveying"],
                    "generalized_by_semantic_ids": ["urn:test#Conveying"],
                    "realized_by": ["conveying-empty-operation"],
                    "capability_qualifiers": [],
                    "is_assignable": True,
                },
                {
                    "capability": [{
                        "capability_name": "Conveying",
                        "capability_ID": "urn:test#Conveying",
                        "semantic_ids": ["urn:test#Conveying"],
                        "capability_comment": "",
                    }],
                    "properties": [],
                    "generalized_by": [],
                    "generalized_by_semantic_ids": [],
                    "realized_by": [],
                    "capability_qualifiers": [{
                        "kind": "ValueQualifier",
                        "type": "NotAssigned",
                        "value_type": "xs:boolean",
                        "value": "true",
                        "semantic_ids": ["urn:test#Offered"],
                    }],
                    "is_assignable": False,
                },
            ]
        }

        gui_rows, solutions, debug = run_optimization(
            recipe,
            resources,
            generate_json=True,
            find_all_solutions=True,
        )

        self.assertEqual(len(resources["resource: HC30"]), 2)
        self.assertEqual(len(solutions), 1)
        self.assertEqual(
            solutions[0]["assignments"][0]["selected_capability"]["name"],
            "ConveyingEmpty",
        )
        self.assertEqual(gui_rows[0]["capability_name"], "ConveyingEmpty")

        checks = debug["matching_debug"][0]["capability_checks"]
        conveying_check = next(
            check
            for check in checks
            if check["capability_name"] == "Conveying"
        )
        self.assertFalse(conveying_check["is_assignable"])
        self.assertEqual(
            conveying_check["assignment_exclusion_reason"],
            "not_assigned",
        )
        self.assertTrue(conveying_check["semantic_match"])
        self.assertEqual(
            debug["matching_debug"][0]["matched_capabilities"],
            ["ConveyingEmpty"],
        )


class MaterialFlowSemanticTests(unittest.TestCase):
    @staticmethod
    def _capability(name, semantic_ids, generalized_ids=()):
        semantic_ids = list(semantic_ids)
        return {
            "capability": [{
                "capability_name": name,
                "capability_ID": semantic_ids[0] if semantic_ids else "",
                "semantic_ids": semantic_ids,
                "capability_comment": "",
            }],
            "properties": [],
            "generalized_by": [],
            "generalized_by_semantic_ids": list(generalized_ids),
            "generalization_resolution": [],
            "realized_by": [f"{name}-operation"],
            "capability_qualifiers": [],
            "is_assignable": True,
        }

    def test_dosing_semantics_allow_material_transfer_between_resources(self):
        recipe = {
            "ID": "Recipe",
            "Description": "Cross-resource material-flow recipe",
            "Inputs": [{"ID": "Input"}],
            "Outputs": [{"ID": "Product"}],
            "Intermediates": [{"ID": "Mixed"}, {"ID": "Dosed"}],
            "DirectedLinks": [
                {"FromID": "Input", "ToID": "Mixing"},
                {"FromID": "Mixing", "ToID": "Mixed"},
                {"FromID": "Mixed", "ToID": "Dosing"},
                {"FromID": "Dosing", "ToID": "Dosed"},
                {"FromID": "Dosed", "ToID": "Heating"},
                {"FromID": "Heating", "ToID": "Product"},
            ],
            "ProcessElements": [
                {
                    "ID": "Mixing",
                    "Description": "Mixing",
                    "Parameters": [],
                    "SemanticDescription": "urn:test#Mixing",
                },
                {
                    "ID": "Dosing",
                    "Description": "Dosing",
                    "Parameters": [],
                    "SemanticDescription": "urn:test#Dosing",
                },
                {
                    "ID": "Heating",
                    "Description": "Heating",
                    "Parameters": [],
                    "SemanticDescription": "urn:test#Heating",
                },
            ],
        }

        dosing_variants = (
            self._capability("DirectDosingVariant", ["urn:test#Dosing"]),
            self._capability(
                "DosingFlow",
                ["urn:test#DosingFlow"],
                ["urn:test#Dosing"],
            ),
        )
        for dosing_capability in dosing_variants:
            with self.subTest(
                capability=dosing_capability["capability"][0]["capability_name"]
            ):
                resources = {
                    "resource: HC20": [
                        self._capability("Mixer", ["urn:test#Mixing"]),
                        dosing_capability,
                    ],
                    "resource: HC10": [
                        self._capability("Heater", ["urn:test#Heating"]),
                    ],
                }

                _, solutions, _ = run_optimization(
                    recipe,
                    resources,
                    generate_json=True,
                    find_all_solutions=True,
                )

                self.assertEqual(len(solutions), 1)
                assignments = {
                    assignment["step_id"]: assignment["resource"]
                    for assignment in solutions[0]["assignments"]
                }
                self.assertEqual(assignments["Mixing"], "resource: HC20")
                self.assertEqual(assignments["Dosing"], "resource: HC20")
                self.assertEqual(assignments["Heating"], "resource: HC10")


class CapabilityVariantTests(unittest.TestCase):
    def setUp(self):
        self.recipe = {
            "ID": "Recipe",
            "Description": "Test recipe",
            "Inputs": [],
            "Outputs": [],
            "Intermediates": [],
            "DirectedLinks": [],
            "ProcessElements": [{
                "ID": "MixingOfLiquids001",
                "Description": "MixingOfLiquids",
                "Parameters": [_rotation_parameter(), _duration_parameter()],
                "SemanticDescription": "urn:test#MixingOfLiquids",
            }],
        }
        self.resource_name = "resource: HC10"
        self.resources = {
            self.resource_name: [
                _capability(
                    "StirringDuration",
                    "urn:test#StirringDuration",
                    "stirring-duration-operation",
                ),
                _capability(
                    "StirringPulseDuration",
                    "urn:test#StirringPulseDuration",
                    "stirring-pulse-duration-operation",
                ),
            ]
        }

    def test_missing_generalization_target_id_excludes_resource(self):
        hc10_capabilities = copy.deepcopy(
            self.resources[self.resource_name]
        )
        hc20_capabilities = copy.deepcopy(hc10_capabilities)
        for capability in hc20_capabilities:
            capability["generalized_by_semantic_ids"] = []
            capability["generalization_resolution"] = [{
                "target_reference": [],
                "resolved": True,
                "target_capability": "MixingOfLiquids",
                "semantic_ids": [],
                "reason": "target_missing_supplemental_semantic_id",
            }]

        _, solutions, debug = run_optimization(
            self.recipe,
            {
                "resource: HC10": hc10_capabilities,
                "resource: HC20": hc20_capabilities,
            },
            generate_json=True,
            find_all_solutions=True,
        )

        self.assertEqual(len(solutions), 2)
        self.assertTrue(all(
            assignment["resource"] == "resource: HC10"
            for solution in solutions
            for assignment in solution["assignments"]
        ))
        hc20_debug = next(
            entry for entry in debug["matching_debug"]
            if entry["resource"] == "resource: HC20"
        )
        self.assertEqual(hc20_debug["matched_capabilities"], [])
        self.assertTrue(all(
            not check["semantic_match"]
            for check in hc20_debug["capability_checks"]
        ))

    def test_solver_returns_one_solution_per_capability(self):
        gui_rows, solutions, _ = run_optimization(
            self.recipe,
            self.resources,
            generate_json=True,
            find_all_solutions=True,
        )

        self.assertEqual(len(solutions), 2)
        selected_names = {
            solution["assignments"][0]["selected_capability"]["name"]
            for solution in solutions
        }
        self.assertEqual(
            selected_names,
            {"StirringDuration", "StirringPulseDuration"},
        )
        self.assertTrue(all(
            len(solution["assignments"][0]["capabilities"]) == 1
            for solution in solutions
        ))

        result_texts = [row["capabilities"] for row in gui_rows if row]
        self.assertTrue(all(
            "RotationSpeed: {100, 150} [rpm]" in text
            for text in result_texts
        ))
        self.assertTrue(all(
            "StirringDuration: 0 -> inf [second]" in text
            for text in result_texts
        ))
        self.assertTrue(all(
            ">=50" not in text and "<=300" not in text
            for text in result_texts
        ))
        pulse_text = next(
            row["capabilities"]
            for row in gui_rows
            if row and row["capability_name"] == "StirringPulseDuration"
        )
        self.assertIn("    CycleTime: 1 -> 20 [second]", pulse_text)
        self.assertIn("    DutyCycle: 0 -> 100 [percent]", pulse_text)

        required_texts = [row["required_capability"] for row in gui_rows if row]
        self.assertTrue(all(
            text == (
                "MixingOfLiquids\n"
                "    RotationSpeed001: >=50 & <=300 [rpm]\n"
                "    MixingDuration001: 15 [second]"
            )
            for text in required_texts
        ))

    def test_offered_formatter_uses_property_names_values_and_units(self):
        parameter = _rotation_parameter()
        prop = self.resources[self.resource_name][0]["properties"][0]
        text = format_capability_string([
            ("StirringDuration", [(parameter, prop)])
        ])
        self.assertEqual(
            text,
            "StirringDuration\n"
            "    RotationSpeed: {100, 150} [rpm]",
        )

    def test_required_formatter_uses_parameter_ids_constraints_and_units(self):
        text = format_required_capability(self.recipe["ProcessElements"][0])
        self.assertEqual(
            text,
            "MixingOfLiquids\n"
            "    RotationSpeed001: >=50 & <=300 [rpm]\n"
            "    MixingDuration001: 15 [second]",
        )

    def test_formatters_use_local_names_for_uri_units(self):
        step = copy.deepcopy(self.recipe["ProcessElements"][0])
        rotation_unit = "http://qudt.org/vocab/unit/REV-PER-MIN"
        duration_unit = "http://si-digital-framework.org/SI/units/second"
        for value in step["Parameters"][0]["Values"]:
            value["UnitOfMeasure"] = rotation_unit
        step["Parameters"][0]["UnitOfMeasure"] = rotation_unit
        step["Parameters"][1]["Values"][0]["UnitOfMeasure"] = duration_unit
        step["Parameters"][1]["UnitOfMeasure"] = duration_unit

        required_text = format_required_capability(step)
        self.assertIn(
            "    RotationSpeed001: >=50 & <=300 [REV-PER-MIN]",
            required_text,
        )
        self.assertIn(
            "    MixingDuration001: 15 [second]",
            required_text,
        )

        prop = copy.deepcopy(self.resources[self.resource_name][0]["properties"][0])
        prop["property_unit"] = rotation_unit
        offered_text = format_capability_string([
            ("StirringDuration", [(step["Parameters"][0], prop)])
        ])
        self.assertEqual(
            offered_text,
            "StirringDuration\n"
            "    RotationSpeed: {100, 150} [REV-PER-MIN]",
        )

    def test_solution_export_includes_all_generalized_capability_ids(self):
        resources = copy.deepcopy(self.resources)
        for capability in resources[self.resource_name]:
            capability["generalized_by_semantic_ids"] = [
                "urn:test#MixingOfLiquids",
                "urn:test#MixingOfLiquids",
                "urn:test#AdditionalMixing",
            ]

        _, solutions, _ = run_optimization(
            self.recipe,
            resources,
            generate_json=True,
            find_all_solutions=True,
        )

        self.assertTrue(solutions)
        for solution in solutions:
            generalized_ids = solution["assignments"][0][
                "capability_details"
            ][0]["capability_generalized_by_id"]
            self.assertEqual(
                generalized_ids,
                [
                    "urn:test#MixingOfLiquids",
                    "urn:test#AdditionalMixing",
                ],
            )

    def test_direct_capability_exports_empty_generalized_capability_ids(self):
        recipe = copy.deepcopy(self.recipe)
        recipe["ProcessElements"][0]["SemanticDescription"] = "urn:test#Dosing"
        recipe["ProcessElements"][0]["Parameters"] = []
        capability = _capability(
            "Dosing",
            "urn:test#Dosing",
            "dosing-operation",
        )
        capability["generalized_by"] = []
        capability["generalized_by_semantic_ids"] = []

        _, solutions, _ = run_optimization(
            recipe,
            {self.resource_name: [capability]},
            generate_json=True,
            find_all_solutions=True,
        )

        self.assertEqual(len(solutions), 1)
        self.assertEqual(
            solutions[0]["assignments"][0]["capability_details"][0][
                "capability_generalized_by_id"
            ],
            [],
        )

    def test_weighted_sorting_is_stable_for_equal_resource_costs(self):
        optimizer = SolutionOptimizer()
        optimizer.resource_costs = {
            "HC10": {
                "EnergyCost": 1.0,
                "UseCost": 2.0,
                "CO2Footprint": 3.0,
            }
        }
        solutions = [
            {"solution_id": 2, "assignments": [{"resource": self.resource_name}]},
            {"solution_id": 1, "assignments": [{"resource": self.resource_name}]},
        ]
        ranked = optimizer.optimize_solutions_from_memory(solutions)
        self.assertEqual([item["solution_id"] for item in ranked], [1, 2])

    def test_export_uses_selected_capability_and_omits_matching_only_parameter(self):
        _, solutions, _ = run_optimization(
            self.recipe,
            self.resources,
            generate_json=True,
            find_all_solutions=True,
        )
        logs = []
        namespace = {"b2mml": B2MML_NS}

        for solution in solutions:
            assignment = solution["assignments"][0]
            selected = assignment["selected_capability"]
            self.assertEqual(
                assignment["required_capability_semantic_id"],
                self.recipe["ProcessElements"][0]["SemanticDescription"],
            )
            matched_properties = {
                prop["required_parameter_id"]: prop
                for detail in assignment["capability_details"]
                for prop in detail["matched_properties"]
            }
            self.assertEqual(
                assignment["capability_details"][0][
                    "capability_generalized_by_id"
                ],
                ["urn:test#MixingOfLiquids"],
            )
            self.assertEqual(
                matched_properties["RotationSpeed001"][
                    "required_parameter_semantic_id"
                ],
                "rotation",
            )
            xml = generate_b2mml_master_recipe(
                resources_data=self.resources,
                solutions_data_list={"plant_configurations": solutions},
                general_recipe_data=copy.deepcopy(self.recipe),
                selected_solution_id=solution["solution_id"],
                output_path=None,
                log_callback=logs.append,
            )
            root = ET.fromstring(xml)

            recipe_element_ids = [
                element.text
                for element in root.findall(".//b2mml:RecipeElement/b2mml:ID", namespace)
            ]
            self.assertTrue(any(
                selected["realized_by"][0] in value
                for value in recipe_element_ids
                if value
            ))

            parameter_descriptions = [
                element.text
                for element in root.findall(
                    ".//b2mml:Formula/b2mml:Parameter/b2mml:Description",
                    namespace,
                )
            ]
            self.assertFalse(any(
                "Rotation_speed_requirement" in value
                for value in parameter_descriptions
                if value
            ))
            self.assertTrue(any(
                "Mixing_duration" in value
                for value in parameter_descriptions
                if value
            ))

        rotation_logs = [
            message for message in logs if "RotationSpeed001" in message
        ]
        self.assertEqual(len(rotation_logs), 2)
        self.assertTrue(all(message.startswith("Info:") for message in rotation_logs))


if __name__ == "__main__":
    unittest.main()
