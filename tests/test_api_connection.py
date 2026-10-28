import os
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch, Mock
import httpx
from openai import OpenAI

from core.api_connection import PROVIDERS, connection_config, create_completion, get_api_key, normalize_base_url
from core.config_loader import get_paths_config, get_processing_config
from server import config_server as server


class ConnectionTests(unittest.TestCase):
    def test_legacy_provider_inference(self):
        for host, provider in [('api.openai.com', 'openai'), ('api.deepseek.com', 'deepseek'), ('generativelanguage.googleapis.com', 'gemini'), ('api.anthropic.com', 'claude'), ('openrouter.ai', 'openrouter')]:
            self.assertEqual(get_processing_config({'processing': {'base_url': f'https://{host}/v1'}}).provider, provider)

    def test_url_normalization(self):
        for suffix in ['', '/', '/v1/', '/v1/chat/completions']:
            self.assertEqual(normalize_base_url('https://api.anthropic.com' + suffix), 'https://api.anthropic.com/v1')
        for url in ['file:///tmp/a', 'https://user:pass@example.org', 'https://example.org?key=secret']:
            with self.assertRaises(ValueError):
                normalize_base_url(url)

    def test_keys_are_isolated(self):
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'deep', 'OPENROUTER_API_KEY_BACKUP': 'backup'}, clear=True):
            self.assertEqual(get_api_key('claude')[0], '')
            self.assertEqual(get_api_key('deepseek')[0], 'deep')
            self.assertEqual(get_api_key('openrouter')[0], 'backup')

    def test_codex_inference_and_shared_openai_key(self):
        inferred = connection_config({'base_url': 'https://api.openai.com/v1/responses', 'model': 'gpt-5.1-codex'})
        self.assertEqual(inferred['provider'], 'codex')
        self.assertEqual(inferred['base_url'], 'https://api.openai.com/v1')
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'openai-key'}, clear=True):
            self.assertEqual(get_api_key('codex'), get_api_key('openai'))
            self.assertEqual(get_api_key('gemini')[0], '')
            self.assertEqual(get_api_key('claude')[0], '')

    def test_new_connections_use_correct_protocol_and_save_only_verified_keys(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True), patch.object(server, 'ROOT', Path(directory)):
            client = server.app.test_client()
            for provider in ('gemini', 'claude', 'codex'):
                with self.subTest(provider=provider):
                    response = Mock(status_code=200)
                    response.json.return_value = ({'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}]}
                                                  if provider == 'codex' else {'choices': [{'message': {'content': 'OK'}}]})
                    request = {'processing': {'provider': provider}, 'key': provider + '-secret'}
                    with patch.object(server.http_requests, 'post', return_value=response) as post:
                        self.assertEqual(client.post('/test-connection', json=request).status_code, 200)
                        suffix = '/responses' if provider == 'codex' else '/chat/completions'
                        self.assertEqual(post.call_args.args[0], PROVIDERS[provider]['base_url'] + suffix)
                        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer ' + provider + '-secret')
                        self.assertEqual(os.environ[PROVIDERS[provider]['key_env']], provider + '-secret')
                        self.assertFalse(post.call_args.kwargs['allow_redirects'])
                        response.status_code = 401
                        request['key'] = 'invalid-replacement'
                        self.assertEqual(client.post('/test-connection', json=request).status_code, 400)
                        self.assertEqual(os.environ[PROVIDERS[provider]['key_env']], provider + '-secret')

    def test_codex_sdk_round_trip_with_image_and_tools(self):
        requests = []
        reasoning = {'type': 'reasoning', 'id': 'rs_1', 'summary': [], 'encrypted_content': 'encrypted-state'}
        def handle(request):
            requests.append(json.loads(request.content))
            self.assertEqual(str(request.url), 'https://api.openai.com/v1/responses')
            output = ([reasoning, {'type': 'function_call', 'id': 'fc_1', 'call_id': 'call_1', 'name': 'search', 'arguments': '{"query":"drawing"}'}]
                      if len(requests) == 1 else [{'type': 'message', 'id': 'msg_1', 'role': 'assistant', 'content': [{'type': 'output_text', 'text': '{"domain":"Architecture"}', 'annotations': []}]}])
            return httpx.Response(200, json={'id': 'resp_1', 'object': 'response', 'created_at': 1, 'status': 'completed', 'model': 'gpt-5.1-codex', 'output': output})
        with OpenAI(api_key='test-key', http_client=httpx.Client(transport=httpx.MockTransport(handle))) as client:
            messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Classify this drawing.'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,example'}}]}]
            options = {'model': 'gpt-5.1-codex', 'tools': [{'type': 'function', 'function': {
                'name': 'search', 'parameters': {'type': 'object', 'properties': {'query': {'type': 'string'}}}
            }}], 'temperature': 0, 'timeout': 30}
            first = create_completion(client, messages=messages, **options)
            call = first.choices[0].message.tool_calls[0]
            self.assertEqual(call.function.name, 'search')
            messages.extend([first.choices[0].message, {'role': 'tool', 'tool_call_id': call.id, 'content': 'Found a drawing.'}])
            final = create_completion(client, messages=messages, **options)
        self.assertEqual(json.loads(final.choices[0].message.content)['domain'], 'Architecture')
        self.assertEqual(requests[0]['input'][0]['content'][1]['type'], 'input_image')
        self.assertNotIn('temperature', requests[0])
        self.assertFalse(requests[0]['store'])
        self.assertIn(reasoning, requests[1]['input'])
        self.assertEqual(requests[1]['input'][-1]['call_id'], 'call_1')
        self.assertEqual(requests[1]['input'][-1]['type'], 'function_call_output')

    def test_relative_paths_resolve_from_application_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # The loader's application root is the repository root; relative
            # output/taxonomy paths must not depend on the caller's cwd.
            cfg = get_paths_config({'paths': {
                'input_dir': 'project files',
                'output_csv': 'outputs/result.csv',
                'taxonomy_path': 'taxonomies/project.yaml',
            }})
            app_root = Path(__file__).resolve().parents[1]
            self.assertEqual(cfg.input_dir, (app_root / 'project files').absolute())
            self.assertEqual(cfg.output_csv, (app_root / 'outputs/result.csv').absolute())
            self.assertEqual(cfg.taxonomy_path, str((app_root / 'taxonomies/project.yaml').absolute()))

    def test_connection_endpoints(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            with patch.object(server, 'ROOT', root), patch.object(server, 'CONFIG_PATH', root / 'config.yaml'), patch.object(server, 'SAVED_CONFIGS_PATH', root / 'saved.json'):
                client = server.app.test_client()
                cfg = {'processing': {'provider': 'claude', 'base_url': 'https://api.anthropic.com/v1/chat/completions', 'model': 'test-model'}}
                self.assertEqual(client.post('/save-config', json=cfg).status_code, 200)
                self.assertEqual(client.get('/load-config').json['processing']['base_url'], 'https://api.anthropic.com/v1')
                self.assertEqual(client.post('/test-connection', json=cfg).status_code, 400)
                self.assertEqual(client.post('/save-apikey', json={'provider': 'claude', 'key': 'test-secret'}).status_code, 200)
                self.assertFalse(client.get('/apikey-status?provider=openrouter').json['set'])
                self.assertNotIn('test-secret', client.get('/apikey-status?provider=claude').text)
                self.assertNotIn('test-secret', (root / 'config.yaml').read_text())
                response = Mock(status_code=200)
                response.json.return_value = {'choices': [{'message': {'content': 'OK'}}]}
                with patch.object(server.http_requests, 'post', return_value=response) as post:
                    self.assertTrue(client.post('/test-connection', json=cfg).json['ok'])
                    self.assertEqual(post.call_args.args[0], 'https://api.anthropic.com/v1/chat/completions')
                    self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer test-secret')
                    response.status_code = 401
                    self.assertEqual(client.post('/test-connection', json=cfg).status_code, 400)
                self.assertEqual(client.post('/save-apikey', json={'provider': 'bad', 'key': 'x'}).status_code, 400)
                self.assertEqual(client.post('/save-apikey', json={'provider': 'claude', 'key': 'x\nBAD=y'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
