"""Create a new synthetic Git repository with a deliberately regressed average."""

import argparse
import json
import os
from pathlib import Path
import subprocess

BASE = 'def average(values):\n    if not values:\n        return 0\n    return sum(values) / len(values)\n'
HEAD = 'def average(values):\n    return sum(values) / len(values)\n'


def make_repo(path, before=BASE, after=HEAD):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=False)
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_AUTHOR_NAME': 'Synthetic Fixture', 'GIT_COMMITTER_NAME': 'Synthetic Fixture',
                'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
                'GIT_AUTHOR_DATE': '2026-11-19T12:00:00+00:00', 'GIT_COMMITTER_DATE': '2026-11-19T12:00:00+00:00'})
    def git(*args):
        return subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'commit.gpgsign=false',
                               *args], cwd=path, env=env, check=True, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    git('init', '-b', 'main')
    source = path / 'calc.py'
    source.write_text(before, encoding='utf-8')
    git('add', 'calc.py'); git('commit', '-m', 'Synthetic baseline')
    base = git('rev-parse', 'HEAD')
    source.write_text(after, encoding='utf-8')
    git('add', 'calc.py'); git('commit', '-m', 'Synthetic change')
    return {'base': base, 'head': git('rev-parse', 'HEAD')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(make_repo(args.destination), indent=2))
