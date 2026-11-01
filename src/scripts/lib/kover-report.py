#!/usr/bin/env python3
"""Parse and line-union Kover's JaCoCo-compatible XML reports."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_report(path: Path) -> dict[tuple[str, int], tuple[str, bool]]:
    root = ET.parse(path).getroot()
    lines: dict[tuple[str, int], tuple[str, bool]] = {}
    for package in root.findall(".//package"):
        package_name = package.attrib.get("name", "")
        source_classes: dict[str, list[str]] = {}
        for class_node in package.findall("class"):
            class_name = class_node.attrib.get("name")
            source_name = class_node.attrib.get("sourcefilename", "")
            if not class_name:
                raise ValueError(f"class entry has no name in {path}")
            source_classes.setdefault(source_name, []).append(class_name)
            for line_node in class_node.findall(".//line"):
                record_line(lines, package_name, class_name, source_name, line_node, path)
        # Kover emits line entries under <sourcefile>, sibling to <class>.
        # Map only when source attribution is unambiguous; otherwise fail closed.
        for source_node in package.findall("sourcefile"):
            source_name = source_node.attrib.get("name", "")
            candidates = source_classes.get(source_name, [])
            if len(candidates) != 1:
                if source_node.findall("line"):
                    raise ValueError(f"ambiguous sourcefile attribution for {source_name!r} in {path}")
                continue
            for line_node in source_node.findall("line"):
                record_line(lines, package_name, candidates[0], source_name, line_node, path)
    if not lines:
        raise ValueError(f"no line coverage data found in {path}")
    return lines


def record_line(lines, package_name, class_name, source_name, node, path):
    try:
        line_number = int(node.attrib["nr"])
        covered = int(node.attrib.get("ci", "0")) > 0
        missed = int(node.attrib.get("mi", "0")) > 0
    except (KeyError, ValueError) as error:
        raise ValueError(f"invalid line counter in {path}: {error}") from error
    if not (covered or missed):
        return
    key = (f"{package_name}/{class_name}", line_number)
    previous = lines.get(key)
    if previous and previous[0] != source_name:
        raise ValueError(
            f"ambiguous source identity for {key[0]}:{line_number}: "
            f"{previous[0]!r} vs {source_name!r}"
        )
    lines[key] = (source_name, covered or (previous[1] if previous else False))


def summarize(lines: dict[tuple[str, int], tuple[str, bool]]) -> dict[str, int | float]:
    covered = sum(1 for _, hit in lines.values() if hit)
    missed = len(lines) - covered
    return {
        "covered": covered,
        "missed": missed,
        "total": len(lines),
        "percent": round(covered * 100 / len(lines), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="append",
        required=True,
        metavar="SCOPE=XML",
        help="Kover XML report; repeat once per configured JVM scope",
    )
    args = parser.parse_args()

    reports: dict[str, dict[tuple[str, int], tuple[str, bool]]] = {}
    try:
        for entry in args.report:
            scope, separator, filename = entry.partition("=")
            if not separator or not scope or not filename or scope in reports:
                raise ValueError(f"invalid or duplicate report scope: {entry!r}")
            reports[scope] = parse_report(Path(filename))

        merged: dict[tuple[str, int], tuple[str, bool]] = {}
        for scope_lines in reports.values():
            for key, (source, covered) in scope_lines.items():
                previous = merged.get(key)
                if previous and previous[0] != source:
                    raise ValueError(
                        f"ambiguous source identity for {key[0]}:{key[1]}: "
                        f"{previous[0]!r} vs {source!r}"
                    )
                merged[key] = (source, covered or (previous[1] if previous else False))
    except (OSError, ET.ParseError, ValueError) as error:
        print(f"kover-report: {error}", file=sys.stderr)
        return 2

    result = {
        "scopes": {scope: summarize(lines) for scope, lines in reports.items()},
        "combined": summarize(merged),
        "targets": sorted(reports),
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
