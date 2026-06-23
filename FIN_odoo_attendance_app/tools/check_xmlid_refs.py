#!/usr/bin/env python3
"""Validate XMLID references for this addon.

Usage:
    python3 tools/check_xmlid_refs.py
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path


CORE_MODULES = {
    "account",
    "analytic",
    "base",
    "base_setup",
    "bus",
    "calendar",
    "contacts",
    "crm",
    "fleet",
    "hr",
    "hr_attendance",
    "hr_expense",
    "hr_holidays",
    "mail",
    "portal",
    "project",
    "purchase",
    "resource",
    "sale",
    "stock",
    "web",
    "website",
}

SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode", "i18n", "static"}

RE_ID_ATTR = re.compile(r"\bid\s*=\s*['\"]([^'\"]+)['\"]")
RE_REF_ATTR = re.compile(r"\bref\s*=\s*['\"]([^'\"]+)['\"]")
RE_REF_CALL = re.compile(r"ref\(\s*['\"]([^'\"]+)['\"]\s*\)")
RE_GROUPS_ATTR = re.compile(r"\bgroups\s*=\s*['\"]([^'\"]+)['\"]")
RE_PARENT_ATTR = re.compile(r"\bparent\s*=\s*['\"]([^'\"]+)['\"]")
RE_ACTION_ATTR = re.compile(r"\baction\s*=\s*['\"]([^'\"]+)['\"]")
RE_ENV_REF_CALL = re.compile(r"\b(?:self\.)?env\.ref\(\s*['\"]([^'\"]+)['\"]")


@dataclass
class RefUse:
    file: Path
    line: int
    xmlid: str
    source: str


def _line_no(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _iter_xml_files(module_root: Path):
    for path in module_root.rglob("*.xml"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _iter_csv_files(module_root: Path):
    for path in module_root.rglob("*.csv"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _iter_py_files(module_root: Path):
    for path in module_root.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _collect_defined_ids(module_root: Path) -> set[str]:
    ids: set[str] = set()
    for path in _iter_xml_files(module_root):
        text = path.read_text(encoding="utf-8")
        for match in RE_ID_ATTR.finditer(text):
            xmlid = match.group(1).strip()
            if xmlid:
                ids.add(xmlid)
    for path in _iter_csv_files(module_root):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "id" not in reader.fieldnames:
                continue
            for row in reader:
                xmlid = (row.get("id") or "").strip()
                if xmlid:
                    ids.add(xmlid)
    return ids


def _extract_xml_refs(path: Path) -> list[RefUse]:
    text = path.read_text(encoding="utf-8")
    refs: list[RefUse] = []

    for regex, source in (
        (RE_REF_ATTR, "ref-attr"),
        (RE_REF_CALL, "ref-call"),
        (RE_PARENT_ATTR, "parent-attr"),
        (RE_ACTION_ATTR, "action-attr"),
    ):
        for match in regex.finditer(text):
            xmlid = match.group(1).strip()
            if xmlid:
                refs.append(RefUse(path, _line_no(text, match.start()), xmlid, source))

    for match in RE_GROUPS_ATTR.finditer(text):
        group_xmlids = [part.strip() for part in match.group(1).split(",")]
        for xmlid in group_xmlids:
            if xmlid:
                refs.append(RefUse(path, _line_no(text, match.start()), xmlid, "groups-attr"))

    return refs


def _extract_csv_refs(path: Path) -> list[RefUse]:
    refs: list[RefUse] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return refs
        id_columns = [col for col in reader.fieldnames if col and col.endswith(":id")]
        if not id_columns:
            return refs
        for idx, row in enumerate(reader, start=2):
            for col in id_columns:
                xmlid = (row.get(col) or "").strip()
                if xmlid:
                    refs.append(RefUse(path, idx, xmlid, f"csv:{col}"))
    return refs


def _extract_py_refs(path: Path) -> list[RefUse]:
    text = path.read_text(encoding="utf-8")
    refs: list[RefUse] = []
    for match in RE_ENV_REF_CALL.finditer(text):
        xmlid = match.group(1).strip()
        if xmlid:
            refs.append(RefUse(path, _line_no(text, match.start()), xmlid, "py:env.ref"))
    return refs


def _is_local_model_xmlid(xmlid: str) -> bool:
    return xmlid.startswith("model_")


def main() -> int:
    module_root = Path(__file__).resolve().parents[1]
    module_name = module_root.name
    defined_ids = _collect_defined_ids(module_root)

    refs: list[RefUse] = []
    for path in _iter_xml_files(module_root):
        refs.extend(_extract_xml_refs(path))
    for path in _iter_csv_files(module_root):
        refs.extend(_extract_csv_refs(path))
    for path in _iter_py_files(module_root):
        refs.extend(_extract_py_refs(path))

    errors: list[str] = []
    core_cross_module_refs: list[str] = []

    for ref_use in refs:
        xmlid = ref_use.xmlid
        if xmlid in {"True", "False", "None"}:
            continue
        if xmlid.startswith("%(") and xmlid.endswith(")d"):
            continue

        if "." in xmlid:
            mod, name = xmlid.split(".", 1)
            if mod == module_name:
                if name not in defined_ids and not _is_local_model_xmlid(name):
                    errors.append(
                        f"{ref_use.file}:{ref_use.line} -> missing same-module xmlid: {xmlid}"
                    )
            elif mod not in CORE_MODULES:
                errors.append(
                    f"{ref_use.file}:{ref_use.line} -> non-core external module ref: {xmlid}"
                )
            else:
                core_cross_module_refs.append(f"{ref_use.file}:{ref_use.line} -> {xmlid}")
            continue

        # Unqualified local ref.
        if xmlid not in defined_ids and not _is_local_model_xmlid(xmlid):
            errors.append(
                f"{ref_use.file}:{ref_use.line} -> missing same-module xmlid: {module_name}.{xmlid}"
            )

    print(f"Module root: {module_root}")
    print(f"Module name: {module_name}")
    print(f"Refs scanned: {len(refs)}")
    if core_cross_module_refs:
        print("\nCore cross-module refs:")
        for item in sorted(set(core_cross_module_refs)):
            print(f"  {item}")

    if errors:
        print("\nFAILED:")
        for err in errors:
            print(f"  {err}")
        return 1

    print("\nOK: XMLID references check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
