"""Chart HUD bar telemetry of one to three recordings as an SVG, one panel per bar.

Usage: python hud/hud_chart.py <out.svg> --bars boss,health --series "Agent run=hud_agent.csv"
           [--series "Reference=hud_ref.csv"] [--annotations annotations.json]
annotations.json (optional): {"bands": [{"bar": "boss", "start": 67.8, "end": 68.9, "label": "BUG-01",
                                         "row": 1, "anchor": "start"}],
                              "marks": [{"bar": "health", "t": 61.6, "label": "Player dies"}]}
Values are bar-length fractions from hud_bars.py, not HP.
"""
import argparse
import csv
import json
from pathlib import Path

# first three slots of a colour-blind-checked categorical palette; more series than this stop being distinguishable
COLOURS = ['#2a78d6', '#eb6834', '#1baf7a']
W, LEFT, RIGHT, TOP, PANEL, GAPY, BOTTOM = 1000, 64, 150, 34, 190, 58, 44
INK, INK2, GRID, SURFACE, BAND = '#0b0b0b', '#52514e', '#e4e3df', '#fcfcfb', '#f0efec'


def esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def chart(out, bars, series, notes):
    data = [(name, list(csv.DictReader(open(path, encoding='utf-8'))), colour)
            for (name, path), colour in zip(series, COLOURS)]
    t_max = max(float(rows[-1]['seconds']) for _, rows, _ in data)
    x = lambda t: LEFT + t / t_max * (W - LEFT - RIGHT)
    height = TOP + len(bars) * (PANEL + GAPY) - GAPY + BOTTOM
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" '
           f'font-family="Segoe UI, Arial, sans-serif" role="img" aria-label="HUD bars over time">',
           f'<rect width="{W}" height="{height}" fill="{SURFACE}"/>']
    for p, bar in enumerate(bars):
        top = TOP + p * (PANEL + GAPY)
        y = lambda v: top + (1 - v) * PANEL
        svg.append(f'<text x="{LEFT}" y="{top - 12}" font-size="14" font-weight="600" fill="{INK}">{esc(bar.capitalize())} bar, fraction of bar length</text>')
        bands = [b for b in notes.get('bands', []) if b['bar'] == bar]
        for b in bands:  # all rects before any label, so no band covers a label
            svg.append(f'<rect x="{x(b["start"]):.1f}" y="{top}" width="{x(b["end"]) - x(b["start"]):.1f}" height="{PANEL}" fill="{BAND}"/>')
        for b in bands:
            anchor = b.get('anchor', 'middle')
            lx = {'start': x(b['start']) + 3, 'middle': (x(b['start']) + x(b['end'])) / 2, 'end': x(b['end']) - 3}[anchor]
            svg.append(f'<text x="{lx:.1f}" y="{top + 14 * b.get("row", 1)}" font-size="11" fill="{INK2}" text-anchor="{anchor}">{esc(b["label"])}</text>')
        for v in (0, 0.25, 0.5, 0.75, 1):
            svg.append(f'<line x1="{LEFT}" x2="{W - RIGHT}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{GRID}" stroke-width="1"/>')
            svg.append(f'<text x="{LEFT - 8}" y="{y(v) + 4:.1f}" font-size="11" fill="{INK2}" text-anchor="end">{v:.0%}</text>')
        labels = []
        for name, rows, colour in data:
            points = [(float(r['seconds']), float(r[f'{bar}_fill'])) for r in rows if r.get(f'{bar}_fill')]
            if not points:
                continue
            d, prev = [], None
            for t, v in points:  # step line: the bar holds its value until the next change
                d.append(f'M{x(t):.1f},{y(v):.1f}' if prev is None else f'H{x(t):.1f}V{y(v):.1f}' if v != prev else '')
                prev = v
            d.append(f'H{x(points[-1][0]):.1f}')
            svg.append(f'<path d="{"".join(d)}" fill="none" stroke="{colour}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
            t, v = points[-1]
            svg.append(f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="4.5" fill="{colour}" stroke="{SURFACE}" stroke-width="2"/>')
            labels.append([y(v), x(t), f'{name} {v:.0%}'])
        labels.sort()
        for i in range(1, len(labels)):  # keep end labels 14 px apart
            labels[i][0] = max(labels[i][0], labels[i - 1][0] + 14)
        for ly, lx, text in labels:
            svg.append(f'<text x="{lx + 9:.1f}" y="{ly + 4:.1f}" font-size="11.5" fill="{INK}">{esc(text)}</text>')
        for m in (m for m in notes.get('marks', []) if m['bar'] == bar):
            svg.append(f'<line x1="{x(m["t"]):.1f}" x2="{x(m["t"]):.1f}" y1="{top}" y2="{top + PANEL}" stroke="{INK2}" stroke-width="1"/>')
            svg.append(f'<text x="{x(m["t"]) - 6:.1f}" y="{top + PANEL - 8}" font-size="11" fill="{INK2}" text-anchor="end">{esc(m["label"])}</text>')
    base = TOP + len(bars) * (PANEL + GAPY) - GAPY
    step = 10 if t_max > 30 else 5
    for t in range(0, int(t_max) + 1, step):
        svg.append(f'<text x="{x(t):.1f}" y="{base + 18}" font-size="11" fill="{INK2}" text-anchor="middle">{t} s</text>')
    for i, (name, _, colour) in enumerate(data):  # legend: always shown for two or more series
        if len(data) > 1:
            lx = LEFT + i * 150
            svg.append(f'<line x1="{lx}" x2="{lx + 18}" y1="{base + 36}" y2="{base + 36}" stroke="{colour}" stroke-width="2"/>')
            svg.append(f'<text x="{lx + 24}" y="{base + 40}" font-size="11.5" fill="{INK}">{esc(name)}</text>')
    svg.append('</svg>')
    Path(out).write_text('\n'.join(svg), encoding='utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out')
    ap.add_argument('--bars', required=True, help='comma-separated bar names from the layout, e.g. boss,health')
    ap.add_argument('--series', action='append', required=True, help='"Label=path/to/hud.csv"; up to three')
    ap.add_argument('--annotations', help='optional JSON with bands and marks')
    a = ap.parse_args()
    if len(a.series) > len(COLOURS):
        ap.error(f'at most {len(COLOURS)} series; split into several charts')
    chart(a.out, a.bars.split(','), [s.split('=', 1) for s in a.series],
          json.load(open(a.annotations, encoding='utf-8')) if a.annotations else {})
    print('wrote', a.out)
