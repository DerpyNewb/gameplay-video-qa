"""Visual evidence from a gameplay recording, for a reviewer who looks at images, not video.

sheets  Contact sheets that together hold EVERY frame, each tile labelled with its video time.
        python evidence/evidence.py sheets <video> <out_dir> [--crop W:H:X:Y] [--cols 4] [--rows 5] [--tile-width 480]
        Writes sheet_001.jpg, sheet_002.jpg ... and sheets.csv (sheet -> first/last frame time).

shots   Full-resolution screenshots and before/during/after strips, labelled with an ID and time
        in a band ABOVE the frame so the label never covers the HUD.
        python evidence/evidence.py shots <spec.json> <out_dir>
        spec.json: {"videos": {"agent": {"path": "run.mp4", "crop": "1804:854:6:168", "label": "Agent run"}},
                    "shots": [{"id": "BUG-01", "video": "agent", "best": 68.2, "strip": [66.8, 67.8, 68.9]}]}
        Video paths are relative to the spec file. Writes <id>_<best>s.jpg and <id>_strip.jpg.

Needs FFmpeg and ffprobe on PATH. Set QA_FONT to a .ttf file if none of the usual fonts is found.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

FONTS = [os.environ.get('QA_FONT', ''), r'C:\Windows\Fonts\arialbd.ttf', r'C:\Windows\Fonts\arial.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf']


def font_dir():
    """Temp dir holding font.ttf: FFmpeg filter arguments cannot hold a Windows drive colon, so the
    font is referenced by a relative path and FFmpeg runs with this dir as its working directory."""
    font = next((f for f in FONTS if f and Path(f).is_file()), None)
    if not font:
        raise SystemExit('no font found; set QA_FONT to a .ttf file')
    work = tempfile.mkdtemp(prefix='qa-evidence-')
    shutil.copy(font, Path(work) / 'font.ttf')
    return work


def ffmpeg(*args, cwd=None):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args], check=True, cwd=cwd)


def fps_of(video):
    rate = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=avg_frame_rate',
                           '-of', 'csv=p=0', video], capture_output=True, text=True, check=True).stdout.strip()
    num, den = rate.split('/')
    return int(num) / int(den)


def sheets(video, out, crop=None, cols=4, rows=5, tile_width=480):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = font_dir()
    try:
        vf = (f'crop={crop},' if crop else '') + (
            f'scale={tile_width}:-2,drawbox=x=0:y=0:w=150:h=34:color=black@0.7:t=fill,'
            "drawtext=fontfile=font.ttf:fontsize=24:fontcolor=yellow:x=6:y=5:text='%{pts\\:hms}',"
            f'tile={cols}x{rows}:padding=4:color=white')
        (Path(work) / 'vf.txt').write_text(vf, encoding='utf-8')
        ffmpeg('-i', str(Path(video).resolve()), '-/vf', 'vf.txt', '-fps_mode', 'passthrough', '-q:v', '3',
               str(out / 'sheet_%03d.jpg'), cwd=work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    fps, per = fps_of(video), cols * rows
    made = sorted(out.glob('sheet_*.jpg'))
    with open(out / 'sheets.csv', 'w', newline='', encoding='utf-8') as h:
        w = csv.writer(h)
        w.writerow(['sheet', 'first_s', 'last_s'])
        for i, p in enumerate(made):
            w.writerow([p.name, round(i * per / fps, 3), round(((i + 1) * per - 1) / fps, 3)])
    return len(made)


def label(text, size):
    # the label goes in a band added above the frame, so it never covers the HUD
    band = int(size * 1.6)
    return (f"pad=iw:ih+{band}:0:{band}:black,"
            f"drawtext=fontfile=font.ttf:fontsize={size}:fontcolor=yellow:x=10:y={int(size * 0.3)}:text='{text}'")


def shots(spec_path, out):
    spec_path, out = Path(spec_path).resolve(), Path(out).resolve()
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    out.mkdir(parents=True, exist_ok=True)
    work = font_dir()
    try:
        for shot in spec['shots']:
            v = spec['videos'][shot['video']]
            path, crop = str((spec_path.parent / v['path']).resolve()), f"crop={v['crop']}," if v.get('crop') else ''
            grab = lambda t, vf, dest: ffmpeg('-ss', f'{t:.3f}', '-i', path, '-frames:v', '1', '-vf', vf, '-q:v', '2', str(dest), cwd=work)
            # drawtext treats ':' as a separator, so the label text uses none
            grab(shot['best'], crop + label(f"{shot['id']}   {v.get('label', shot['video'])}   {shot['best']:.1f} s", 30),
                 out / f"{shot['id']}_{shot['best']:.1f}s.jpg")
            tiles = []
            for i, t in enumerate(shot.get('strip', [])):
                tiles.append(Path(work) / f'tile{i}.jpg')
                grab(t, crop + 'scale=480:-2,' + label(f'{t:.1f} s', 22), tiles[-1])
            if len(tiles) > 1:
                inputs = [a for t in tiles for a in ('-i', str(t))]
                pads = ''.join(f'[{i}:v]pad=iw+6:ih:0:0:white[p{i}];' for i in range(len(tiles)))
                ffmpeg(*inputs, '-filter_complex', pads + ''.join(f'[p{i}]' for i in range(len(tiles))) + f'hstack=inputs={len(tiles)}',
                       '-q:v', '3', str(out / f"{shot['id']}_strip.jpg"))
            print(shot['id'], 'done')
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('sheets')
    s.add_argument('video'), s.add_argument('out')
    s.add_argument('--crop', help='W:H:X:Y of the game viewport inside the capture')
    s.add_argument('--cols', type=int, default=4), s.add_argument('--rows', type=int, default=5)
    s.add_argument('--tile-width', type=int, default=480)
    p = sub.add_parser('shots')
    p.add_argument('spec'), p.add_argument('out')
    a = ap.parse_args()
    if a.cmd == 'sheets':
        print(sheets(a.video, a.out, a.crop, a.cols, a.rows, a.tile_width), 'sheets ->', a.out)
    else:
        shots(a.spec, a.out)
