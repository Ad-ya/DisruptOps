"""Credentials remain outside prompts, checkpoint state and public error messages."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from supply_chain_poc.integration.environment import load_google_key, public_error


class EnvironmentTests(unittest.TestCase):
    def test_only_google_key_names_load_and_existing_environment_wins(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / '.env'
            filename.write_text('GOOGLE_API_KEY="synthetic-file-key"\nUNRELATED_VARIABLE=ignored\n')
            with patch.dict(os.environ, {'GOOGLE_API_KEY': 'synthetic-existing'}, clear=True):
                self.assertTrue(load_google_key(filename))
                self.assertEqual(os.environ['GOOGLE_API_KEY'], 'synthetic-existing')
                self.assertNotIn('UNRELATED_VARIABLE', os.environ)
            with patch.dict(os.environ, {'GEMINI_API_KEY': 'synthetic-existing'}, clear=True):
                self.assertTrue(load_google_key(filename))
                self.assertNotIn('GOOGLE_API_KEY', os.environ)
            with patch.dict(os.environ, {}, clear=True):
                self.assertTrue(load_google_key(filename))
                self.assertEqual(os.environ['GOOGLE_API_KEY'], 'synthetic-file-key')

    def test_errors_do_not_expose_google_key_values(self):
        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'synthetic-sensitive-value'}):
            self.assertNotIn('synthetic-sensitive-value', public_error(ValueError('synthetic-sensitive-value')))
            self.assertNotIn('synthetic-sensitive-value', public_error(RuntimeError('synthetic-sensitive-value')))
