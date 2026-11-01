#!/usr/bin/env python3
"""직접 gh pr create 호출의 실제 본문을 검사하거나 --body-file로 명시적 검사한다."""
import argparse
import json
from pathlib import Path
import re
import shlex
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--tool-root', default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument('--body-file')
    args = parser.parse_args()
    root = Path(args.project).resolve()
    body_file, body = args.body_file, None
    if body_file is None:
        payload = json.load(sys.stdin)
        command = payload.get('tool_input', {}).get('command', '')
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|\n')
        lexer.whitespace = ' \t\r'
        segments = [[]]
        for token in lexer:
            if token and all(c in ';&|\n' for c in token):
                segments.append([])
            else:
                segments[-1].append(token)
        calls = [s for s in segments if s[:3] == ['gh', 'pr', 'create']]
        if not calls:
            return 0
        # cwd 변경/복수 호출을 실행해 해석하지 않는다. 지원 경계 밖은 사전 검사를 요구한다.
        if len(calls) != 1 or len([s for s in segments if s]) != 1:
            print('PR 검사: 복합 shell 호출은 check-pr-body.py --project ROOT --body-file FILE로 사전 검사하세요.', file=sys.stderr)
            return 2
        tokens = calls[0][3:]
        for index, token in enumerate(tokens):
            if token in ('--body-file', '-F', '--body', '-b'):
                if index + 1 >= len(tokens):
                    return 2
                if token in ('--body-file', '-F'):
                    body_file = tokens[index + 1]
                else:
                    body = tokens[index + 1]
            elif token.startswith('--body-file='):
                body_file = token.split('=', 1)[1]
            elif token.startswith('--body='):
                body = token.split('=', 1)[1]
        if body is None and body_file is None:
            print('PR 검사: --body 또는 --body-file의 실제 본문이 필요합니다.', file=sys.stderr)
            return 2
    if body_file is not None:
        if body_file == '-' or any(s in body_file for s in ('$', '`')):
            print('PR 검사: stdin/동적 본문 경로는 명시적 사전 검사가 필요합니다.', file=sys.stderr)
            return 2
        path = Path(body_file)
        body = (path if path.is_absolute() else root / path).read_text(encoding='utf-8')
    template = root / '.github/pull_request_template.md'
    if not template.is_file():
        template = Path(args.tool_root) / 'templates/pull_request_template.md'
    text = template.read_text(encoding='utf-8')
    required = [match.group(1) for match in re.finditer(r'^(## .+)\n([^\n]*)', text + '\n', re.MULTILINE)
                if '선택' not in match.group(2)]
    if '```mermaid' in text:
        required.append('```mermaid')
    missing = [section for section in required if section not in body.splitlines()]
    if missing:
        print('PR 본문 템플릿 누락: ' + ', '.join(missing), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, TypeError) as error:
        print(f'PR 검사 실패: {error}', file=sys.stderr)
        sys.exit(2)
