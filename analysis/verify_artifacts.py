#!/usr/bin/env python3
"""Check the GitHub package's stored results and paper without Word tools."""
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results' / 'extended'
manifest = json.loads((OUT / 'manifest.json').read_text())
for filename, digest in manifest.items():
    assert hashlib.sha256((OUT / filename).read_bytes()).hexdigest() == digest, filename
with (OUT / 'all_policy_results.csv').open() as f:
    rows = list(csv.DictReader(f))
with (OUT / 'sampling_results.csv').open() as f:
    samples = list(csv.DictReader(f))
summary = json.loads((OUT / 'summary.json').read_text())
assert len(rows) == 4200 and len(samples) == 300
assert len(json.loads((OUT / 'instances.json').read_text())) == 100
for item in summary['policies']:
    subset = [r for r in rows if r['policy'] == item['policy']]
    assert len(subset) == 600
    for field, column in [('mean_normalized_envelope_loss', 'normalized_envelope_loss'),
                          ('mean_normalized_outside_loss', 'normalized_outside_loss')]:
        assert abs(statistics.mean(float(r[column]) for r in subset) - item[field]) < 1e-12
robust = [r for r in rows if r['policy'] == 'Source-aware robust']
nominal = [r for r in rows if r['policy'] == 'Nominal minimax']
assert sum(float(r['outside_loss']) > float(n['outside_loss']) + 1e-7
           for r, n in zip(robust, nominal)) == 271
assert sum(int(r['robust_bound_exceeded_outside']) for r in robust) == 430
# Match the numerical acceptance tolerances used by the research code.
assert -1e-7 < summary['max_primal_dual_gap'] < 1e-7
assert summary['max_feasibility_error'] < 1e-8

tex = (ROOT / 'using_game_theory_to_detect_fraud_in_ai_assisted_banking.tex').read_text()
bib = (ROOT / 'references.bib').read_text()
keys = set(re.findall(r'@\w+\{([^,]+)', bib))
cited = {k for group in re.findall(r'\\cite\{([^}]+)\}', tex) for k in group.split(',')}
assert cited <= keys, cited - keys
log_path = ROOT / 'using_game_theory_to_detect_fraud_in_ai_assisted_banking.log'
if log_path.exists():
    log = log_path.read_text()
    assert 'There were undefined references' not in log
    assert 'Overfull \\hbox' not in log
try:
    pdftext = subprocess.check_output(['pdftotext', str(ROOT / 'using_game_theory_to_detect_fraud_in_ai_assisted_banking.pdf'), '-'], text=True)
except FileNotFoundError:
    raise SystemExit('Install pdftotext (Poppler) to check the paper. See README.md.')
assert '??' not in pdftext
assert 'Using Game Theory to Detect Fraud in AI-Assisted Banking' in ' '.join(pdftext.split())
report = {'manifest': 'passed', 'numeric_summaries': 'passed',
          'reference_keys': len(cited), 'pdf_text': 'passed',
          'latex_log': 'passed' if log_path.exists() else 'not present; rebuild to check'}
log_dir = ROOT / 'results' / 'build'
log_dir.mkdir(parents=True, exist_ok=True)
(log_dir / 'artifact_validation.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
