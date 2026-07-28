# Code/GUI/Logs.py
import json
from datetime import datetime
from typing import Any, Dict, Optional
from xml.etree import ElementTree as ET

from PyQt6.QtCore import QPointF, QRectF, QSignalBlocker, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPen, QPolygonF, QTextCursor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QStackedWidget,
    QTextEdit,
    QTreeWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon as FIF,
    SmoothScrollArea,
    StrongBodyLabel,
    TreeWidget,
    TextEdit,
    SubtitleLabel,
    CaptionLabel,
    ToolTipFilter,
    ToolTipPosition,
)

MAX_DEBUG_TEXT_LENGTH = 250_000
MAX_EXECUTION_LOG_LENGTH = 120_000

VIEW_ITEMS = [
    ("log_execution", "Execution Log", FIF.DOCUMENT),
    ("log_parsed_recipe", "parsed_recipe", FIF.BOOK_SHELF),
    ("log_parsed_resources", "parsed_resources", FIF.FOLDER),
    ("log_smt_model", "SMT2-Modell", FIF.CODE),
    ("log_master_recipe", "Master Recipe", FIF.ALBUM),
    ("log_flow", "Flow Diagram", FIF.IOT),
    ("log_matching_debug", "Matching Debug", FIF.FILTER),
]


