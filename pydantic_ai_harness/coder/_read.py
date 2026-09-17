"""Bounded file windows with line-based continuation."""

from __future__ import annotations

from typing import BinaryIO

_MAX_CONTENT_CHARS = 60000
_MAX_LINE_BYTES = 65536
_MAX_OUTPUT_CHARS = 64000
_EOF = '[End of file.]'
_BINARY = '[Binary file; use a binary-aware tool.]'


def read_window(source: BinaryIO, *, path: str, offset: int, limit: int) -> str:
    """Read complete lines, consuming skipped long lines in bounded chunks."""
    output: list[str] = []
    number = 0
    budget = _MAX_CONTENT_CHARS
    while line := source.readline(_MAX_LINE_BYTES + 1):
        number += 1
        if b'\0' in line:
            return _render(path, [], _BINARY)
        if number <= offset:
            while len(line) > _MAX_LINE_BYTES and not line.endswith(b'\n'):
                line = source.readline(_MAX_LINE_BYTES + 1)
                if b'\0' in line:
                    return _render(path, [], _BINARY)
            continue
        if len(line) > _MAX_LINE_BYTES:
            return _render(path, output, _oversized(number, '65,536 bytes'))
        rendered = f'{number}: {line.decode("utf-8", errors="replace")}'
        if len(rendered) > _MAX_CONTENT_CHARS:
            return _render(path, output, _oversized(number, 'the 60,000-character read window'))
        if len(rendered) > budget:
            return _render(path, output, f'[More content remains. Use offset={number - 1} to continue.]')
        output.append(rendered)
        budget -= len(rendered)
        if len(output) >= limit or budget == 0:
            notice = f'[More content remains. Use offset={number} to continue.]' if source.read(1) else _EOF
            return _render(path, output, notice)
    return _render(path, output, _EOF)


def _oversized(number: int, bound: str) -> str:
    return (
        f'[Line {number} exceeds {bound} and was not returned; '
        f'use shell for a bounded byte-range inspection. To skip this line, use offset={number}.]'
    )


def _render(path: str, output: list[str], notice: str) -> str:
    content = ''.join(output)
    # Abbreviate an unusually long path label rather than losing content or the continuation notice.
    path_budget = _MAX_OUTPUT_CHARS - len(content) - len(notice) - 4
    if len(path) > path_budget:
        path = '...' + path[-(path_budget - 3) :]
    return f'[{path}]\n{content}\n{notice}'
