#!/usr/bin/env python3
"""Parse and line-union Kover's JaCoCo-compatible XML reports."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def parse_report(path: Path):
    root = ET.parse(path).getroot()
    lines: dict[tuple[str, int], bool] = {}
    class_sources: dict[str, str] = {}
    for package in root.findall(".//package"):
        package_name = package.attrib.get("name", "")
        source_classes: dict[str, list[str]] = {}
        for class_node in package.findall("class"):
            class_name = class_node.attrib.get("name")
            source_name = class_node.attrib.get("sourcefilename", "")
            if not class_name:
                raise ValueError(f"class entry has no name in {path}")
            if source_name:
                source = f"{package_name}/{source_name}"
                previous = class_sources.get(class_name)
                if previous and previous != source:
                    raise ValueError(f"ambiguous source identity for {class_name!r} in {path}")
                class_sources[class_name] = source
                source_classes.setdefault(source_name, []).append(class_name)
            for line_node in class_node.findall(".//line"):
                record_line(lines, package_name, source_name, line_node, path)
        # Sourcefile lines already aggregate all classes in that source file.
        for source_node in package.findall("sourcefile"):
            source_name = source_node.attrib.get("name", "")
            if source_node.findall("line") and not source_classes.get(source_name):
                raise ValueError(f"unknown sourcefile attribution for {source_name!r} in {path}")
            for line_node in source_node.findall("line"):
                record_line(lines, package_name, source_name, line_node, path)
    if not lines:
        raise ValueError(f"no line coverage data found in {path}")
    return lines, class_sources


def record_line(lines, package_name, source_name, node, path):
    if not source_name:
        raise ValueError(f"missing source identity in {path}")
    try:
        line_number = int(node.attrib["nr"])
        covered = int(node.attrib.get("ci", "0")) > 0
        missed = int(node.attrib.get("mi", "0")) > 0
    except (KeyError, ValueError) as error:
        raise ValueError(f"invalid line counter in {path}: {error}") from error
    if not (covered or missed):
        return
    key = (f"{package_name}/{source_name}", line_number)
    lines[key] = covered or lines.get(key, False)


def summarize(lines: dict[tuple[str, int], bool]) -> dict[str, int | float]:
    covered = sum(lines.values())
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

    reports: dict[str, dict[tuple[str, int], bool]] = {}
    class_sources: dict[str, str] = {}
    try:
        for entry in args.report:
            scope, separator, filename = entry.partition("=")
            if not separator or not scope or not filename or scope in reports:
                raise ValueError(f"invalid or duplicate report scope: {entry!r}")
            scope_lines, scope_sources = parse_report(Path(filename))
            for class_name, source in scope_sources.items():
                previous = class_sources.get(class_name)
                if previous and previous != source:
                    raise ValueError(f"ambiguous source identity for {class_name!r}: {previous!r} vs {source!r}")
                class_sources[class_name] = source
            reports[scope] = scope_lines

        merged: dict[tuple[str, int], bool] = {}
        for scope_lines in reports.values():
            for key, covered in scope_lines.items():
                merged[key] = covered or merged.get(key, False)
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