class MetricCard(CardWidget):
    """Small summary card used in the debug dashboard header."""

    def __init__(self, label: str, accent: str, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(88)
        self.setStyleSheet(
            f"""
            CardWidget {{
                background-color: rgba(255, 255, 255, 0.035);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)

        self.label = CaptionLabel(label, self)
        self.label.setStyleSheet("color: #9BA7B4; font-size: 12px;")
        self.value = SubtitleLabel("--", self)
        self.value.setStyleSheet(f"color: {accent}; font-size: 18px; font-weight: 700;")

        layout.addWidget(self.label)
        layout.addWidget(self.value)

    def set_value(self, value: str):
        self.value.setText(value)


class StructuredLogView(QWidget):
    """Read-only tree inspector for structured JSON/XML payloads with text fallback."""

    MAX_TREE_ITEMS = 9000
    MAX_DISPLAY_VALUE_LENGTH = 160

    def __init__(self, mono_font: QFont, parent=None):
        super().__init__(parent)
        self._mono_font = mono_font
        self._tree_items_added = 0
        self._tree_truncated = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.stack = QStackedWidget(self)

        self.tree = TreeWidget(self)
        self.tree.setObjectName("structuredLogTree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Field", "Value"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(14)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemsExpandable(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setColumnWidth(0, 190)

        compact_font = QFont(self.font())
        compact_font.setPointSizeF(9.5)
        self.tree.setFont(compact_font)

        header_font = QFont(compact_font)
        header_font.setBold(True)
        header_font.setPointSizeF(9.0)
        self.tree.header().setFont(header_font)
        self.tree.setStyleSheet(
            """
            TreeWidget#structuredLogTree, QTreeWidget#structuredLogTree {
                background-color: rgba(255, 255, 255, 0.025);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
                color: #E7ECF2;
                padding: 4px;
                alternate-background-color: rgba(255, 255, 255, 0.02);
                selection-background-color: rgba(74, 163, 255, 0.18);
            }
            TreeWidget#structuredLogTree::item, QTreeWidget#structuredLogTree::item {
                min-height: 22px;
                padding: 1px 4px;
                border-radius: 6px;
            }
            TreeWidget#structuredLogTree::item:hover, QTreeWidget#structuredLogTree::item:hover {
                background-color: rgba(255, 255, 255, 0.05);
            }
            QHeaderView::section {
                background-color: rgba(255, 255, 255, 0.045);
                color: #96AEC8;
                border: none;
                border-bottom: 1px solid rgba(255, 255, 255, 0.08);
                padding: 5px 8px;
                font-size: 10px;
                font-weight: 700;
            }
            """
        )

        self.text_view = TextEdit(self)
        self.text_view.setReadOnly(True)
        self.text_view.setFont(self._mono_font)
        self.text_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_view.setStyleSheet(
            """
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.025);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
                padding: 10px 12px;
                color: #E7ECF2;
                selection-background-color: rgba(74, 163, 255, 0.35);
            }
            """
        )

        self.stack.addWidget(self.tree)
        self.stack.addWidget(self.text_view)
        layout.addWidget(self.stack)

    @staticmethod
    def _placeholder(title: str, body: str) -> str:
        return f"{title}\n{'=' * len(title)}\n\n{body}"

    @staticmethod
    def _looks_like_json(text: str) -> bool:
        stripped = (text or "").lstrip()
        return stripped.startswith("{") or stripped.startswith("[")

    @staticmethod
    def _looks_like_xml(text: str) -> bool:
        stripped = (text or "").lstrip()
        return stripped.startswith("<")

    def _clear_tree(self):
        self.tree.clear()
        self._tree_items_added = 0
        self._tree_truncated = False

    def _show_tree(self):
        self.stack.setCurrentWidget(self.tree)
        self.tree.expandAll()

    def _show_text(self, text: str):
        limited_text = text or ""
        if len(limited_text) > MAX_DEBUG_TEXT_LENGTH:
            hidden = len(limited_text) - MAX_DEBUG_TEXT_LENGTH
            limited_text = (
                limited_text[:MAX_DEBUG_TEXT_LENGTH]
                + f"\n\n[Truncated in UI]\nThis fallback text view was shortened by {hidden} characters."
            )
        self.text_view.setPlainText(limited_text)
        self.stack.setCurrentWidget(self.text_view)

    @classmethod
    def _summary_for_node(cls, data: Any) -> str:
        if isinstance(data, dict):
            size = len(data)
            return f"Object · {size} field(s)"
        if isinstance(data, list):
            size = len(data)
            return f"Array · {size} item(s)"
        if data is None:
            return "null"

        text = str(data)
        if len(text) > cls.MAX_DISPLAY_VALUE_LENGTH:
            return text[: cls.MAX_DISPLAY_VALUE_LENGTH - 1] + "…"
        return text

    def _make_item(self, label: str, value: str = "", dimmed: bool = False) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label, value])
        tooltip = label if not value else f"{label}\n{value}"
        item.setToolTip(0, tooltip)
        item.setToolTip(1, value or label)

        if dimmed:
            dim_color = QColor("#8EA1B4")
            item.setForeground(0, dim_color)
            item.setForeground(1, dim_color)

        self._tree_items_added += 1
        return item

    def _append_truncation_hint(self, parent_item: QTreeWidgetItem):
        if self._tree_truncated:
            return

        parent_item.addChild(
            self._make_item(
                "… truncated",
                "The structured preview was shortened to keep the UI responsive.",
                dimmed=True,
            )
        )
        self._tree_truncated = True

    def _populate_json_item(self, parent_item: QTreeWidgetItem, data: Any):
        if self._tree_truncated:
            return

        if self._tree_items_added >= self.MAX_TREE_ITEMS:
            self._append_truncation_hint(parent_item)
            return

        if isinstance(data, dict):
            for key, value in data.items():
                if self._tree_truncated:
                    break
                if self._tree_items_added >= self.MAX_TREE_ITEMS:
                    self._append_truncation_hint(parent_item)
                    break
                child = self._make_item(str(key), self._summary_for_node(value))
                parent_item.addChild(child)
                if isinstance(value, (dict, list)):
                    self._populate_json_item(child, value)
        elif isinstance(data, list):
            for index, value in enumerate(data):
                if self._tree_truncated:
                    break
                if self._tree_items_added >= self.MAX_TREE_ITEMS:
                    self._append_truncation_hint(parent_item)
                    break
                child = self._make_item(f"[{index}]", self._summary_for_node(value))
                parent_item.addChild(child)
                if isinstance(value, (dict, list)):
                    self._populate_json_item(child, value)

    def _set_json_tree(self, data: Any, title: str):
        self._clear_tree()
        root = self._make_item(title, self._summary_for_node(data))
        self.tree.addTopLevelItem(root)

        if isinstance(data, (dict, list)):
            self._populate_json_item(root, data)

        self._show_tree()

    def _populate_xml_item(self, parent_item: QTreeWidgetItem, element: ET.Element):
        if self._tree_truncated:
            return

        if self._tree_items_added >= self.MAX_TREE_ITEMS:
            self._append_truncation_hint(parent_item)
            return

        if element.attrib:
            attributes_item = self._make_item("@attributes", f"{len(element.attrib)} attribute(s)", dimmed=True)
            parent_item.addChild(attributes_item)
            for name, value in element.attrib.items():
                if self._tree_truncated:
                    break
                if self._tree_items_added >= self.MAX_TREE_ITEMS:
                    self._append_truncation_hint(attributes_item)
                    break
                attributes_item.addChild(self._make_item(name, str(value)))

        text = (element.text or "").strip()
        children = list(element)
        has_attributes = bool(element.attrib)
        show_text_child = bool(text) and (has_attributes or bool(children))

        if show_text_child and not self._tree_truncated:
            if self._tree_items_added >= self.MAX_TREE_ITEMS:
                self._append_truncation_hint(parent_item)
                return
            parent_item.addChild(self._make_item("#text", self._summary_for_node(text), dimmed=True))

        for child_element in children:
            if self._tree_truncated:
                break
            if self._tree_items_added >= self.MAX_TREE_ITEMS:
                self._append_truncation_hint(parent_item)
                break
            summary_parts = []
            child_text = (child_element.text or "").strip()
            if child_element.attrib:
                summary_parts.append(f"{len(child_element.attrib)} attr")
            if list(child_element):
                summary_parts.append(f"{len(list(child_element))} child")
            elif child_text:
                summary_parts.append(self._summary_for_node(child_text))

            summary = " · ".join(summary_parts)
            child_item = self._make_item(f"<{child_element.tag}>", summary)
            parent_item.addChild(child_item)
            self._populate_xml_item(child_item, child_element)

    def _set_xml_tree(self, xml_text: str, title: str):
        self._clear_tree()
        root_element = ET.fromstring(xml_text)
        summary = f"Element · <{root_element.tag}>"
        root = self._make_item(title, summary)
        self.tree.addTopLevelItem(root)
        root_item = self._make_item(f"<{root_element.tag}>", f"{len(list(root_element))} child node(s)")
        root.addChild(root_item)
        self._populate_xml_item(root_item, root_element)
        self._show_tree()

    def set_placeholder(self, title: str, body: str):
        self._clear_tree()
        self._show_text(self._placeholder(title, body))

    def set_text(self, text: str):
        self._clear_tree()
        self._show_text(text)

    def set_structured_content(self, content: Any, title: str, format_hint: str = ""):
        hint = (format_hint or "").lower()

        try:
            if hint == "json":
                if isinstance(content, str):
                    self._set_json_tree(json.loads(content), title)
                    return
                self._set_json_tree(content, title)
                return

            if hint == "xml":
                if isinstance(content, str):
                    self._set_xml_tree(content, title)
                    return
                self._show_text(self._placeholder(title, "The XML preview is not available as text."))
                return

            if isinstance(content, (dict, list)):
                self._set_json_tree(content, title)
                return

            if isinstance(content, str):
                if self._looks_like_json(content):
                    self._set_json_tree(json.loads(content), title)
                    return
                if self._looks_like_xml(content):
                    self._set_xml_tree(content, title)
                    return
                self._show_text(content)
                return

            self._show_text(str(content))
        except (json.JSONDecodeError, ET.ParseError, TypeError, ValueError):
            fallback_text = str(content) if content is not None else self._placeholder(title, "No data available.")
            self._show_text(fallback_text)


class FlowStepConnector(QWidget):
    """Horizontal connector used inside one snake row."""

    WIDTH = 86
    HEIGHT = 42

    def __init__(self, direction: str, color: str, transition_text: str = "", parent=None):
        super().__init__(parent)
        self.direction = direction
        self.color = QColor(color)
        self.transition_text = str(transition_text or "").strip()
        self._font = QFont()
        self._font.setPointSize(9)
        self._font.setBold(True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setToolTip(self._tooltip_text())
        self.installEventFilter(ToolTipFilter(self, showDelay=350, position=ToolTipPosition.TOP))

    @staticmethod
    def _display_transition(text: str) -> str:
        if not text:
            return ""
        return "Auto" if text == "True" else text

    def _tooltip_text(self) -> str:
        display = self._display_transition(self.transition_text)
        return "Transition\nCondition: " + (display or "No condition available")

    def _draw_badge(self, painter: QPainter, text: str):
        if not text:
            return

        display = self._display_transition(text)
        if not display:
            return

        painter.save()
        painter.setFont(self._font)
        metrics = QFontMetrics(self._font)
        display = metrics.elidedText(display, Qt.TextElideMode.ElideRight, self.width() - 14)
        text_width = metrics.horizontalAdvance(display)
        badge_width = min(self.width() - 8, text_width + 14)
        badge_height = 18
        badge_x = (self.width() - badge_width) / 2
        badge_rect = QRectF(badge_x, 2, badge_width, badge_height)

        painter.setPen(QPen(QColor(255, 255, 255, 24), 1))
        painter.setBrush(QColor(255, 255, 255, 16))
        painter.drawRoundedRect(badge_rect, 9, 9)
        painter.setPen(QColor("#C9D8E7"))
        painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), display)
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)

        self._draw_badge(painter, self.transition_text)

        line_y = self.height() - 12
        if self.direction == "right":
            start_x, end_x = 8, self.width() - 12
            arrow = QPolygonF(
                [
                    QPointF(end_x - 6, line_y - 5),
                    QPointF(end_x + 1, line_y),
                    QPointF(end_x - 6, line_y + 5),
                ]
            )
        else:
            start_x, end_x = self.width() - 6, 11
            arrow = QPolygonF(
                [
                    QPointF(end_x + 6, line_y - 5),
                    QPointF(end_x - 1, line_y),
                    QPointF(end_x + 6, line_y + 5),
                ]
            )

        glow = QColor(self.color)
        glow.setAlpha(52)
        painter.setPen(QPen(glow, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(start_x, line_y), QPointF(end_x, line_y))

        painter.setPen(QPen(self.color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(start_x, line_y), QPointF(end_x, line_y))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        painter.drawPolygon(arrow)

        super().paintEvent(event)


class FlowTurnConnector(QWidget):
    """Vertical connector used when the snake layout wraps to the next row."""

    HEIGHT = 58

    def __init__(self, side: str, row_width: int, card_width: int, color: str, transition_text: str = "", parent=None):
        super().__init__(parent)
        self.side = side
        self.row_width = row_width
        self.card_width = card_width
        self.color = QColor(color)
        self.transition_text = str(transition_text or "").strip()
        self._font = QFont()
        self._font.setPointSize(9)
        self._font.setBold(True)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setToolTip(self._tooltip_text())
        self.installEventFilter(ToolTipFilter(self, showDelay=350, position=ToolTipPosition.TOP))

    @staticmethod
    def _display_transition(text: str) -> str:
        if not text:
            return ""
        return "Auto" if text == "True" else text

    def _tooltip_text(self) -> str:
        display = self._display_transition(self.transition_text)
        wrap_side = "right edge wrap" if self.side == "right" else "left edge wrap"
        return f"Transition\nCondition: {display or 'No condition available'}\nWrap: {wrap_side}"

    def _anchor_x(self) -> float:
        if self.side == "right":
            return self.row_width - self.card_width / 2
        return self.width() - self.row_width + self.card_width / 2

    def _draw_badge(self, painter: QPainter, anchor_x: float):
        display = self._display_transition(self.transition_text)
        if not display:
            return

        painter.save()
        painter.setFont(self._font)
        metrics = QFontMetrics(self._font)
        display = metrics.elidedText(display, Qt.TextElideMode.ElideRight, 156)
        text_width = metrics.horizontalAdvance(display)
        badge_width = min(160, text_width + 16)
        badge_height = 18
        badge_y = (self.height() - badge_height) / 2 - 2
        badge_x = anchor_x + 14 if self.side == "right" else anchor_x - badge_width - 14
        badge_x = max(4, min(self.width() - badge_width - 4, badge_x))
        badge_rect = QRectF(badge_x, badge_y, badge_width, badge_height)

        painter.setPen(QPen(QColor(255, 255, 255, 24), 1))
        painter.setBrush(QColor(255, 255, 255, 16))
        painter.drawRoundedRect(badge_rect, 9, 9)
        painter.setPen(QColor("#C9D8E7"))
        painter.drawText(badge_rect, int(Qt.AlignmentFlag.AlignCenter), display)
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing)

        center_x = self._anchor_x()
        line_top = 5
        line_bottom = self.height() - 12

        glow = QColor(self.color)
        glow.setAlpha(54)
        painter.setPen(QPen(glow, 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(center_x, line_top), QPointF(center_x, line_bottom))

        painter.setPen(QPen(self.color, 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(center_x, line_top), QPointF(center_x, line_bottom))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.color)
        arrow = QPolygonF(
            [
                QPointF(center_x - 5, line_bottom - 1),
                QPointF(center_x, line_bottom + 6),
                QPointF(center_x + 5, line_bottom - 1),
            ]
        )
        painter.drawPolygon(arrow)
        self._draw_badge(painter, center_x)

        super().paintEvent(event)


class FlowNodeCard(CardWidget):
    """Modern step card used by the Master Recipe flow preview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

    @staticmethod
    def _kind_label(kind: str) -> str:
        mapping = {
            "start": "Start",
            "phase": "Phase",
            "end": "End",
        }
        return mapping.get(kind, "Step")

    @classmethod
    def _tooltip_text(cls, node: Dict, sequence: int) -> str:
        kind = str(node.get("kind", "phase"))
        title = str(node.get("title") or "Unnamed Stage")
        subtitle = str(node.get("subtitle") or "").strip()
        meta = str(node.get("meta") or "").strip()
        transition = str(node.get("transition") or "").strip()

        lines = [
            f"{cls._kind_label(kind)} {sequence:02d}",
            f"Title: {title}",
        ]

        if subtitle:
            label = "Context"
            if kind == "phase":
                label = "Resource"
            elif kind == "end":
                label = "Output"
            lines.append(f"{label}: {subtitle}")

        if meta:
            lines.append(f"Capability: {meta}")

        if transition:
            lines.append(f"Incoming transition: {'Auto' if transition == 'True' else transition}")

        return "\n".join(lines)

    @staticmethod
    def palette_for_kind(kind: str):
        if kind == "start":
            return {
                "fill": "rgba(15, 58, 43, 0.92)",
                "border": "rgba(47, 201, 150, 0.58)",
                "accent": "#B9F6DE",
                "muted": "#8ED6BA",
                "badge": "START",
                "meta_fill": "rgba(185, 246, 222, 0.10)",
            }
        if kind == "end":
            return {
                "fill": "rgba(61, 18, 33, 0.92)",
                "border": "rgba(255, 123, 156, 0.56)",
                "accent": "#FFD0DB",
                "muted": "#F0A7BB",
                "badge": "END",
                "meta_fill": "rgba(255, 208, 219, 0.10)",
            }
        return {
            "fill": "rgba(16, 34, 56, 0.94)",
            "border": "rgba(84, 169, 255, 0.52)",
            "accent": "#B5DBFF",
            "muted": "#8FBFEF",
            "badge": "STEP",
            "meta_fill": "rgba(181, 219, 255, 0.10)",
        }

    @classmethod
    def build(cls, node: Dict, sequence: int, parent=None):
        card = cls(parent)
        kind = str(node.get("kind", "phase"))
        palette = cls.palette_for_kind(kind)
        title = str(node.get("title") or "Unnamed Stage")
        subtitle = str(node.get("subtitle") or "This stage was generated for the selected preview solution.")
        meta = str(node.get("meta") or "").strip()

        card.setObjectName("flowNodeCard")
        card.setStyleSheet(
            f"""
            CardWidget#flowNodeCard {{
                background-color: {palette['fill']};
                border: 1px solid {palette['border']};
                border-radius: 18px;
            }}
            """
        )
        card.setToolTip(cls._tooltip_text(node, sequence))
        card.installEventFilter(ToolTipFilter(card, showDelay=350, position=ToolTipPosition.TOP))

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        badge = CaptionLabel(palette["badge"], card)
        badge.setStyleSheet(
            f"""
            color: {palette['accent']};
            background-color: rgba(255, 255, 255, 0.06);
            border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 999px;
            padding: 3px 8px;
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 0.08em;
            """
        )
        top_row.addWidget(badge)
        top_row.addStretch(1)

        order_label = CaptionLabel(f"{sequence:02d}", card)
        order_label.setStyleSheet(f"color: {palette['muted']}; font-size: 11px; font-weight: 700;")
        top_row.addWidget(order_label)
        layout.addLayout(top_row)

        title_label = StrongBodyLabel(title, card)
        title_label.setWordWrap(True)
        title_label.setStyleSheet("color: #F4F8FC; font-size: 14px; font-weight: 700;")
        layout.addWidget(title_label)

        subtitle_label = BodyLabel(subtitle, card)
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet("color: #D4DDE7; font-size: 11px; line-height: 1.32;")
        layout.addWidget(subtitle_label)

        if meta:
            meta_label = CaptionLabel(meta, card)
            meta_label.setWordWrap(True)
            meta_label.setStyleSheet(
                f"""
                color: {palette['accent']};
                background-color: {palette['meta_fill']};
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 5px 8px;
                font-size: 10px;
                """
            )
            layout.addWidget(meta_label)

        return card


