"""Kover source-line union across classes and reports."""
import json
from pathlib import Path
import subprocess
import sys

PARSER = Path(__file__).resolve().parents[1] / 'src/scripts/lib/kover-report.py'


def report(package, source, classes, lines, class_lines=''):
    entries = ''.join(f'<class name="{package}/{name}" sourcefilename="{source}">{class_lines}</class>' for name in classes)
    counters = ''.join(f'<line nr="{nr}" ci="{int(hit)}" mi="{int(not hit)}"/>' for nr, hit in lines)
    return f'<report><package name="{package}">{entries}<sourcefile name="{source}">{counters}</sourcefile></package></report>'


def run(tmp_path, *reports):
    args = [sys.executable, str(PARSER)]
    for i, xml in enumerate(reports):
        path = tmp_path / f'{i}.xml'
        path.write_text(xml)
        args += ['--report', f'scope{i}={path}']
    return subprocess.run(args, capture_output=True, text=True)


def test_nested_and_top_level_classes_share_source_lines(tmp_path):
    xml = report('p', 'Policy.kt', ['Policy', 'Policy$Appearance', 'Helper'], [(10, True), (11, False)],
                 '<line nr="10" ci="1" mi="0"/>')
    result = run(tmp_path, xml)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['combined'] == {'covered': 1, 'missed': 1, 'total': 2, 'percent': 50.0}


def test_reports_union_hits_and_do_not_double_count(tmp_path):
    first = report('p', 'Policy.kt', ['Policy', 'Policy$Appearance'], [(1, True), (2, False), (3, False)])
    second = report('p', 'Policy.kt', ['Policy'], [(1, False), (2, True), (3, False)])
    result = run(tmp_path, first, second, first)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value['scopes']['scope0']['covered'] == 1
    assert value['combined'] == {'covered': 2, 'missed': 1, 'total': 3, 'percent': 66.6667}


def test_same_filename_in_different_packages_is_separate(tmp_path):
    result = run(tmp_path, report('a', 'Policy.kt', ['Policy'], [(1, True)]),
                 report('b', 'Policy.kt', ['Policy'], [(1, False)]))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['combined']['total'] == 2


def test_conflicting_class_source_across_reports_is_rejected(tmp_path):
    result = run(tmp_path, report('p', 'First.kt', ['Policy'], [(1, True)]),
                 report('p', 'Second.kt', ['Policy'], [(1, True)]))
    assert result.returncode == 2
    assert 'ambiguous source identity' in result.stderr


def test_unknown_source_attribution_is_rejected(tmp_path):
    result = run(tmp_path, report('p', 'Unknown.kt', [], [(1, True)]))
    assert result.returncode == 2
    assert 'sourcefile attribution' in result.stderr


def test_empty_and_invalid_line_reports_are_rejected(tmp_path):
    for xml in ('<report/>', report('p', 'Policy.kt', ['Policy'], [('invalid', True)])):
        result = run(tmp_path, xml)
        assert result.returncode == 2
