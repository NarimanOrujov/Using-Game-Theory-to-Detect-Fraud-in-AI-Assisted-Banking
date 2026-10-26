#!/usr/bin/env python3
"""Reproduce the main synthetic study and build the paper's PDF."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from clean_metadata import clean_file
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--skip-compute', action='store_true',
                    help='Build from the included results without rerunning the study.')
args = parser.parse_args()
os.chdir(ROOT)
os.environ.setdefault('MPLCONFIGDIR', str(Path(tempfile.gettempdir()) / 'ai-heist-matplotlib'))
logs = ROOT / 'results' / 'build'
logs.mkdir(parents=True, exist_ok=True)
steps = []
if not args.skip_compute:
    steps.append(('extended', [sys.executable, 'analysis/evidence_audit.py']))
tex = ['pdflatex', '-interaction=nonstopmode', '-halt-on-error', 'using_game_theory_to_detect_fraud_in_ai_assisted_banking.tex']
steps += [('latex1', tex), ('bibtex', ['bibtex', 'using_game_theory_to_detect_fraud_in_ai_assisted_banking']),
          ('latex2', tex), ('latex3', tex)]
for name, command in steps:
    with (logs / (name + '.log')).open('w') as stream:
        try:
            run = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            raise SystemExit(f'Missing tool: {command[0]}. See README.md for prerequisites.')
    if run.returncode:
        raise SystemExit(f'{name} failed: inspect {logs / (name + ".log")}')
    print(name + ': passed', flush=True)
text = (ROOT / 'using_game_theory_to_detect_fraud_in_ai_assisted_banking.log').read_text()
for error in ('There were undefined references', 'Overfull \\hbox', 'Citation `'):
    if error in text:
        raise SystemExit('Review LaTeX log: ' + error)
print('PDF built; no undefined references or overflowing horizontal boxes.')

clean_file(ROOT/'using_game_theory_to_detect_fraud_in_ai_assisted_banking.pdf')
print('Embedded PDF metadata removed.')