class MasterRecipeFlowView(SmoothScrollArea):
    """Card-based, snake-layout Master Recipe flow preview."""

    CARD_MIN_WIDTH = 180
    CARD_MAX_WIDTH = 248
    MAX_COLUMNS = 4
    CARD_SPACING = 8
    ROW_SPACING = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("masterRecipeFlowView")
        self._flow_nodes = []
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            """
            QScrollArea#masterRecipeFlowView {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
            }
            QWidget#masterRecipeFlowContainer {
                background: transparent;
            }
            """
        )
        self.setScrollAnimation(Qt.Orientation.Vertical, 260)

        self.container = QWidget(self)
        self.container.setObjectName("masterRecipeFlowContainer")
        self.content_layout = QVBoxLayout(self.container)
        self.content_layout.setContentsMargins(18, 18, 18, 24)
        self.content_layout.setSpacing(self.ROW_SPACING)
        self.setWidget(self.container)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._flow_nodes:
            self._rebuild_flow()

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_info_chip(self, text: str, accent: str, parent=None):
        chip = CaptionLabel(text, parent or self.container)
        chip.setStyleSheet(
            f"""
            color: {accent};
            background-color: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.07);
            border-radius: 999px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 700;
            """
        )
        return chip

    @staticmethod
    def _phase_overview_content(nodes):
        start_title = str(nodes[0].get("title") or "Start")
        end_title = str(nodes[-1].get("title") or "End")
        phase_count = sum(1 for node in nodes if node.get("kind") == "phase")
        phase_step_label = "phase step" if phase_count == 1 else "phase steps"
        phase_chip_label = "Phase" if phase_count == 1 else "Phases"
        summary = f'{phase_count} {phase_step_label} between "{start_title}" and "{end_title}".'
        phase_chip_text = f"{phase_count} {phase_chip_label}"
        return phase_count, summary, phase_chip_text

    def _build_overview_card(self, nodes):
        phase_count, summary_text, phase_chip_text = self._phase_overview_content(nodes)

        card = CardWidget(self.container)
        card.setMaximumWidth(560)
        card.setObjectName("flowOverviewCard")
        card.setStyleSheet(
            """
            CardWidget#flowOverviewCard {
                background-color: rgba(255, 255, 255, 0.035);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 22px;
            }
            """
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        eyebrow = CaptionLabel("MASTER RECIPE FLOW", card)
        eyebrow.setStyleSheet("color: #8EBEF7; font-size: 11px; font-weight: 700; letter-spacing: 0.08em;")
        layout.addWidget(eyebrow)

        title = SubtitleLabel(f"{len(nodes)} stage(s) connected as one guided process", card)
        title.setStyleSheet("color: #F3F7FB;")
        layout.addWidget(title)

        summary = BodyLabel(summary_text, card)
        summary.setWordWrap(True)
        summary.setStyleSheet("color: #C9D3DE;")
        layout.addWidget(summary)

        chip_row = QHBoxLayout()
        chip_row.setContentsMargins(0, 4, 0, 0)
        chip_row.setSpacing(8)
        chip_row.addWidget(self._make_info_chip(f"{len(nodes)} Nodes", "#B5DBFF", card))
        chip_row.addWidget(self._make_info_chip(phase_chip_text, "#BDF0D4", card))
        chip_row.addWidget(self._make_info_chip("Preview Solution", "#FFD6DE", card))
        chip_row.addStretch(1)
        layout.addLayout(chip_row)

        return card

    def _draw_placeholder(self, message: str):
        self._clear_content()

        card = CardWidget(self.container)
        card.setObjectName("flowPlaceholderCard")
        card.setStyleSheet(
            """
            CardWidget#flowPlaceholderCard {
                background-color: rgba(255, 255, 255, 0.028);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 22px;
            }
            """
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(8)

        title = SubtitleLabel("No Flow Preview Yet", card)
        title.setStyleSheet("color: #F4F8FC;")
        body = BodyLabel(message, card)
        body.setWordWrap(True)
        body.setStyleSheet("color: #AAB9C8;")
        layout.addWidget(title)
        layout.addWidget(body)

        self.content_layout.addWidget(card)
        self.content_layout.addStretch(1)

    def _flow_layout_metrics(self):
        available_width = max(self.viewport().width() - 36, self.CARD_MIN_WIDTH)
        columns = 1
        for candidate in range(self.MAX_COLUMNS, 0, -1):
            required_width = (
                candidate * self.CARD_MIN_WIDTH
                + (candidate - 1) * FlowStepConnector.WIDTH
                + (candidate * 2 - 2) * self.CARD_SPACING
            )
            if required_width <= available_width:
                columns = candidate
                break

        if columns == 1:
            card_width = min(self.CARD_MAX_WIDTH, available_width)
        else:
            usable_width = available_width - (columns - 1) * FlowStepConnector.WIDTH - (columns * 2 - 2) * self.CARD_SPACING
            card_width = min(self.CARD_MAX_WIDTH, max(self.CARD_MIN_WIDTH, usable_width // columns))

        grid_width = self._row_visual_width(columns, int(card_width))
        return int(card_width), columns, int(grid_width)

    def _row_visual_width(self, row_len: int, card_width: int) -> int:
        if row_len <= 0:
            return 0
        return (
            row_len * card_width
            + max(0, row_len - 1) * FlowStepConnector.WIDTH
            + max(0, row_len * 2 - 2) * self.CARD_SPACING
        )

    def _build_flow_row(self, row_items, row_index: int, card_width: int, grid_width: int):
        row_widget = QWidget(self.container)
        row_widget.setFixedWidth(grid_width)
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(self.CARD_SPACING)

        display_items = row_items if row_index % 2 == 0 else list(reversed(row_items))
        direction = "right" if row_index % 2 == 0 else "left"

        if row_index % 2 == 1:
            row_layout.addStretch(1)

        for position, (sequence, node) in enumerate(display_items):
            card = FlowNodeCard.build(node, sequence, row_widget)
            card.setFixedWidth(card_width)
            row_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)

            if position < len(display_items) - 1:
                connector_color = FlowNodeCard.palette_for_kind(node.get("kind", "phase"))["border"]
                if direction == "right":
                    transition_text = str(display_items[position + 1][1].get("transition") or "")
                else:
                    transition_text = str(display_items[position][1].get("transition") or "")
                row_layout.addWidget(
                    FlowStepConnector(direction, connector_color, transition_text, row_widget),
                    0,
                    Qt.AlignmentFlag.AlignVCenter,
                )

        if row_index % 2 == 0:
            row_layout.addStretch(1)

        return row_widget

    def _build_turn_row(self, row_index: int, row_len: int, card_width: int, grid_width: int, color: str, transition_text: str):
        turn_widget = QWidget(self.container)
        turn_widget.setFixedWidth(grid_width)
        turn_layout = QHBoxLayout(turn_widget)
        turn_layout.setContentsMargins(0, 0, 0, 0)
        turn_layout.setSpacing(0)

        row_width = self._row_visual_width(row_len, card_width)
        connector = FlowTurnConnector(
            side="right" if row_index % 2 == 0 else "left",
            row_width=row_width,
            card_width=card_width,
            color=color,
            transition_text=transition_text,
            parent=turn_widget,
        )
        turn_layout.addWidget(connector)

        return turn_widget

    def _rebuild_flow(self):
        self._clear_content()

        if not self._flow_nodes:
            self._draw_placeholder("No Master Recipe flow preview available yet.")
            return

        card_width, columns, grid_width = self._flow_layout_metrics()
        self.content_layout.addWidget(self._build_overview_card(self._flow_nodes))

        rows = []
        for start in range(0, len(self._flow_nodes), columns):
            chunk = self._flow_nodes[start : start + columns]
            rows.append([(start + offset + 1, node) for offset, node in enumerate(chunk)])

        for row_index, row_items in enumerate(rows):
            self.content_layout.addWidget(self._build_flow_row(row_items, row_index, card_width, grid_width))

            if row_index < len(rows) - 1:
                last_node = row_items[-1][1]
                turn_color = FlowNodeCard.palette_for_kind(last_node.get("kind", "phase"))["border"]
                next_transition = str(rows[row_index + 1][0][1].get("transition") or "")
                self.content_layout.addWidget(
                    self._build_turn_row(row_index, len(row_items), card_width, grid_width, turn_color, next_transition)
                )

        self.content_layout.addStretch(1)

    def set_flow_nodes(self, nodes):
        self._flow_nodes = list(nodes or [])
        self._rebuild_flow()


class LogPage(QWidget):
    """Multi-tab execution log and debug workbench."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("log_page")
        self.context_data: Optional[Dict] = None
        self._tab_pages: Dict[str, QWidget] = {}
        self._mono_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._mono_font.setPointSize(10)
        self._init_ui()
        self.reset_for_run()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header_layout = QVBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        self.title = SubtitleLabel("Execution Log & Debug Workspace", self)
        self.subtitle = CaptionLabel(
            "Inspect parsed inputs, SMT constraints, generated Master Recipe output, and matching diagnostics from the latest run.",
            self,
        )
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color: #8FA0B2;")
        header_layout.addWidget(self.title)
        header_layout.addWidget(self.subtitle)
        layout.addLayout(header_layout)

        metrics_row = QHBoxLayout()
        metrics_row.setContentsMargins(0, 0, 0, 0)
        metrics_row.setSpacing(12)
        self.recipe_card = MetricCard("Recipe ID", "#8BD8FF", self)
        self.resource_card = MetricCard("Parsed Resources", "#7DE4B7", self)
        self.solution_card = MetricCard("Solutions", "#F8BF6B", self)
        self.preview_card = MetricCard("Preview Solution", "#FF9BB3", self)
        metrics_row.addWidget(self.recipe_card)
        metrics_row.addWidget(self.resource_card)
        metrics_row.addWidget(self.solution_card)
        metrics_row.addWidget(self.preview_card)
        layout.addLayout(metrics_row)

        tab_card = CardWidget(self)
        tab_card.setStyleSheet(
            """
            CardWidget {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 22px;
            }
            """
        )
        tab_layout = QVBoxLayout(tab_card)
        tab_layout.setContentsMargins(18, 18, 18, 18)
        tab_layout.setSpacing(12)

        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.setSpacing(16)

        filter_text = QVBoxLayout()
        filter_text.setContentsMargins(0, 0, 0, 0)
        filter_text.setSpacing(4)

        nav_caption = CaptionLabel("Run Artifacts", self)
        nav_caption.setStyleSheet("color: #E9EFF6; font-size: 12px; font-weight: 700; letter-spacing: 0.05em;")
        nav_hint = CaptionLabel("Choose one artifact view from the filter and the panel below updates automatically.", self)
        nav_hint.setStyleSheet("color: #92A4B6;")
        nav_hint.setWordWrap(True)
        filter_text.addWidget(nav_caption)
        filter_text.addWidget(nav_hint)
        filter_row.addLayout(filter_text, 1)

        filter_box = QVBoxLayout()
        filter_box.setContentsMargins(0, 0, 0, 0)
        filter_box.setSpacing(6)

        filter_label = CaptionLabel("View Filter", self)
        filter_label.setStyleSheet("color: #88A8C6;")
        filter_box.addWidget(filter_label, 0, Qt.AlignmentFlag.AlignRight)

        self.view_filter = ComboBox(self)
        self.view_filter.setObjectName("artifactFilter")
        self.view_filter.setMinimumWidth(280)
        self.view_filter.setFixedHeight(38)
        self.view_filter.setStyleSheet(
            """
            ComboBox#artifactFilter {
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 14px;
                padding: 0 38px 0 14px;
                color: #F3F7FB;
                text-align: left;
            }
            ComboBox#artifactFilter:hover {
                background-color: rgba(255, 255, 255, 0.075);
                border: 1px solid rgba(86, 171, 255, 0.34);
            }
            ComboBox#artifactFilter:pressed {
                background-color: rgba(255, 255, 255, 0.09);
            }
            ComboBoxMenu {
                background-color: rgba(25, 31, 39, 0.98);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 14px;
            }
            """
        )
        self.view_filter.currentIndexChanged.connect(self._on_view_filter_changed)
        filter_box.addWidget(self.view_filter)
        filter_row.addLayout(filter_box, 0)
        tab_layout.addLayout(filter_row)

        self.tab_stack = QStackedWidget(self)
        self.tab_stack.setObjectName("logTabStack")
        self.tab_stack.setStyleSheet(
            """
            QStackedWidget#logTabStack {
                background: transparent;
                border: none;
            }
            """
        )

        self.log_edit = self._create_text_view()
        self.recipe_view = self._create_structured_view()
        self.resources_view = self._create_structured_view()
        self.smt_model_view = self._create_text_view()
        self.master_recipe_view = self._create_structured_view()
        self.matching_debug_view = self._create_structured_view()
        self.flow_view = MasterRecipeFlowView(self)

        page_widgets = {
            "log_execution": self.log_edit,
            "log_parsed_recipe": self.recipe_view,
            "log_parsed_resources": self.resources_view,
            "log_smt_model": self.smt_model_view,
            "log_master_recipe": self.master_recipe_view,
            "log_flow": self.flow_view,
            "log_matching_debug": self.matching_debug_view,
        }

        for route_key, text, icon in VIEW_ITEMS:
            self._add_tab_page(route_key, text, page_widgets[route_key], icon)

        self.tab_stack.currentChanged.connect(self._sync_view_filter)
        tab_layout.addWidget(self.tab_stack)
        layout.addWidget(tab_card, 1)

        self._set_current_tab("log_execution")

    def _create_text_view(self) -> TextEdit:
        editor = TextEdit(self)
        editor.setReadOnly(True)
        editor.setFont(self._mono_font)
        editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        editor.setStyleSheet(
            """
            QTextEdit {
                background-color: rgba(255, 255, 255, 0.025);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 18px;
                padding: 10px 12px;
                color: #E7ECF2;
                selection-background-color: rgba(74, 163, 255, 0.35);
            }
            """
        )
        return editor

    def _create_structured_view(self) -> StructuredLogView:
        return StructuredLogView(self._mono_font, self)

    def _add_tab_page(self, route_key: str, text: str, widget: QWidget, icon):
        widget.setObjectName(route_key)
        self._tab_pages[route_key] = widget
        self.tab_stack.addWidget(widget)
        self.view_filter.addItem(text=text, icon=icon, userData=route_key)

    def _sync_view_filter(self, index: int):
        widget = self.tab_stack.widget(index)
        if widget is not None:
            combo_index = self.view_filter.findData(widget.objectName())
            if combo_index >= 0 and combo_index != self.view_filter.currentIndex():
                blocker = QSignalBlocker(self.view_filter)
                self.view_filter.setCurrentIndex(combo_index)
                del blocker

    def _on_view_filter_changed(self, index: int):
        route_key = self.view_filter.itemData(index)
        widget = self._tab_pages.get(route_key)
        if widget is not None and self.tab_stack.currentWidget() is not widget:
            self.tab_stack.setCurrentWidget(widget)

    def _set_current_tab(self, route_key: str):
        widget = self._tab_pages.get(route_key)
        if widget is None:
            return
        self.tab_stack.setCurrentWidget(widget)
        combo_index = self.view_filter.findData(route_key)
        if combo_index >= 0 and combo_index != self.view_filter.currentIndex():
            blocker = QSignalBlocker(self.view_filter)
            self.view_filter.setCurrentIndex(combo_index)
            del blocker

    @staticmethod
    def _placeholder(title: str, body: str) -> str:
        return f"{title}\n{'=' * len(title)}\n\n{body}"

    @staticmethod
    def _format_json(data) -> str:
        try:
            return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False)
        except Exception as exc:
            return f"Failed to serialize debug data:\n{exc}"

    @staticmethod
    def _limit_text(text: str, title: str) -> str:
        """Prevent extremely large debug payloads from overwhelming QTextEdit."""
        if text is None:
            return ""

        if len(text) <= MAX_DEBUG_TEXT_LENGTH:
            return text

        hidden = len(text) - MAX_DEBUG_TEXT_LENGTH
        suffix = (
            f"\n\n[Truncated in UI]\n"
            f"The {title} view was shortened by {hidden} characters to keep the app responsive."
        )
        return text[:MAX_DEBUG_TEXT_LENGTH] + suffix

    def _set_view_text(self, view: TextEdit, text: str, title: str):
        """Set text safely with a UI size cap."""
        view.setPlainText(self._limit_text(text, title))

    def _reset_structured_tabs(self):
        self.recipe_view.set_placeholder(
            "parsed_recipe",
            "Run the calculation to inspect the parsed recipe structure.",
        )
        self.resources_view.set_placeholder(
            "parsed_resources",
            "Parsed AAS/XML resource capabilities will appear here.",
        )
        self.smt_model_view.setPlainText(
            self._placeholder("SMT2-Modell", "The generated SMT constraint model will appear here after a run.")
        )
        self.master_recipe_view.set_placeholder(
            "Master Recipe",
            "A preview XML for the default solution will appear here.",
        )
        self.matching_debug_view.set_placeholder(
            "Matching Debug",
            "Per-step and per-resource capability matching diagnostics will appear here.",
        )
        self.flow_view.set_flow_nodes([])

    def _set_metrics(self, recipe_id="--", resource_count="--", solution_count="--", preview_solution="--"):
        self.recipe_card.set_value(str(recipe_id))
        self.resource_card.set_value(str(resource_count))
        self.solution_card.set_value(str(solution_count))
        self.preview_card.set_value(str(preview_solution))

    def reset_for_run(self, recipe_path: str = "", resource_dir: str = ""):
        """Reset structured tabs for a new calculation run."""
        self.context_data = None
        self.log_edit.clear()
        self._reset_structured_tabs()
        self._set_metrics("Pending", "0", "0", "--")
        self._set_current_tab("log_execution")

        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.append_log(f"Run initialized at {started_at}")
        if recipe_path:
            self.append_log(f"Recipe file: {recipe_path}")
        if resource_dir:
            self.append_log(f"Resource directory: {resource_dir}")

    def append_log(self, msg: str):
        """Append a log line to the execution log tab and keep the cursor at the bottom."""
        if msg is None:
            return

        text = str(msg).rstrip("\n")
        cursor = self.log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self.log_edit.toPlainText():
            cursor.insertText("\n")
        cursor.insertText(text)
        self.log_edit.setTextCursor(cursor)

        current_text = self.log_edit.toPlainText()
        if len(current_text) > MAX_EXECUTION_LOG_LENGTH:
            trimmed = current_text[-MAX_EXECUTION_LOG_LENGTH:]
            first_break = trimmed.find("\n")
            if first_break != -1:
                trimmed = trimmed[first_break + 1:]
            self.log_edit.setPlainText("[Older log lines trimmed]\n" + trimmed)
            cursor = self.log_edit.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.log_edit.setTextCursor(cursor)

        self.log_edit.ensureCursorVisible()

    def set_context_data(self, context_data: Optional[Dict]):
        """Populate all structured debug tabs with the latest run context."""
        self.context_data = context_data if isinstance(context_data, dict) else None
        if not self.context_data:
            self._reset_structured_tabs()
            self._set_metrics("Pending", "0", "0", "--")
            return

        try:
            recipe = self.context_data.get("recipe") or {}
            resources = self.context_data.get("resources") or {}
            solutions = self.context_data.get("solutions") or []
            preview_solution_id = self.context_data.get("preview_solution_id") or "--"

            self._set_metrics(
                recipe_id=recipe.get("ID", "--"),
                resource_count=len(resources),
                solution_count=len(solutions),
                preview_solution=preview_solution_id,
            )

            self.recipe_view.set_structured_content(recipe, "parsed_recipe", format_hint="json")
            self.resources_view.set_structured_content(resources, "parsed_resources", format_hint="json")

            smt_model = self.context_data.get("smt_model") or self._placeholder(
                "SMT2-Modell",
                "No SMT2 text was generated for this run.",
            )
            self._set_view_text(self.smt_model_view, smt_model, "SMT2-Modell")

            master_recipe_preview = self.context_data.get("master_recipe_preview_xml") or self._placeholder(
                "Master Recipe",
                "No preview XML is available. This can happen when no valid solution was found.",
            )
            self.master_recipe_view.set_structured_content(master_recipe_preview, "Master Recipe", format_hint="xml")

            matching_debug = self.context_data.get("matching_debug") or []
            self.matching_debug_view.set_structured_content(matching_debug, "Matching Debug", format_hint="json")

            self.flow_view.set_flow_nodes(self.context_data.get("master_recipe_flow") or [])
            self.append_log("Structured debug panes updated for the latest run.")
        except Exception as exc:
            self.flow_view.set_flow_nodes([])
            self.append_log(f"Warning: failed to render structured debug view: {exc}")
