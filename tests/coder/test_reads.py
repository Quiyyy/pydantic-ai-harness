import re
from pathlib import Path

import pytest

from .test_tools import call

pytestmark = pytest.mark.anyio


class TestCoder:
    @pytest.mark.parametrize('character,length,ending', [('A', 40000, '\n'), ('é', 30000, '\r\n'), ('漢', 21000, '\n')])
    async def test_read_pages_preserve_complete_lines(
        self, tmp_path: Path, character: str, length: int, ending: str
    ) -> None:
        line = character * length
        original = ending.join([line, line, 'last'])
        (tmp_path / 'file').write_bytes(original.encode('utf-8'))
        offset = 0
        contents: list[str] = []
        output = ''
        while not output.endswith('[End of file.]'):
            assert len(contents) < 3, 'Reading did not reach EOF.'
            output = await call(tmp_path, 'read_file', {'path': 'file', 'offset': offset})
            assert len(output) <= 64000
            body = output.partition('\n')[2].rpartition('\n[')[0]
            contents.append(re.sub(r'^\d+: ', '', body, flags=re.MULTILINE))
            if not output.endswith('[End of file.]'):
                match = re.search(r'Use offset=(\d+) to continue\.', output)
                assert match is not None
                next_offset = int(match.group(1))
                assert next_offset > offset
                offset = next_offset
        assert ''.join(contents) == original

    @pytest.mark.parametrize('ending', [b'\n', b'\r\n', b''])
    async def test_read_exact_character_budget(self, tmp_path: Path, ending: bytes) -> None:
        content = b'A' * (60000 - 3 - len(ending)) + ending
        (tmp_path / 'file').write_bytes(content)
        output = await call(tmp_path, 'read_file', {'path': 'file'})
        assert output == '[file]\n1: ' + content.decode() + '\n[End of file.]'

    async def test_read_full_page_with_more_content(self, tmp_path: Path) -> None:
        first = 'A' * 59996 + '\n'
        (tmp_path / 'file').write_bytes((first + 'next').encode())
        output = await call(tmp_path, 'read_file', {'path': 'file'})
        assert output == f'[file]\n1: {first}\n[More content remains. Use offset=1 to continue.]'
        assert await call(tmp_path, 'read_file', {'path': 'file', 'offset': 1}) == ('[file]\n2: next\n[End of file.]')

    @pytest.mark.parametrize('limit', [1, 2, 2000, 3000])
    async def test_read_line_limit_and_eof(self, tmp_path: Path, limit: int) -> None:
        count = min(limit, 2000)
        (tmp_path / 'file').write_bytes(b'line\n' * (count + 1))
        output = await call(tmp_path, 'read_file', {'path': 'file', 'limit': limit})
        assert output.count(': line\n') == count
        assert output.endswith(f'[More content remains. Use offset={count} to continue.]')
        last = await call(tmp_path, 'read_file', {'path': 'file', 'offset': count, 'limit': 1})
        assert last == f'[file]\n{count + 1}: line\n\n[End of file.]'

    @pytest.mark.parametrize('content,offset', [(b'', 0), (b'one\n', 1), (b'one', 1), (b'one\n', 10**12)])
    async def test_read_empty_or_past_eof(self, tmp_path: Path, content: bytes, offset: int) -> None:
        (tmp_path / 'file').write_bytes(content)
        assert await call(tmp_path, 'read_file', {'path': 'file', 'offset': offset}) == '[file]\n\n[End of file.]'

    @pytest.mark.parametrize(
        'content', [b'A' * 61000, b'A' * 70000, ('漢' * 22000).encode()], ids=['chars', 'bytes', 'utf8']
    )
    @pytest.mark.parametrize('prefix', [b'', b'first\n'])
    async def test_read_oversized_line_is_explicit(self, tmp_path: Path, content: bytes, prefix: bytes) -> None:
        (tmp_path / 'file').write_bytes(prefix + content + b'\nlast\n')
        output = await call(tmp_path, 'read_file', {'path': 'file'})
        number = 2 if prefix else 1
        assert f'Line {number} exceeds' in output
        assert 'was not returned' in output
        assert 'shell for a bounded byte-range inspection' in output
        assert f'To skip this line, use offset={number}.' in output
        assert 'AAAA' not in output and '漢' not in output
        if prefix:
            assert '1: first\n' in output
        assert await call(tmp_path, 'read_file', {'path': 'file', 'offset': number}) == (
            f'[file]\n{number + 1}: last\n\n[End of file.]'
        )

    @pytest.mark.parametrize('size', [65536, 65537, 131074, 200000])
    @pytest.mark.parametrize('ending', [b'\n', b'\r\n'])
    async def test_read_skips_oversized_logical_lines(self, tmp_path: Path, size: int, ending: bytes) -> None:
        (tmp_path / 'file').write_bytes(b'A' * size + ending + b'also skipped\nTARGET\n')
        assert await call(tmp_path, 'read_file', {'path': 'file', 'offset': 2, 'limit': 1}) == (
            '[file]\n3: TARGET\n\n[End of file.]'
        )

    @pytest.mark.parametrize('size', [65537, 70000, 131074])
    async def test_read_skips_unterminated_oversized_line(self, tmp_path: Path, size: int) -> None:
        (tmp_path / 'file').write_bytes(b'A' * size)
        assert await call(tmp_path, 'read_file', {'path': 'file', 'offset': 1}) == '[file]\n\n[End of file.]'

    @pytest.mark.parametrize(
        'content', [('é' * 32768).encode(), ('漢' * 21845 + '\n').encode()], ids=['eof', 'newline']
    )
    async def test_read_exact_byte_limit(self, tmp_path: Path, content: bytes) -> None:
        assert len(content) == 65536
        (tmp_path / 'file').write_bytes(content)
        assert await call(tmp_path, 'read_file', {'path': 'file'}) == (
            '[file]\n1: ' + content.decode() + '\n[End of file.]'
        )

    async def test_read_skipped_binary_chunk(self, tmp_path: Path) -> None:
        (tmp_path / 'file').write_bytes(b'A' * 70000 + b'\0\ntext\n')
        assert 'Binary file' in await call(tmp_path, 'read_file', {'path': 'file', 'offset': 1})

    async def test_read_final_limit_includes_path_and_notice(self, tmp_path: Path) -> None:
        (tmp_path / 'file').write_bytes(b'A' * 59996 + b'\nnext\n')
        output = await call(tmp_path, 'read_file', {'path': './' * 40000 + 'file'})
        assert len(output) <= 64000
        assert output.count('A') == 59996
        assert output.endswith('[More content remains. Use offset=1 to continue.]')
