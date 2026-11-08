"""Экспортировать учебный магазин в отдельную папку, не перезаписывая существующую."""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / 'workspace/romashka')
    parser.add_argument('--no-git', action='store_true', help='не создавать Git-репозиторий')
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists() or destination.is_symlink():
        parser.error(f'{destination} already exists; no files were changed')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.romashka-', dir=destination.parent) as tmp:
        staged = Path(tmp) / 'repo'
        shutil.copytree(ROOT / 'template', staged,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.env', '.git', '.DS_Store'))
        if not args.no_git:
            subprocess.run(['git', 'init', '-b', 'main', str(staged)], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(staged), 'add', '.'], check=True)
            subprocess.run(['git', '-C', str(staged), 'commit', '-m', 'Initial Romashka exercise'],
                           check=True, capture_output=True)
        staged.rename(destination)
    print(f'Ready: {destination}')
    print(f'Tests: cd "{destination}" && python3 -m unittest discover -s tests -v')


if __name__ == '__main__':
    main()
