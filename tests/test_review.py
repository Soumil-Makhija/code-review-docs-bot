import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from reviewlens.cli import main
from reviewlens.review import build_review, digest, markdown, read_json, source_lines, validate_response, validate_review, validate_snapshot, verify_repository, write_json, write_text


def fixture():
    data = {'schema_version': 1, 'base_commit': 'a' * 40, 'head_commit': 'b' * 40,
            'files': [{'path': 'calc.py', 'base_text': 'def average(xs):\n    return 0 if not xs else sum(xs)/len(xs)\n',
                       'head_text': 'def average(xs):\n    return sum(xs)/len(xs)\n',
                       'changed_base_lines': [2], 'changed_head_lines': [2]}],
            'diff': '@@ -2 +2 @@\n-    return 0 if not xs else sum(xs)/len(xs)\n+    return sum(xs)/len(xs)\n'}
    response = {'summary': 'Removes the empty-list guard.',
                'explanations': [{'path': 'calc.py', 'side': 'head', 'line': 2, 'body': 'Returns sum divided by length.'}],
                'findings': [{'path': 'calc.py', 'side': 'head', 'line': 2, 'severity': 'medium',
                              'title': 'Restore empty-input handling',
                              'body': 'An empty list now raises ZeroDivisionError; restore the empty-list guard.'}]}
    return data, response


def report_fixture():
    data, response = fixture()
    return build_review(data, response, {'settings': {}, 'request': {}, 'response': response})


class ReviewTests(unittest.TestCase):
    def test_valid_anchors_and_exact_source_excerpt(self):
        report = report_fixture()
        validate_review(report)
        text = markdown(report)
        self.assertIn('    return sum(xs)/len(xs)', text)
        self.assertIn('calc\\.py:2 (head)', text)
        self.assertIn('`' + 'b' * 40 + '`', text)

    def test_rejects_invented_unchanged_out_of_range_and_boolean_anchors(self):
        data, response = fixture()
        for field, value in [('path', 'secrets.py'), ('line', 1), ('line', 99),
                             ('line', True), ('side', 'working'), ('side', [])]:
            candidate = copy.deepcopy(response)
            candidate['findings'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_response(data, candidate)

    def test_explanation_may_cite_unchanged_context(self):
        data, response = fixture()
        response['explanations'][0]['line'] = 1
        validate_response(data, response)

    def test_findings_may_cite_removed_lines(self):
        data, response = fixture()
        response['findings'][0]['side'] = 'base'
        validate_response(data, response)

    def test_empty_findings_valid_but_no_explanation_invalid(self):
        data, response = fixture()
        response['findings'] = []
        validate_response(data, response)
        response['explanations'] = []
        with self.assertRaises(ValueError):
            validate_response(data, response)

    def test_rejects_duplicate_unknown_and_excess_findings(self):
        data, response = fixture()
        variants = []
        candidate = copy.deepcopy(response); candidate['findings'] *= 2; variants.append(candidate)
        candidate = copy.deepcopy(response); candidate['findings'][0]['code'] = 'execute()'; variants.append(candidate)
        candidate = copy.deepcopy(response); candidate['findings'] *= 6; variants.append(candidate)
        for candidate in variants:
            with self.assertRaises(ValueError):
                validate_response(data, candidate)

    def test_strict_snapshot_shape_and_metadata(self):
        data, _ = fixture()
        for key, value in [('schema_version', True), ('head_commit', 'bad'), ('files', []), ('diff', '')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_snapshot(dict(data, **{key: value}))
        for path in ['/tmp/code.py', '../code.py', '.git/config', 'a//b.py']:
            candidate = copy.deepcopy(data); candidate['files'][0]['path'] = path
            with self.assertRaises(ValueError): validate_snapshot(candidate)

    def test_digest_and_recorded_model_response_consistency(self):
        report = report_fixture()
        report['snapshot']['diff'] += 'tamper'
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): validate_review(report)
        report = copy.deepcopy(report_fixture())
        report['model']['response'] = {}
        with self.assertRaisesRegex(ValueError, 'metadata'): validate_review(report)

    def test_verify_against_actual_git_snapshot(self):
        report = report_fixture()
        with patch('reviewlens.review.snapshot', return_value=report['snapshot']):
            self.assertEqual(verify_repository(report, '.'), report)
        altered = copy.deepcopy(report['snapshot']); altered['files'][0]['head_text'] += '# changed\n'
        with patch('reviewlens.review.snapshot', return_value=altered), self.assertRaisesRegex(ValueError, 'differs'):
            verify_repository(report, '.')

    def test_markdown_escapes_model_html_links_and_source_fences(self):
        report = report_fixture()
        report['response']['summary'] = '<script>oops</script> [click](javascript:alert(1))'
        report['snapshot']['files'][0]['head_text'] = 'def f():\n    # ``` fence\n'
        report['snapshot_sha256'] = digest(report['snapshot'])
        text = markdown(report)
        self.assertNotIn('<script>', text)
        self.assertNotIn('[click](javascript:', text)
        self.assertIn('````\n    # ``` fence\n````', text)

    def test_lf_line_numbering_matches_git_not_unicode_separators(self):
        self.assertEqual(source_lines('x\u2028y\r\nz\n'), ['x\u2028y\r', 'z'])

    def test_atomic_no_clobber_and_strict_json(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'review.json'
            write_json(path, report_fixture())
            before = path.read_bytes()
            with self.assertRaises(ValueError): write_text(path, 'replacement')
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(list(Path(temp).glob('.reviewlens-*')))
            for raw in ['{"a":1,"a":2}', '{"a":NaN}', '[]' * 300000]:
                path.write_text(raw)
                with self.assertRaises(ValueError): read_json(path)

    def test_existing_destination_rejected_before_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'existing'; path.write_text('retained')
            with patch('reviewlens.cli.generate') as generate, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['review', 'absent.json', '--out', str(path)]), 2)
            generate.assert_not_called()
            self.assertEqual(path.read_text(), 'retained')


if __name__ == '__main__':
    unittest.main()
