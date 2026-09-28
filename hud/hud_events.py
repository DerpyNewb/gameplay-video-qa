"""Turn hud_bars.py CSVs into events: every drop of every bar, and every time a bar sits empty.

Usage: python hud/hud_events.py <out.json> <label>=<hud.csv> [<label>=<hud.csv> ...]
e.g.   python hud/hud_events.py output/events.json agent=output/hud_agent.csv reference=output/hud_ref.csv

A drop counts only if the bar stays lower for 3 frames, so one-pixel edge flicker is ignored.
Drops closer together than GAP seconds merge into one event (one hit animating over frames).
"""
import csv
import json
import sys

GAP = 0.5         # s between steps that still count as one event
MIN_STEP = 0.01   # fraction of the bar; about two pixels of a 200 px bar
EMPTY = 0.03      # at or below this the bar counts as empty


def drops(points):
    events, level = [], points[0][1]
    for i, (t, v) in enumerate(points):
        ahead = [p[1] for p in points[i:i + 3]]
        if level - max(ahead) >= MIN_STEP:
            new = max(ahead)
            if events and t - events[-1]['end'] <= GAP:
                events[-1].update(end=t, to=new)
            else:
                events.append({'start': t, 'end': t, 'from': level, 'to': new})
            level = new
        elif min(ahead) - level >= MIN_STEP:
            level = min(ahead)  # refill, or flicker settling upward
    for e in events:
        e['loss'] = round(e['from'] - e['to'], 4)
    return events


def empty_runs(points, min_len=0.2):
    runs, start, step = [], None, points[1][0] - points[0][0] if len(points) > 1 else 0.1
    for t, v in points + [(points[-1][0] + step, 1.0)]:
        if v <= EMPTY and start is None:
            start = t
        elif v > EMPTY and start is not None:
            if t - start >= min_len - 1e-9:
                runs.append({'start': start, 'end': round(t - step, 3)})
            start = None
    return runs


def events_for(path):
    rows = list(csv.DictReader(open(path, encoding='utf-8')))
    out = {'frames': len(rows)}
    for col in (c for c in rows[0] if c.endswith('_fill')):
        points = [(float(r['seconds']), float(r[col])) for r in rows if r[col] != '']
        if not points:
            continue
        bar = col[:-5]
        out[bar] = {'first_readable_s': points[0][0], 'final_fill': points[-1][1],
                    'drops': drops(points), 'empty': empty_runs(points)}
    return out


if __name__ == '__main__':
    if len(sys.argv) < 3 or any('=' not in a for a in sys.argv[2:]):
        sys.exit(__doc__)
    result = {label: events_for(path) for label, path in (a.split('=', 1) for a in sys.argv[2:])}
    json.dump(result, open(sys.argv[1], 'w', encoding='utf-8'), indent=1)
    for label, bars in result.items():
        print(label, {b: (len(v['drops']), len(v['empty'])) for b, v in bars.items() if b != 'frames'}, '(drops, empty runs)')
