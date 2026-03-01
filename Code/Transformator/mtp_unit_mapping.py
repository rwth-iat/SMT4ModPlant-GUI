"""
MTP unit mapping helper.

- Source list: MTP_Units.txt (switch/case list of ~600 units)
- Mapping table: mtp_units_mapping.json (generated once, can be extended manually)

Goal:
- Resolve a unit identifier that may come from different sources:
  * MTP unit code (int or numeric string)
  * SI Digital Framework unit URI (si-digital-framework.org)
  * QUDT unit URI (qudt.org)
- Return a canonical label for B2MML (current generator uses German labels),
  while keeping BOTH possible IRDIs for robust matching.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, Union


@dataclass(frozen=True)
class UnitEntry:
    mtp_id: int
    label: str
    si_uri: Optional[str] = None
    qudt_uri: Optional[str] = None

    def all_iris(self) -> List[str]:
        return [u for u in [self.si_uri, self.qudt_uri] if u]


# --- Load mapping table (JSON) ---
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_TABLE = os.path.join(_THIS_DIR, "mtp_units_mapping.json")


def _candidate_table_paths() -> List[str]:
    table_name = "mtp_units_mapping.json"
    meipass = getattr(sys, "_MEIPASS", "")
    exe_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else ""
    return [
        _DEFAULT_TABLE,
        os.path.join(_THIS_DIR, "Code", "Transformator", table_name),
        os.path.join(meipass, "Code", "Transformator", table_name) if meipass else "",
        os.path.join(meipass, "_internal", "Code", "Transformator", table_name) if meipass else "",
        os.path.join(exe_dir, "Code", "Transformator", table_name) if exe_dir else "",
        os.path.join(exe_dir, "_internal", "Code", "Transformator", table_name) if exe_dir else "",
    ]


def _load_table(path: str = _DEFAULT_TABLE) -> List[UnitEntry]:
    table_path = path if os.path.isfile(path) else ""
    if not table_path:
        for candidate in _candidate_table_paths():
            if candidate and os.path.isfile(candidate):
                table_path = candidate
                break

    if not table_path:
        return []

    with open(table_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries: List[UnitEntry] = []
    for row in data:
        try:
            entries.append(
                UnitEntry(
                    mtp_id=int(row["mtp_id"]),
                    label=str(row.get("label", "")),
                    si_uri=row.get("si_uri") or None,
                    qudt_uri=row.get("qudt_uri") or None,
                )
            )
        except Exception:
            # Skip malformed rows instead of breaking execution
            continue
    return entries


_ENTRIES = _load_table()


# --- Build indexes for fast lookup ---
_BY_MTP: Dict[int, UnitEntry] = {e.mtp_id: e for e in _ENTRIES}
_BY_SI: Dict[str, UnitEntry] = {e.si_uri: e for e in _ENTRIES if e.si_uri}
_BY_QUDT: Dict[str, UnitEntry] = {e.qudt_uri: e for e in _ENTRIES if e.qudt_uri}
_BY_LABEL: Dict[str, UnitEntry] = {e.label: e for e in _ENTRIES if e.label}


def resolve_unit(unit_identifier: Union[str, int, None]) -> Dict[str, Any]:
    """
    Resolve a unit identifier to a canonical mapping entry.

    Returns a dict with:
      - label (string)
      - mtp_id (int|None)
      - si_uri (string|None)
      - qudt_uri (string|None)

    If not found, returns the input as label (best-effort).
    """
    if unit_identifier is None:
        return {"label": "", "mtp_id": None, "si_uri": None, "qudt_uri": None}

    # Accept ints and numeric strings as MTP IDs
    if isinstance(unit_identifier, int):
        e = _BY_MTP.get(unit_identifier)
        return _as_dict(e, fallback_label=str(unit_identifier))

    s = str(unit_identifier).strip()
    if s == "":
        return {"label": "", "mtp_id": None, "si_uri": None, "qudt_uri": None}

    # Numeric string => MTP ID
    if s.isdigit():
        e = _BY_MTP.get(int(s))
        return _as_dict(e, fallback_label=s)

    # URI match (prefer exact)
    if s in _BY_SI:
        return _as_dict(_BY_SI[s], fallback_label=s)
    if s in _BY_QUDT:
        return _as_dict(_BY_QUDT[s], fallback_label=s)

    # Try label match (e.g., if AAS provided literal labels)
    if s in _BY_LABEL:
        return _as_dict(_BY_LABEL[s], fallback_label=s)

    # Try last-path-segment match for URIs we don't know yet
    # (keeps previous behavior but without losing the original)
    if "/" in s:
        return {"label": s.split("/")[-1], "mtp_id": None, "si_uri": None, "qudt_uri": None}

    return {"label": s, "mtp_id": None, "si_uri": None, "qudt_uri": None}


def map_unit(unit_identifier: Union[str, int, None]) -> str:
    """Backwards-compatible helper used by MasterRecipeGenerator: return a label."""
    return resolve_unit(unit_identifier)["label"]


def candidate_iris_for_same_unit(unit_identifier: Union[str, int, None]) -> List[str]:
    """
    Return BOTH possible IRIs (SI Digital Framework + QUDT) for the same unit, if known.

    Example:
      candidate_iris_for_same_unit("http://si-digital-framework.org/SI/units/second")
      -> ["http://si-digital-framework.org/SI/units/second", "http://qudt.org/vocab/unit/SEC"]
    """
    resolved = resolve_unit(unit_identifier)
    iris = []
    if resolved.get("si_uri"):
        iris.append(resolved["si_uri"])
    if resolved.get("qudt_uri"):
        iris.append(resolved["qudt_uri"])
    return iris


def _as_dict(e: Optional[UnitEntry], fallback_label: str) -> Dict[str, Any]:
    if not e:
        return {"label": fallback_label, "mtp_id": None, "si_uri": None, "qudt_uri": None}
    return {"label": e.label, "mtp_id": e.mtp_id, "si_uri": e.si_uri, "qudt_uri": e.qudt_uri}
