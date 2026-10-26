#!/usr/bin/env python3
"""Render the README's plain SVG diagrams and chart from stored study results.

No image-generation services or network access. Run from any directory.
"""
import json
from pathlib import Path
from clean_metadata import clean_file

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator, FormatStrFormatter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

COVER = '''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="340" viewBox="0 0 1280 340" role="img" aria-labelledby="title desc">
<title id="title">Using Game Theory to Detect Fraud in AI-Assisted Banking</title>
<desc id="desc">Evidence Dependencies, Audit Disclosure, and Robust Verification in Agent-Assisted Banking. A theoretical working paper with synthetic experiments.</desc>
<rect x="1" y="1" width="1278" height="338" rx="4" fill="#ffffff" stroke="#d0d7de" stroke-width="2"/>
<g font-family="Arial, Helvetica, sans-serif">
 <text x="52" y="48" fill="#57606a" font-size="17">Working paper · Game theory and AI security</text>
 <text x="50" y="112" fill="#24292f" font-family="Georgia, 'Times New Roman', serif" font-size="53" font-weight="700">Using Game Theory to Detect Fraud</text>
 <text x="50" y="176" fill="#24292f" font-family="Georgia, 'Times New Roman', serif" font-size="53" font-weight="700">in AI-Assisted Banking</text>
 <text x="52" y="231" fill="#424a53" font-size="24">Evidence dependencies, audit disclosure, and robust verification</text>
 <path d="M52 267H1228" stroke="#d0d7de" stroke-width="1"/>
 <text x="52" y="306" fill="#57606a" font-size="19">Mathematical analysis · Synthetic experiments · Reproducible code</text>
</g>
</svg>
'''


def evidence_map():
    parts = ['''<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="460" viewBox="0 0 1280 460" role="img" aria-labelledby="title desc">
<title id="title">Evidence sources behind the checks</title>
<desc id="desc">Left: three checks reuse one source's reveal outcome. Right: three checks access three distinct sources, whose dependencies must still be modeled.</desc>
<rect x="1" y="1" width="1278" height="458" rx="4" fill="#ffffff" stroke="#d0d7de" stroke-width="2"/>
<g font-family="Arial, Helvetica, sans-serif">
<text x="42" y="54" font-size="30" font-weight="600" fill="#24292f">Evidence sources behind the checks</text>
<text x="42" y="87" font-size="20" fill="#57606a">Several checks can reuse the same information.</text>
<path d="M640 119V391" stroke="#d0d7de" stroke-width="1"/>
<text x="331" y="151" text-anchor="middle" font-size="23" font-weight="600" fill="#24292f">Repeated evidence</text>
<text x="949" y="151" text-anchor="middle" font-size="23" font-weight="600" fill="#24292f">Distinct sources</text>
''']
    for panel_x in (58, 676):
        centers = [panel_x + 80, panel_x + 273, panel_x + 466]
        for center in centers:
            target = centers[1] if panel_x == 58 else center
            parts.append(f'<path d="M{center} 236V260H{target}V284" fill="none" stroke="#6e7781" stroke-width="2"/>')
        for i, center in enumerate(centers):
            parts.append(f'<rect x="{center-80}" y="186" width="160" height="50" rx="4" fill="#ffffff" stroke="#8c959f" stroke-width="1.5"/>')
            parts.append(f'<text x="{center}" y="218" text-anchor="middle" font-size="21" fill="#24292f">Check {chr(65+i)}</text>')
        source_centers = [centers[1]] if panel_x == 58 else centers
        for i, center in enumerate(source_centers):
            label = 'Same source' if panel_x == 58 else f'Source {i+1}'
            parts.append(f'<rect x="{center-80}" y="284" width="160" height="50" rx="4" fill="#f6f8fa" stroke="#6e7781" stroke-width="1.5"/>')
            parts.append(f'<text x="{center}" y="316" text-anchor="middle" font-size="21" fill="#24292f">{label}</text>')
        caption = '3 checks / 1 reveal outcome' if panel_x == 58 else '3 checks / 3 evidence sources'
        parts.append(f'<text x="{centers[1]}" y="376" text-anchor="middle" font-size="20" fill="#57606a">{caption}</text>')
    parts.append('''<path d="M42 406H1238" stroke="#d0d7de" stroke-width="1"/>
<text x="42" y="438" font-size="19" fill="#57606a">Different sources can still fail together. Their dependencies belong in the model.</text>
</g></svg>
''')
    return ''.join(parts)


def results_chart():
    summary = json.loads((ROOT / 'results/extended/summary.json').read_text())
    rows = summary['policies']
    names = [r['policy'] for r in rows]
    values = [r['mean_normalized_envelope_loss'] for r in rows]
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'svg.fonttype': 'none',
                         'svg.hashsalt': 'ai-heist-readme', 'font.size': 12})
    background, ink, muted = '#ffffff', '#24292f', '#57606a'
    fig, ax = plt.subplots(figsize=(12.8, 6.7), facecolor=background)
    fig.subplots_adjust(left=.325, right=.92, top=.79, bottom=.25)
    ax.set_facecolor(background)
    colors = ['#b0b6bc'] * (len(rows)-1) + ['#4d5660']
    ax.barh(range(len(rows)), values, height=.56, color=colors, zorder=3)
    ax.set_yticks(range(len(rows)), names, fontsize=12.5, color=ink)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_locator(MultipleLocator(.2))
    ax.xaxis.set_major_formatter(FormatStrFormatter('%.1f'))
    ax.tick_params(axis='x', colors=muted, labelsize=11, length=4, pad=8)
    ax.tick_params(axis='y', length=0, pad=13)
    ax.set_axisbelow(True)
    ax.grid(axis='x', color='#e3e6e8', linewidth=.7)
    for side, spine in ax.spines.items():
        spine.set_visible(side == 'bottom')
        spine.set_color('#afb8c1')
        spine.set_linewidth(.7)
    for i, value in enumerate(values):
        ax.text(value+.018, i, f'{value:.3f}', va='center', fontsize=12.5,
                fontweight='bold' if i==len(rows)-1 else 'normal', color=ink)
    fig.text(.045, .925, 'Comparison of audit policies', color=ink, fontsize=22, weight='semibold')
    fig.text(.045, .866, '600 synthetic settings · Mean normalized worst-case loss within the design scenarios',
             color=muted, fontsize=12)
    ax.set_xlabel('Loss relative to the largest route value in each setting · Lower is better',
                  color=muted, fontsize=11, labelpad=13)
    fig.text(.045, .09, 'The darker bar marks the policy that optimizes this objective.', color=ink, fontsize=11.5)
    fig.text(.045, .046, 'Outside the design scenarios, it loses to nominal optimization in 271 of 600 settings.',
             color=muted, fontsize=11.5)
    fig.savefig(ASSETS / 'results-overview.svg', facecolor=background,
                metadata={'Date': None, 'Creator': None, 'Format': None, 'Type': None})
    plt.close(fig)


if __name__ == '__main__':
    (ASSETS / 'cover.svg').write_text(COVER, encoding='utf-8')
    (ASSETS / 'evidence-map.svg').write_text(evidence_map(), encoding='utf-8')
    results_chart()
    for path in ASSETS.glob('*.svg'):
        clean_file(path)
    print(f'Rendered 3 light-theme SVG assets in {ASSETS}')
