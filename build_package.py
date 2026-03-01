#!/usr/bin/env python3
"""Cross-platform PyInstaller build helper for SMT4ModPlant."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


def _data_arg(src: Path, dst: str) -> str:
    sep = ";" if os.name == "nt" else ":"
    return f"{src}{sep}{dst}"


def _pick_icon(project_root: Path) -> Path | None:
    system = platform.system()
    mac_icon = project_root / "Others" / "logo.icns"
    win_icon = project_root / "Others" / "logo.ico"

    if system == "Darwin" and mac_icon.exists():
        return mac_icon
    if system == "Windows" and win_icon.exists():
        return win_icon
    if mac_icon.exists():
        return mac_icon
    if win_icon.exists():
        return win_icon
    return None


def build_command(project_root: Path, args: argparse.Namespace) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--noconfirm",
        "--name",
        args.name,
    ]

    if args.clean:
        cmd.append("--clean")
    # Default build mode is onedir. Only switch when explicitly requested.
    if args.onefile:
        cmd.append("--onefile")

    for pkg in ("qfluentwidgets", "z3"):
        cmd.extend(["--collect-all", pkg])

    # Runtime assets used by the GUI and transformator module.
    data_assets = [
        (project_root / "Code" / "GUI" / "rwth_logo.bmp", "Code/GUI"),
        (project_root / "Code" / "GUI" / "rwth_logo.png", "Code/GUI"),
        (project_root / "Code" / "Transformator" / "mtp_units_mapping.json", "Code/Transformator"),
    ]
    for src, dst in data_assets:
        if src.exists():
            cmd.extend(["--add-data", _data_arg(src, dst)])

    icon = _pick_icon(project_root)
    if icon is not None:
        cmd.extend(["--icon", str(icon)])

    cmd.append(str(project_root / args.entry))
    cmd.extend(args.pyinstaller_args)
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build SMT4ModPlant with PyInstaller (Windows/macOS aware)."
    )
    parser.add_argument("--name", default="SMT4ModPlant", help="Application name.")
    parser.add_argument("--entry", default="gui_main.py", help="Entry script path.")
    parser.add_argument("--clean", dest="clean", action="store_true", help="Use --clean.")
    parser.add_argument("--no-clean", dest="clean", action="store_false", help="Disable --clean.")
    parser.add_argument("--onefile", action="store_true", help="Build a onefile executable.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated PyInstaller command without running it.",
    )
    parser.add_argument(
        "pyinstaller_args",
        nargs=argparse.REMAINDER,
        help="Extra args passed directly to PyInstaller (prefix with --).",
    )
    parser.set_defaults(clean=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(__file__).resolve().parent
    cmd = build_command(project_root, args)

    print("Running command:")
    print(" ".join(f'"{x}"' if " " in x else x for x in cmd))

    if args.dry_run:
        return 0

    try:
        proc = subprocess.run(cmd, cwd=project_root, check=False)
        return proc.returncode
    except FileNotFoundError:
        print("PyInstaller not found. Install it first: pip install pyinstaller")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
