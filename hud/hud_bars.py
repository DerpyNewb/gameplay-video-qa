"""Read HUD bars (health, stamina, boss...) off every frame of a gameplay recording.

Usage: python hud/hud_bars.py <video> <layout.json> <out.csv>
Needs FFmpeg and ffprobe on PATH. Python standard library only.

Bars without numbers can still be measured: each value is the filled fraction of the bar's
track (0.0-1.0), read from pixels. It is a bar-length reading, not an HP value. A value is left
empty when the bar cannot be read (hidden, or washed out by bloom) and the note column says why.

layout.json names each bar, the pixel rows and columns of its track, and its fill colour:
  {"bars": {"health": {"rows": [207, 210], "cols": [147, 348], "fill": "red"}, ...}}
Find the rows and columns by opening one frame at full size; see hud/layout.example.json.
"""

import csv
import json
import subprocess
import sys


def colour(r, g, b):
    if r > 140 and g < 90 and b < 90:
        return 'red'
    if g > 120 and r < 110 and b < 110:
        return 'green'
    if b > 140 and r < 100 and g < 160:
        return 'blue'
    if r > 180 and g > 140 and b < 90:
        return 'yellow'
    if min(r, g, b) > 150 and max(r, g, b) - min(r, g, b) < 45:
        return 'track'
    return 'other'


def read_bar(frame, width, bar):
    (y0, y1), (x0, x1), fill = bar['rows'], bar['cols'], bar['fill']
    kinds = []
    for x in range(x0, x1 + 1):
        # average the bar's rows so one anti-aliased row does not decide the column
        r = g = b = 0
        for y in range(y0, y1 + 1):
            i = (y * width + x) * 3
            r, g, b = r + frame[i], g + frame[i + 1], b + frame[i + 2]
        n = y1 - y0 + 1
        kinds.append(colour(r // n, g // n, b // n))
    readable = sum(k in (fill, 'track') for k in kinds) / len(kinds)
    if readable < 0.6:
        return None, f'unreadable ({readable:.0%} of columns are bar colours)'
    # the fill runs from the left edge; allow gaps of up to 3 columns (anti-aliasing, sparks)
    end, gap = -1, 0
    for i, k in enumerate(kinds):
        if k == fill:
            end, gap = i, 0
        else:
            gap += 1
            if gap > 3 and (end >= 0 or i > 5):
                break
    return round((end + 1) / len(kinds), 4), ''


def probe(video):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,avg_frame_rate', '-of', 'json', video],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    num, den = s['avg_frame_rate'].split('/')
    return s['width'], s['height'], int(num) / int(den)


def measure(video, layout, out):
    bars = json.load(open(layout, encoding='utf-8'))['bars']
    width, height, fps = probe(video)
    size = width * height * 3
    proc = subprocess.Popen(['ffmpeg', '-v', 'error', '-nostdin', '-i', video, '-map', '0:v:0',
                             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    with open(out, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['frame', 'seconds', *(f'{name}_fill' for name in bars), 'note'])
        index = 0
        while True:
            frame = proc.stdout.read(size)
            if len(frame) < size:
                break
            values, notes = [], []
            for name, bar in bars.items():
                value, note = read_bar(frame, width, bar)
                values.append('' if value is None else value)
                if note:
                    notes.append(f'{name} {note}')
            writer.writerow([index, round(index / fps, 3), *values, '; '.join(notes)])
            index += 1
    if proc.wait():
        sys.exit('ffmpeg failed')
    return index


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    print(f'{measure(*sys.argv[1:])} frames -> {sys.argv[3]}')
