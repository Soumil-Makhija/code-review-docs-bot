import io
import json
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError

from reviewlens.model import endpoint, generate, make_payload, settings_for
from test_review import fixture


class ModelTests(unittest.TestCase):
    def test_loopback_only_and_bounded_settings(self):
        self.assertEqual(endpoint('http://[::1]:11434'), 'http://[::1]:11434/api/chat')
        for url in ['https://127.0.0.1', 'http://example.com', 'http://localhost', 'http://user@127.0.0.1',
                    'http://127.0.0.1:0', 'http://127.0.0.1/x', 'http://127.0.0.1?x', 'http://127.0.0.1#x']:
            with self.subTest(url=url), self.assertRaises(ValueError): endpoint(url)
        for timeout in [True, 0, float('nan'), 181]:
            with self.assertRaises(ValueError): settings_for(timeout=timeout)

    def test_request_includes_selected_code_and_exact_revisions(self):
        data, _ = fixture()
        payload = make_payload(data, settings_for())
        text = payload['messages'][1]['content']
        self.assertIn(data['head_commit'], text)
        self.assertIn('return sum(xs)/len(xs)', text)
        with self.assertRaises(ValueError): make_payload(data, settings_for(), 'x' * 501)

    def response(self, envelope):
        opener = Mock(); opener.open.return_value = io.BytesIO(json.dumps(envelope).encode())
        return patch('reviewlens.model.build_opener', return_value=opener)

    def test_real_request_path_validates_anchors_and_refuses_redirects(self):
        data, response = fixture()
        with self.response({'done': True, 'message': {'content': json.dumps(response)}}) as builder:
            self.assertEqual(generate(data, settings_for()), response)
        handlers = builder.call_args.args
        self.assertEqual(handlers[0].proxies, {})
        with self.assertRaises(ValueError): handlers[1].redirect_request(None, None, 302, None, {}, 'http://example.com')

    def test_bad_incomplete_truncated_duplicate_and_unanchored_response(self):
        data, response = fixture()
        bad_anchor = json.loads(json.dumps(response)); bad_anchor['findings'][0]['line'] = 99
        for envelope in [[], {'done': False}, {'done': True, 'done_reason': 'length'},
                         {'done': True, 'message': {'content': '[]'}},
                         {'done': True, 'message': {'content': '{"a":1,"a":2}'}},
                         {'done': True, 'message': {'content': json.dumps(bad_anchor)}},
                         {'padding': 'x' * 130000}]:
            with self.subTest(envelope=str(envelope)[:100]), self.response(envelope), self.assertRaises(ValueError):
                generate(data, settings_for())

    def test_network_failure_actionable(self):
        data, _ = fixture()
        with patch('reviewlens.model.build_opener') as builder:
            builder.return_value.open.side_effect = URLError('offline')
            with self.assertRaisesRegex(ValueError, 'start Ollama'): generate(data, settings_for())

    def test_prompt_cap_includes_numbered_sources_and_diff(self):
        data, _ = fixture()
        file = data['files'][0]
        file.update(base_text='x' * 10000 + '\n', head_text='y' * 10000 + '\n',
                    changed_base_lines=[1], changed_head_lines=[1])
        data['diff'] = '@@ -1 +1 @@\n-' + 'x' * 10000 + '\n+' + 'y' * 10000 + '\n'
        with self.assertRaisesRegex(ValueError, '28000'):
            make_payload(data, settings_for())


if __name__ == '__main__':
    unittest.main()
