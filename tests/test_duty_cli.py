import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('duty_cli', ROOT / 'duty.py')
duty = importlib.util.module_from_spec(spec)
spec.loader.exec_module(duty)


class FakeGitHub:
    def __init__(self):
        self.calls = []

    def call(self, name, args):
        self.calls.append((name, args))
        return 'https://github.com/test/shop/pull/12'


class DutyCliTests(unittest.TestCase):
    def test_dry_pr_does_not_write(self):
        gh = FakeGitHub()
        with patch.object(duty, 'MODE', 'dry'):
            number = duty.open_pr(gh, {'number': 1, 'title': 'Promo'},
                                  {'files': {'shop/cart.py': 'code'}, 'report': 'fixed'})
        self.assertIsNone(number)
        self.assertEqual(gh.calls, [])

    def test_declined_confirmation_stops_pr_before_first_write(self):
        gh = FakeGitHub()
        with patch.object(duty, 'MODE', 'ask'), patch('builtins.input', return_value='n'), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(RuntimeError):
                duty.open_pr(gh, {'number': 1, 'title': 'Promo'},
                             {'files': {'shop/cart.py': 'code'}, 'report': 'fixed'})
        self.assertEqual(gh.calls, [])

    def test_confirmed_write_shows_full_file_before_sending(self):
        gh = FakeGitHub()
        content = 'x' * 400 + 'review-this-tail'
        output = io.StringIO()
        with patch.object(duty, 'MODE', 'ask'), patch('builtins.input', return_value='y'), contextlib.redirect_stdout(output):
            duty.gh_write(gh, 'push_files', {'branch': 'fix/issue-1', 'files': [{'path': 'shop/cart.py', 'content': content}]})
        self.assertIn('review-this-tail', output.getvalue())
        self.assertEqual(gh.calls[0][1]['files'][0]['content'], content)

    def test_runtime_check_never_calls_models(self):
        with patch.object(duty, 'configure'), patch.object(duty, 'check_runtime', return_value={'issues': 10}), patch.object(duty, 'chat', side_effect=AssertionError('Paid call')), patch.object(duty, 'on_duty', side_effect=AssertionError('Agent run')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(duty.main(['--check']), 0)

    def test_run_saves_one_result_csv_without_old_call_metrics(self):
        frame = duty.pd.DataFrame([{'состав': 'tmp', 'задача': 1, 'триаж': 'bug', 'проверки': True, 'приёмка': True}])
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(duty, 'ROOT', Path(tmp)), patch.object(duty, 'configure'), patch.object(duty, 'on_duty', return_value=frame), patch.object(duty, 'CALLS', [{'tag': 'old|#1|coder', 'prompt': 9000, 'completion': 1, 'latency_s': 99}]), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(duty.main(['--mode', 'dry', '--team', 'команда']), 0)
            saved = list((Path(tmp) / 'results').glob('run_*.csv'))
            self.assertEqual(len(saved), 1)
            result = duty.pd.read_csv(saved[0])
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]['вызовов'], 0)
            self.assertEqual(result.iloc[0]['токенов'], 0)

    def test_seed_rebuilt_from_issue_titles_without_local_seed_file(self):
        issues = [{'number': 1, 'title': 'Promo'}, {'number': 2, 'title': 'Question'}]
        truth = [{'key': 'promo', 'title': 'Promo', 'kind': 'bug'}, {'key': 'question', 'title': 'Question', 'kind': 'question'}]
        self.assertEqual(duty.match_seed(issues, truth), {'promo': 1, 'question': 2})

    def test_pr_does_not_claim_an_unperformed_review(self):
        gh = FakeGitHub()
        with patch.object(duty, 'MODE', 'ask'), patch('builtins.input', return_value='y'), contextlib.redirect_stdout(io.StringIO()):
            duty.open_pr(gh, {'number': 1, 'title': 'Promo'},
                         {'files': {'shop/cart.py': 'code'}, 'report': 'fixed'})
        body = next(args['body'] for name, args in gh.calls if name == 'create_pull_request')
        self.assertNotIn('ревьюер одобрил', body)
        self.assertIn('тесты проходят', body)

    def test_help_works_without_configured_credentials(self):
        env = {key: value for key, value in os.environ.items() if key not in {'GITHUB_TOKEN', 'GITHUB_REPO', 'OPENROUTER_API_KEY'}}
        result = subprocess.run([sys.executable, str(ROOT / 'duty.py'), '--help'], cwd='/private/tmp', env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--check', result.stdout)
        self.assertIn('--mode', result.stdout)


if __name__ == '__main__':
    unittest.main()
