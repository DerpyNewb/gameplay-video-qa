"""Tests for the HUD, evidence and report tools, on a synthetic clip with a known bar drop.

Run: python -m unittest -v   (needs FFmpeg and ffprobe on PATH)
"""
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / 'report'))
import report2pdf  # noqa: E402


def run(*args):
    return subprocess.run([sys.executable, *map(str, args)], check=True, capture_output=True, text=True).stdout


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp(prefix='qa-tools-test-'))
        cls.video = cls.dir / 'bar.mkv'
        # 2 s at 10 fps: a 200 px red bar on a light grey track, full for 1 s, then half
        seg = ("color=c=0x303030:s=320x200:r=10:d=1,drawbox=x=20:y=20:w=200:h=5:color=0xC8C8C8:t=fill,"
               "drawbox=x=20:y=20:w={w}:h=5:color=0xE01010:t=fill")
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', seg.format(w=200), '-f', 'lavfi', '-i', seg.format(w=100),
                        '-filter_complex', '[0:v][1:v]concat=n=2:v=1', '-c:v', 'ffv1', str(cls.video)], check=True)
        cls.layout = cls.dir / 'layout.json'
        cls.layout.write_text(json.dumps({'bars': {'boss': {'rows': [20, 24], 'cols': [20, 219], 'fill': 'red'}}}))
        cls.csv = cls.dir / 'hud.csv'
        run(HERE / 'hud' / 'hud_bars.py', cls.video, cls.layout, cls.csv)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_bar_fill_is_measured_per_frame(self):
        rows = list(csv.DictReader(self.csv.read_text().splitlines()))
        self.assertEqual(len(rows), 20)
        self.assertAlmostEqual(float(rows[5]['boss_fill']), 1.0, delta=0.02)
        self.assertAlmostEqual(float(rows[15]['boss_fill']), 0.5, delta=0.02)

    def test_events_find_the_drop(self):
        out = self.dir / 'events.json'
        run(HERE / 'hud' / 'hud_events.py', out, f'test={self.csv}')
        drops = json.loads(out.read_text())['test']['boss']['drops']
        self.assertEqual(len(drops), 1)
        self.assertAlmostEqual(drops[0]['start'], 1.0, delta=0.1)
        self.assertAlmostEqual(drops[0]['loss'], 0.5, delta=0.02)

    def test_chart_draws_every_series(self):
        out = self.dir / 'chart.svg'
        run(HERE / 'hud' / 'hud_chart.py', out, '--bars', 'boss', '--series', f'Run A={self.csv}', '--series', f'Run B={self.csv}')
        svg = out.read_text(encoding='utf-8')
        self.assertEqual(svg.count('<path'), 2)
        self.assertIn('Run B', svg)

    def test_sheets_cover_every_frame(self):
        out = self.dir / 'sheets'
        run(HERE / 'evidence' / 'evidence.py', 'sheets', self.video, out, '--cols', '2', '--rows', '5', '--tile-width', '160')
        spans = list(csv.DictReader((out / 'sheets.csv').read_text().splitlines()))
        self.assertEqual([s['sheet'] for s in spans], ['sheet_001.jpg', 'sheet_002.jpg'])
        self.assertEqual((float(spans[1]['first_s']), float(spans[1]['last_s'])), (1.0, 1.9))

    def test_shots_write_frame_and_strip(self):
        spec = self.dir / 'spec.json'
        spec.write_text(json.dumps({'videos': {'run': {'path': 'bar.mkv', 'label': 'Test run'}},
                                    'shots': [{'id': 'BUG-01', 'video': 'run', 'best': 1.5, 'strip': [0.5, 1.5]}]}))
        out = self.dir / 'shots'
        run(HERE / 'evidence' / 'evidence.py', 'shots', spec, out)
        self.assertTrue((out / 'BUG-01_1.5s.jpg').is_file())
        self.assertTrue((out / 'BUG-01_strip.jpg').is_file())

    def test_report_markdown_converts_tables_and_figures(self):
        page = report2pdf.convert('| ID | Bug |\n|---|---|\n| BUG-01 | a \\| b |\n\n![Camera clip](shots/x.jpg)')
        self.assertIn('<td>a | b</td>', page)
        self.assertIn('<figcaption>Camera clip</figcaption>', page)


if __name__ == '__main__':
    unittest.main()
