import os
import sys
from typing import Dict, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QSizePolicy

from qfluentwidgets import (
    CardWidget,
    IconWidget,
    SubtitleLabel,
    BodyLabel,
    PushButton,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
)

from Code.Transformator.MasterRecipeValidator import (
    validate_master_recipe_xml,
    validate_master_recipe_parameters,
)

try:
    from Code.SMT4ModPlant.AASxmlCapabilityParser import parse_capabilities_robust
except Exception:
    parse_capabilities_robust = None


class RecipeValidatorPage(QWidget):
    """Standalone page for recipe-level validation tools."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("recipe_validator_page")
        self.context_data: Optional[Dict] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        self.title = SubtitleLabel("Recipe Validator", self)
        layout.addWidget(self.title)

        # Card 1: XSD validation
        xsd_card = CardWidget(self)
        xsd_row = QHBoxLayout(xsd_card)
        xsd_row.setContentsMargins(20, 20, 20, 20)
        xsd_row.setSpacing(14)
        xsd_row.addWidget(IconWidget(FluentIcon.DOCUMENT, self))
        xsd_text = QVBoxLayout()
        xsd_title = SubtitleLabel("Validate Master Recipe", self)
        xsd_desc = BodyLabel("Check Master Recipe XML against selected XSD schema folder.", self)
        xsd_desc.setStyleSheet("color: #8A8A8A;")
        xsd_text.addWidget(xsd_title)
        xsd_text.addWidget(xsd_desc)
        xsd_row.addLayout(xsd_text, 1)
        self.btn_validate = PushButton("Run XSD Validation", self)
        self.btn_validate.setFixedHeight(34)
        self.btn_validate.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_validate.clicked.connect(self.validate_master_recipe)
        xsd_row.addWidget(self.btn_validate)
        layout.addWidget(xsd_card)

        # Card 2: Parameter validation
        param_card = CardWidget(self)
        param_row = QHBoxLayout(param_card)
        param_row.setContentsMargins(20, 20, 20, 20)
        param_row.setSpacing(14)
        param_row.addWidget(IconWidget(FluentIcon.ACCEPT, self))
        param_text = QVBoxLayout()
        param_title = SubtitleLabel("Parameter Validierung", self)
        param_desc = BodyLabel("Validate XML parameter IDs against parsed AAS capabilities.", self)
        param_desc.setStyleSheet("color: #8A8A8A;")
        param_text.addWidget(param_title)
        param_text.addWidget(param_desc)
        param_row.addLayout(param_text, 1)
        self.btn_param_validate = PushButton("Run Parameter Validation", self)
        self.btn_param_validate.setFixedHeight(34)
        self.btn_param_validate.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.btn_param_validate.clicked.connect(self.validate_parameters)
        param_row.addWidget(self.btn_param_validate)
        layout.addWidget(param_card)

        # Result status area (replaces in-page validation log)
        status_card = CardWidget(self)
        status_layout = QHBoxLayout(status_card)
        status_layout.setContentsMargins(20, 16, 20, 16)
        status_layout.setSpacing(10)
        self.status_dot = BodyLabel("●", self)
        self.status_dot.setStyleSheet("color: #8A8A8A; font-size: 18px;")
        self.status_text = SubtitleLabel("No Validation Run Yet", self)
        self.status_text.setWordWrap(True)
        status_layout.addWidget(self.status_dot, 0, Qt.AlignmentFlag.AlignVCenter)
        status_layout.addWidget(self.status_text, 1)
        layout.addWidget(status_card)
        layout.addStretch(1)

    def set_context_data(self, context_data: Optional[Dict]):
        """Receive latest calculation context from Home page."""
        self.context_data = context_data if isinstance(context_data, dict) else None

    @staticmethod
    def _default_user_dir() -> str:
        downloads = os.path.normpath(os.path.join(os.path.expanduser("~"), "Downloads"))
        return downloads if os.path.isdir(downloads) else os.path.expanduser("~")

    @staticmethod
    def _program_dir() -> str:
        program_path = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else os.getcwd()
        return os.path.dirname(program_path)

    @staticmethod
    def _dialog_options():
        options = QFileDialog.Option(0)
        if os.name != "nt":
            options |= QFileDialog.Option.DontUseNativeDialog
        return options

    def _open_file_dialog(self, title: str, start_dir: str, name_filter: str):
        dialog = QFileDialog(self)
        dialog.setWindowTitle(title)
        dialog.setDirectory(start_dir)
        dialog.setNameFilter(name_filter)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dialog.setOptions(self._dialog_options())
        if dialog.exec():
            files = dialog.selectedFiles()
            if files:
                return files[0]
        return ""

    def _open_directory_dialog(self, title: str, start_dir: str):
        dialog = QFileDialog(self)
        dialog.setWindowTitle(title)
        dialog.setDirectory(start_dir)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        if os.name != "nt":
            dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        if dialog.exec():
            dirs = dialog.selectedFiles()
            if dirs:
                return dirs[0]
        return ""

    def _set_status(self, ok: bool, text: str):
        color = "#107C10" if ok else "#D13438"
        self.status_dot.setStyleSheet(f"color: {color}; font-size: 18px;")
        self.status_text.setText(text)

    def validate_master_recipe(self):
        main = self.window()
        start_dir = self._default_user_dir()
        if hasattr(main, "settings_page"):
            try:
                d = main.settings_page.get_export_path()
                if d and os.path.isdir(d):
                    start_dir = d
            except Exception:
                pass

        xml_path = self._open_file_dialog(
            title="Validate Master Recipe - Step 1/2: Select Master Recipe XML",
            start_dir=start_dir,
            name_filter="XML Files (*.xml);;All Files (*)",
        )
        if not xml_path:
            return

        schema_dir = self._open_directory_dialog(
            title="Validate Master Recipe - Step 2/2: Select XSD Schema Folder",
            start_dir=self._program_dir(),
        )
        if not schema_dir:
            return
        if not any(name.lower().endswith(".xsd") for name in os.listdir(schema_dir)):
            InfoBar.error(
                title="Validation Error",
                content="Selected folder does not contain any .xsd files.",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=6000,
                parent=self.window(),
            )
            return

        try:
            ok, errors, used_root = validate_master_recipe_xml(xml_path, schema_dir, root_xsd_path=None)

            if ok:
                self._set_status(True, f"Validate Master Recipe Passed (Root XSD: {os.path.basename(used_root or '')})")
                InfoBar.success(
                    title="Validation Passed",
                    content=f"XML conforms to XSD (root: {os.path.basename(used_root or '')})",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=6000,
                    parent=self.window(),
                )
                return

            preview = " | ".join(errors[:2])
            more = "" if len(errors) <= 2 else f" (+{len(errors) - 2} more)"
            self._set_status(False, f"Validate Master Recipe failed: {preview}{more}")
            InfoBar.error(
                title="Validation Failed",
                content=f"{preview}{more}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                duration=8000,
                parent=self.window(),
            )
        except Exception as e:
            self._set_status(False, f"Validate Master Recipe error: {e}")
            InfoBar.error(
                title="Validation Error",
                content=str(e),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self.window(),
            )

    def validate_parameters(self):
        main = self.window()
        start_dir = self._default_user_dir()
        if hasattr(main, "settings_page"):
            try:
                d = main.settings_page.get_export_path()
                if d and os.path.isdir(d):
                    start_dir = d
            except Exception:
                pass

        def _has_usable_resources(data) -> bool:
            if not isinstance(data, dict) or not data:
                return False
            for v in data.values():
                if isinstance(v, list) and len(v) > 0:
                    return True
                if isinstance(v, dict) and len(v) > 0:
                    return True
            return False

        resources_data = None
        if isinstance(self.context_data, dict) and "resources" in self.context_data:
            resources_data = self.context_data.get("resources")
        has_cached_resources = _has_usable_resources(resources_data)

        xml_dialog_title = (
            "Parameter Validation: Select Master Recipe XML"
            if has_cached_resources
            else "Parameter Validation - Step 1/2: Select Master Recipe XML"
        )
        xml_path = self._open_file_dialog(
            title=xml_dialog_title,
            start_dir=start_dir,
            name_filter="XML Files (*.xml);;All Files (*)",
        )
        if not xml_path:
            return

        if not has_cached_resources:
            if parse_capabilities_robust is None:
                InfoBar.error(
                    title="Parameter Validation Error",
                    content="AAS parser (parse_capabilities_robust) not available in this build.",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    parent=self.window(),
                )
                return

            resource_dir = self._open_directory_dialog(
                title="Parameter Validation - Step 2/2: Select Resource Folder (AAS XML/AASX/JSON)",
                start_dir=self._program_dir(),
            )
            if not resource_dir:
                return
            if not any(name.lower().endswith((".xml", ".aasx", ".json")) for name in os.listdir(resource_dir)):
                InfoBar.error(
                    title="Parameter Validation Error",
                    content="Selected folder does not contain any .xml, .aasx, or .json files.",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=6000,
                    parent=self.window(),
                )
                return

            resources_data = {}
            try:
                for fn in os.listdir(resource_dir):
                    if not fn.lower().endswith((".xml", ".aasx", ".json")):
                        continue
                    full = os.path.join(resource_dir, fn)
                    res_name = os.path.splitext(fn)[0]
                    try:
                        caps = parse_capabilities_robust(full)
                        if caps:
                            resources_data[f"resource: {res_name}"] = caps
                    except Exception as pe:
                        pass
            except Exception as e:
                InfoBar.error(
                    title="Resource Parsing Failed",
                    content=str(e),
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    parent=self.window(),
                )
                return
            if not _has_usable_resources(resources_data):
                InfoBar.error(
                    title="Parameter Validation Error",
                    content="No valid resource capabilities could be parsed from selected folder.",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=7000,
                    parent=self.window(),
                )
                return

        try:
            ok, errors, warnings, checked, details = validate_master_recipe_parameters(xml_path, resources_data)

            if ok:
                self._set_status(True, f"Parameter Validierung passed: all {checked} parameters matched.")
                InfoBar.success(
                    title="Parameter Validation Passed",
                    content=f"All {checked} parameters matched parsed AAS capabilities.",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=6000,
                    parent=self.window(),
                )
            else:
                preview = " | ".join(errors[:2])
                more = "" if len(errors) <= 2 else f" (+{len(errors) - 2} more)"
                self._set_status(False, f"Parameter Validierung failed: {preview}{more}")
                InfoBar.error(
                    title="Parameter Validation Failed",
                    content=f"{preview}{more}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP_RIGHT,
                    duration=9000,
                    parent=self.window(),
                )
        except Exception as e:
            self._set_status(False, f"Parameter Validierung error: {e}")
            InfoBar.error(
                title="Parameter Validation Error",
                content=str(e),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP_RIGHT,
                parent=self.window(),
            )
