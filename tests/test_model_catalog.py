import os
import unittest
from unittest.mock import Mock, patch
from server import config_server as server


class ModelCatalogTests(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()

    def test_supported_providers(self):
        providers = self.client.get('/api/providers').json
        self.assertEqual(set(providers), {'openai', 'openrouter', 'gemini', 'claude', 'codex'})
        for details in providers.values():
            self.assertTrue(details['key_url'].startswith('https://'))
            self.assertTrue(details['docs_url'].startswith('https://'))

    def test_shortlists_are_tested_and_tiered_without_network_or_key(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(server.http_requests, 'get') as get:
            defaults = self.client.get('/api/providers').json
            for provider in defaults:
                response = self.client.get('/api/recommended-models?provider=' + provider)
                self.assertEqual(response.status_code, 200)
                models = response.json['models']
                self.assertEqual(len({m['id'] for m in models}), len(models))
                self.assertGreaterEqual(len(models), 1)
                self.assertIn(defaults[provider]['model'], [m['id'] for m in models])
                budget = [m for m in models if m['tier'] == 'budget']
                higher = [m for m in models if m['tier'] == 'higher']
                self.assertEqual(len(budget) + len(higher), len(models))
                self.assertTrue(all(m['vision_listed'] for m in models))
                if provider != 'openrouter':
                    self.assertTrue(all(m['chat_tested_on'] is None for m in models))
                self.assertTrue(all(not m.get('region_blocked') or m['chat_tested_on'] is None for m in models))
            self.assertEqual(self.client.get('/api/recommended-models?provider=custom').status_code, 400)
            get.assert_not_called()

    def test_fixed_endpoint_key_isolation_and_catalog(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data': [{'id': 'z'}, {'id': 'a', 'name': 'A'}, {'id': 'z'}, {'bad': True}, {'id': 'image', 'architecture': {'output_modalities': ['image']}}]}
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'gemini-secret', 'OPENROUTER_API_KEY': 'or-secret'}, clear=True), patch.object(server.http_requests, 'get', return_value=response) as get:
            result = self.client.post('/api/models', json={'provider': 'gemini', 'base_url': 'https://untrusted.invalid'})
            self.assertEqual(result.status_code, 200)
            self.assertEqual([m['id'] for m in result.json['models']], ['a', 'z'])
            self.assertEqual(get.call_args.args[0], 'https://generativelanguage.googleapis.com/v1beta/openai/models')
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer gemini-secret')
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertNotIn('secret', result.text)
            self.client.post('/api/models', json={'provider': 'openrouter', 'key': 'unsaved'})
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer unsaved')
            self.assertEqual(os.environ['OPENROUTER_API_KEY'], 'or-secret')

    def test_failures_are_actionable_and_sanitized(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(server.http_requests, 'get') as get:
            self.assertEqual(self.client.post('/api/models', json={'provider': 'gemini'}).status_code, 400)
            self.assertEqual(self.client.post('/api/models', json={'provider': 'custom'}).status_code, 400)
            get.assert_not_called()
            for response in [Mock(status_code=401), Mock(status_code=200)]:
                response.json.return_value = {'unexpected': 'secret'}
                get.return_value = response
                result = self.client.post('/api/models', json={'provider': 'openrouter'})
                self.assertEqual(result.status_code, 400)
                self.assertNotIn('secret', result.text)
            get.return_value.json.side_effect = ValueError('secret HTML')
            self.assertEqual(self.client.post('/api/models', json={'provider': 'openrouter'}).status_code, 400)

    def test_openai_official_endpoint_and_key_isolation(self):
        response = Mock(status_code=200)
        response.json.return_value = {'data':[{'id':'gpt-4.1-mini'}]}
        with patch.dict(os.environ, {'OPENAI_API_KEY':'openai-test', 'OPENROUTER_API_KEY':'other-test'},clear=True), patch.object(server.http_requests,'get',return_value=response) as get:
            result=self.client.post('/api/models',json={'provider':'openai','base_url':'https://untrusted.invalid'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(get.call_args.args[0],'https://api.openai.com/v1/models')
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'],'Bearer openai-test')
            self.assertNotIn('openai-test',result.text)
            shortlist=self.client.get('/api/recommended-models?provider=openai')
            self.assertEqual(shortlist.status_code,200)
            self.assertEqual(shortlist.json['models'][0]['id'],'gpt-4.1-mini')
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'other-test'},clear=True), patch.object(server.http_requests,'get') as get:
            self.assertEqual(self.client.post('/api/models',json={'provider':'openai'}).status_code,400)
            get.assert_not_called()

    def test_claude_and_codex_official_model_lists(self):
        response = Mock(status_code=200)
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'claude-key', 'OPENAI_API_KEY': 'openai-key'}, clear=True), patch.object(server.http_requests, 'get', return_value=response) as get:
            response.json.return_value = {'data': [{'id': 'claude-sonnet-4-6', 'display_name': 'Claude Sonnet 4.6'}]}
            result = self.client.post('/api/models', json={'provider': 'claude'})
            self.assertEqual(result.json['models'][0]['name'], 'Claude Sonnet 4.6')
            self.assertEqual(get.call_args.args[0], 'https://api.anthropic.com/v1/models')
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer claude-key')
            response.json.return_value = {'data': [{'id': 'gpt-4.1-mini'}, {'id': 'gpt-5.1-codex'}]}
            result = self.client.post('/api/models', json={'provider': 'codex'})
            self.assertEqual(result.json['models'], [{'id': 'gpt-5.1-codex', 'name': 'gpt-5.1-codex'}])
            self.assertEqual(get.call_args.args[0], 'https://api.openai.com/v1/models')
            self.assertEqual(get.call_args.kwargs['headers']['Authorization'], 'Bearer openai-key')
