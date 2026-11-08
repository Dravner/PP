"""Проверить исходный учебный стенд без GitHub и вызовов моделей."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': str(ROOT / 'template')}
    for cwd, tests in [(ROOT / 'template', 'tests'), (ROOT, 'tests')]:
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', tests, '-v'],
                                cwd=cwd, env=env, capture_output=True, text=True)
        print(result.stderr)
        if result.returncode:
            return result.returncode
    issues = json.loads((ROOT / 'data/issues.json').read_text())
    bugs = [issue for issue in issues if issue['kind'] == 'bug']
    if len(issues) < 8 or len(bugs) < 4:
        raise SystemExit('Not enough issues or bugs')
    rows = []
    for bug in bugs:
        key = bug['key']
        test = ROOT / 'data/acceptance' / f'{key}.py'
        result = subprocess.run([sys.executable, str(test)], cwd=ROOT / 'template',
                                env=env, capture_output=True, text=True)
        intended = ('ValueError: unknown promo code' in result.stderr if key == 'promo-case'
                    else 'AssertionError' in result.stderr)
        valid = result.returncode == 1 and intended and 'ModuleNotFoundError' not in result.stderr
        rows.append({'key': key, 'reproduced': valid, 'exit_code': result.returncode})
        print(f'{key}: {"expected defect reproduced" if valid else "UNEXPECTED RESULT"}')
        if not valid:
            print(result.stderr)
    report = {'issues': len(issues), 'bugs': len(bugs), 'baseline': rows,
              'note': 'Reconstructed exercise, not an agent evaluation; acceptance is outside target repo.'}
    out = ROOT / 'results/preparation_check.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if not all(row['reproduced'] for row in rows):
        return 1
    print(f'OK: {len(issues)} issues; {len(bugs)} intended defects reproduced. Report: {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
