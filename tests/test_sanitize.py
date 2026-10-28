import csv
import io
import json
import os
from pathlib import Path
import random
import secrets
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from sttm_sanitize.core import (
    Dataset, Limits, SanitizeError, Tokenizer, encode_csv, sanitize, verify_archive,
)
from sttm_sanitize.cli import main, expand_inputs

ROOT = Path(__file__).resolve().parents[1]


class SanitizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.out = self.root / 'result'

    def tearDown(self):
        self.temp.cleanup()

    def source(self, name='input.csv', header=None, rows=None, encoding='utf-8', delimiter=','):
        path = self.root / name
        with path.open('w', encoding=encoding, newline='') as stream:
            writer = csv.writer(stream, delimiter=delimiter, lineterminator='\r\n')
            writer.writerow(header if header is not None else ['A', 'B'])
            writer.writerows(rows if rows is not None else [['one', 'two']])
        return path

    def glossary(self):
        return json.loads((self.out / 'glossary.json').read_text())

    def records(self, dataset='ds_001.csv'):
        with zipfile.ZipFile(self.out / 'UPLOAD_reports.zip') as archive:
            return list(csv.reader(io.StringIO(archive.read(dataset).decode(), newline='')))

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, '-m', 'sttm_sanitize', *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True, env=env)

    def test_cross_file_global_bijection(self):
        a = self.source('a.csv', rows=[['same', 'different'], ['same', 'same']])
        b = self.source('b.csv', rows=[['different', 'same']])
        result = sanitize([a, b], self.out)
        one, two = self.records(), self.records('ds_002.csv')
        self.assertEqual(one[1][0], one[2][0])
        self.assertEqual(one[1][0], two[1][1])
        self.assertNotEqual(one[1][0], one[1][1])
        self.assertEqual(one[1][1], two[1][0])
        self.assertEqual(result.unique_values, 2)
        self.assertEqual(self.glossary()['verification']['status'], 'passed')
        self.assertEqual(self.glossary()['verification']['ese_sttm_parity'], 'NOT_RUN')

    def test_empty_and_duplicate_rows(self):
        original = [['', 'x'], ['', 'x'], ['', '']]
        a = self.source(rows=original)
        sanitize([a], self.out)
        rows = self.records()[1:]
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[2], ['', ''])
        self.assertNotIn('', self.glossary()['values'].values())

    def test_quoted_comma_quotes_newlines_unicode_and_control(self):
        original = [['a,b', 'a"b'], ['line1\nline2', 'CR\ronly'], ['CRLF\r\ninside', 'Hải 😀'], ['\x00', '\t']]
        a = self.source(rows=original)
        sanitize([a], self.out)
        mapping = self.glossary()['values']
        self.assertEqual([[mapping.get(v, '') for v in row] for row in self.records()[1:]], original)

    def test_exact_strings_no_coercion_or_normalization(self):
        values = ['1', '001', '1.0', ' x', 'x ', 'x', 'X', '\u00e9', 'e\u0301', 'NULL', 'null', 'None', ' ']
        a = self.source(header=['value'], rows=[[v] for v in values])
        sanitize([a], self.out)
        self.assertEqual(len(self.glossary()['values']), len(values))
        self.assertTrue(all(row[0] for row in self.records()[1:]))

    def test_duplicate_blank_headers_and_same_basename(self):
        (self.root / 'sub').mkdir()
        a = self.source('data.csv', header=['same', 'same', ''], rows=[['a', 'b', 'c']])
        b = self.source('sub/data.csv', header=['x'], rows=[['a']])
        sanitize([a, b], self.out)
        self.assertEqual(self.records()[0], ['f_001', 'f_002', 'f_003'])
        metadata = self.glossary()['datasets']
        self.assertEqual([f['original_name'] for f in metadata[0]['fields']], ['same', 'same', ''])
        self.assertEqual(metadata[0]['original_filename'], metadata[1]['original_filename'])
        self.assertNotEqual(metadata[0]['dataset_id'], metadata[1]['dataset_id'])

    def test_header_only(self):
        sanitize([self.source(rows=[])], self.out)
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.glossary()['values'], {})

    def test_bom_semicolon_and_other_encoding(self):
        a = self.source(encoding='utf-8-sig', delimiter=';', rows=[['Hải', 'á']])
        sanitize([a], self.out, delimiter=';')
        self.assertEqual(self.glossary()['datasets'][0]['fields'][0]['original_name'], 'A')
        self.assertEqual(self.records()[0], ['f_001', 'f_002'])
        b = self.source('other.csv', encoding='cp1252', rows=[['café', 'à']])
        sanitize([b], self.root / 'other-out', encoding='cp1252')

    def test_upload_exact_allowlist_no_raw_names_or_values(self):
        secret = 'CUSTOMER_SECRET_72c1'
        path = self.source('confidential-client.csv', header=['Private Name'], rows=[[secret]])
        sanitize([path], self.out)
        with zipfile.ZipFile(self.out / 'UPLOAD_reports.zip') as archive:
            self.assertEqual(archive.namelist(), ['ds_001.csv'])
            for name in archive.namelist():
                self.assertNotIn(secret.encode(), archive.read(name))
                self.assertNotIn(b'Private Name', archive.read(name))
                self.assertNotIn(b'confidential', name.encode())
        self.assertIn(secret, (self.out / 'glossary.json').read_text())

    def test_input_never_modified_and_private_permissions(self):
        source = self.source()
        before = source.read_bytes()
        sanitize([source], self.out)
        self.assertEqual(source.read_bytes(), before)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o700)
            for child in self.out.iterdir():
                self.assertEqual(stat.S_IMODE(child.stat().st_mode), 0o600)

    def test_existing_output_never_overwritten(self):
        self.out.mkdir()
        marker = self.out / 'marker'
        marker.write_text('keep')
        with self.assertRaises(SanitizeError):
            sanitize([self.source()], self.out)
        self.assertEqual(marker.read_text(), 'keep')
        self.assertEqual(list(self.out.iterdir()), [marker])

    def test_output_file_or_symlink_not_overwritten(self):
        self.out.write_text('keep')
        with self.assertRaises(SanitizeError):
            sanitize([self.source()], self.out)
        self.assertEqual(self.out.read_text(), 'keep')
        if hasattr(os, 'symlink'):
            link = self.root / 'link'
            try:
                link.symlink_to(self.root / 'missing', target_is_directory=True)
            except OSError:
                return
            with self.assertRaises(SanitizeError):
                sanitize([self.source()], link)
            self.assertTrue(link.is_symlink())

    def test_malformed_input_no_artifacts_no_value_leak(self):
        path = self.root / 'bad.csv'
        path.write_text('a,b\nSECRET_VALUE\n')
        with self.assertRaises(SanitizeError) as error:
            sanitize([path], self.out)
        self.assertNotIn('SECRET_VALUE', str(error.exception))
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.sttm-sanitize-*')))

    def test_invalid_quote_and_blank_record(self):
        for text in ['a,b\n"not closed,b\n', 'a,b\n\n']:
            path = self.root / 'bad.csv'
            path.write_text(text)
            with self.assertRaises(SanitizeError):
                sanitize([path], self.out)
            self.assertFalse(self.out.exists())

    def test_input_selection_and_limits(self):
        a = self.source(rows=[['x', 'y'], ['z', 'y']])
        for paths, limits in [([a, a], Limits()), ([a], Limits(max_rows=1)), ([a], Limits(max_fields=1)),
                              ([a], Limits(max_file_bytes=1)),
                              ([a], Limits(max_rows=0)), ([], Limits())]:
            with self.subTest(limits=limits, count=len(paths)):
                with self.assertRaises(SanitizeError):
                    sanitize(paths, self.out, limits=limits)
        b = self.source('second.csv')
        with self.assertRaises(SanitizeError):
            sanitize([a, b], self.out, limits=Limits(max_files=1))

    def test_long_data_field_limit(self):
        a = self.source(header=['x'], rows=[['long-value']])
        with self.assertRaises(SanitizeError):
            sanitize([a], self.out, limits=Limits(max_field_chars=2))
        self.assertFalse(self.out.exists())

    def test_long_header_field_limit(self):
        a = self.source(header=['long-header'], rows=[['a']])
        with self.assertRaises(SanitizeError):
            sanitize([a], self.out, limits=Limits(max_field_chars=2))

    def test_decoding_invalid_encoding_delimiter_and_extension(self):
        a = self.root / 'bad.csv'
        a.write_bytes(b'a\n\xff')
        for options in [dict(), dict(encoding='not-a-real-encoding'), dict(delimiter='||')]:
            with self.assertRaises(SanitizeError):
                sanitize([a], self.out, **options)
        other = self.root / 'input.xlsx'
        other.write_bytes(b'not csv')
        with self.assertRaises(SanitizeError):
            sanitize([other], self.out)

    def test_token_collision_retries_and_exhaustion(self):
        first, second = 'v_' + '0'*32, 'v_' + '1'*32
        calls = iter([first, first, second])
        tokenizer = Tokenizer(lambda: next(calls))
        self.assertEqual(tokenizer.transform('a'), first)
        self.assertEqual(tokenizer.transform('b'), second)
        self.assertEqual(tokenizer.transform('a'), first)
        broken = Tokenizer(lambda: first)
        broken.transform('a')
        with self.assertRaises(SanitizeError):
            broken.transform('b')

    def test_original_can_look_like_a_token(self):
        a = self.source(rows=[['v_' + '1'*32, 'other']])
        sanitize([a], self.out)
        self.assertIn('v_' + '1'*32, self.glossary()['values'].values())

    def test_distinct_runs_get_distinct_mapping(self):
        a = self.source()
        sanitize([a], self.out)
        second = self.root / 'second'
        sanitize([a], second)
        one = self.glossary()
        two = json.loads((second / 'glossary.json').read_text())
        self.assertNotEqual(one['scope_id'], two['scope_id'])
        self.assertNotEqual(one['values'], two['values'])

    def test_verification_failure_never_publishes_upload(self):
        a = self.source()
        with mock.patch('sttm_sanitize.core.verify_archive', side_effect=SanitizeError('Forced failure')):
            with self.assertRaises(SanitizeError):
                sanitize([a], self.out)
        self.assertFalse(self.out.exists())
        self.assertFalse(list(self.root.glob('.sttm-sanitize-*')))

    def test_serialized_verifier_detects_tamper(self):
        a = self.source()
        sanitize([a], self.out)
        glossary = self.glossary()
        original = Dataset('ds_001', a.name, ['A', 'B'], [['one', 'two']], glossary['datasets'][0]['source_sha256'])
        glossary['values'][next(iter(glossary['values']))] = 'WRONG'
        with self.assertRaises(SanitizeError):
            verify_archive(self.out / 'UPLOAD_reports.zip', glossary, [original])
        glossary = self.glossary()
        extra = self.root / 'extra.zip'
        with zipfile.ZipFile(extra, 'w') as z:
            z.writestr('glossary.json', json.dumps(glossary))
        with self.assertRaises(SanitizeError):
            verify_archive(extra, glossary, [original])

    def test_randomized_partition_and_recovery(self):
        rng = random.Random(4221)
        pool = ['', 'a', 'A', ' ', '001', '1', 'a,b', 'x\ny', 'Hải', 'é', 'e\u0301']
        originals = [[rng.choice(pool) for _ in range(6)] for _ in range(90)]
        a = self.source(header=['same']*6, rows=originals)
        sanitize([a], self.out)
        transformed = self.records()[1:]
        pairs = list(zip(sum(originals, []), sum(transformed, [])))
        for x, tx in pairs:
            for y, ty in pairs:
                self.assertEqual(x == y, tx == ty)
        reverse = self.glossary()['values']
        self.assertEqual([[reverse[v] if v else '' for v in row] for row in transformed], originals)

    def test_cli_help_version_folder_and_glob(self):
        self.source()
        self.assertEqual(self.run_cli('--help').returncode, 0)
        self.assertIn('0.1.0', self.run_cli('--version').stdout)
        result = self.run_cli('--input', self.root, '--output', self.out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('UPLOAD ONLY', result.stdout)
        self.assertNotIn('one', result.stdout + result.stderr)
        paths = expand_inputs([str(self.root / '*.csv')])
        self.assertEqual(len(paths), 1)

    def test_cli_bad_args_and_safe_failure(self):
        a = self.source(rows=[['SECRET', 'x']])
        result = self.run_cli('--input', a, '--output', self.out, '--max-rows', '0')
        self.assertEqual(result.returncode, 2)
        a.write_text('a,b\nSECRET\n')
        result = self.run_cli('--input', a, '--output', self.out)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('SECRET', result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_complete_cli_with_network_calls_blocked(self):
        self.source()
        guard = self.root / 'guard'
        guard.mkdir()
        (guard / 'sitecustomize.py').write_text(
            'import socket\n'
            'def denied(*a, **kw):\n'
            '    raise RuntimeError("NETWORK_ATTEMPT")\n'
            'socket.socket = denied\n'
            'socket.getaddrinfo = denied\n'
            'socket.create_connection = denied\n'
        )
        env = dict(os.environ, PYTHONPATH=str(guard))
        result = self.run_cli('--input', self.root, '--output', self.out, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('NETWORK_ATTEMPT', result.stderr)


if __name__ == '__main__':
    unittest.main()
