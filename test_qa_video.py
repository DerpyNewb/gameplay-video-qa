import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import qa_video


class GameplayQATest(unittest.TestCase):
    def test_extraction_and_reference_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'clip with spaces.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x240:rate=10:duration=2',
                            '-c:v', 'mpeg4', str(video)], check=True)
            out = root / 'evidence'
            subprocess.run([sys.executable, str(Path(qa_video.__file__)), 'extract',
                            str(video), '--reference', str(video), '--out', str(out),
                            '--interval', '0.5'], check=True)
            manifest = json.loads((out / 'manifest.json').read_text())
            self.assertEqual(len(manifest['videos']), 2)
            for entry in manifest['videos']:
                self.assertEqual(len(entry['frames']), 4)
                self.assertFalse(entry['has_audio'])
                self.assertEqual([f['seconds'] for f in entry['frames']], [0, .5, 1, 1.5])
                self.assertTrue(all((out / f['file']).stat().st_size > 100 for f in entry['frames']))
            payload = qa_video.make_request(out, 'vision-model')
            self.assertFalse(payload['store'])
            images = [c for c in payload['input'][0]['content'] if c['type'] == 'input_image']
            self.assertEqual(len(images), 8)
            self.assertTrue(images[0]['image_url'].startswith('data:image/jpeg;base64,'))
            response = {'status': 'completed', 'output': [{'type': 'message',
                        'content': [{'type': 'output_text', 'text': 'Observed timeline'}]}]}
            with patch.dict('os.environ', {'OPENAI_API_KEY': 'test-secret'}):
                with patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())) as http:
                    qa_video.review(out, 'vision-model', root / 'api-review')
                    self.assertEqual(http.call_args.args[0].full_url, 'https://api.openai.com/v1/responses')
            self.assertIn('Observed timeline', (root / 'api-review/review.md').read_text())
            clip = root / 'segment.mp4'
            subprocess.run([sys.executable, str(Path(qa_video.__file__)), 'clip', str(video),
                            '--start', '.5', '--duration', '1', '--out', str(clip)], check=True)
            self.assertAlmostEqual(qa_video.probe(clip)['duration_seconds'], 1, places=1)
            with self.assertRaises(FileExistsError):
                qa_video.extract(video, out, .5, 0, None, 100, None, '')
            with patch.dict('os.environ', {}, clear=True):
                with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                    qa_video.review(out, 'vision-model', root / 'review')

    def test_sampling_limit_and_numbers(self):
        self.assertEqual(qa_video.sample_times(2, 0, None, .5, 4), [0, .5, 1, 1.5])
        with self.assertRaisesRegex(ValueError, 'max-frames'):
            qa_video.sample_times(100, 0, None, 1, 10)
        for interval in [0, -1, float('nan'), float('inf')]:
            with self.assertRaises(ValueError):
                qa_video.sample_times(2, 0, None, interval, 100)
        with self.assertRaises(ValueError):
            qa_video.sample_times(2, 2, None, 1, 100)

    def test_response_must_be_complete(self):
        self.assertEqual(qa_video.response_text({'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Review'}]}]}), 'Review')
        with self.assertRaises(ValueError):
            qa_video.response_text({'status': 'incomplete', 'output': []})

    def test_detect_finds_planted_defects(self):
        def near(spans, start, end):
            return any(abs(s - start) <= .1 and abs(e - end) <= .1 for s, e in spans)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'planted clip.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x240:rate=10:duration=10', '-filter_complex',
                            "[0]drawbox=color=black:t=fill:enable='between(t,3,3.45)',"
                            "drawbox=color=white:t=fill:enable='between(t,8,8.05)',split[a][b];"
                            '[a][b]freezeframes=first=50:last=64:replace=50',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
            script = str(Path(qa_video.__file__))
            out = root / 'packet' / 'anomalies-candidate'
            subprocess.run([sys.executable, script, 'detect', str(video), '--out', str(out)], check=True)
            report = json.loads((out / 'anomalies.json').read_text())
            events = report['events']

            def spans(kind):
                return [(e['start'], e['end']) for e in events if e['type'] == kind]
            self.assertTrue(near(spans('black'), 3, 3.5))
            self.assertTrue(near(spans('freeze'), 5, 6.5))
            self.assertTrue(near(spans('scene_cut'), 8, 8))
            jumps = [s for s, _ in spans('brightness_jump')]
            for planted in (3, 3.5, 8, 8.1):
                self.assertTrue(any(abs(s - planted) <= .1 for s in jumps), planted)
            self.assertFalse(report['frames_truncated'])
            self.assertTrue(all(e['id'].startswith('candidate-anomaly-') for e in events))
            self.assertTrue(all((out / e['frame']).stat().st_size > 100 for e in events))
            self.assertFalse((out / 'ffmpeg-metadata.txt').exists())
            self.assertEqual(len((out / 'anomalies.csv').read_text().splitlines()), len(events) + 1)

            capped = root / 'capped'
            subprocess.run([sys.executable, script, 'detect', str(video), '--out', str(capped),
                            '--max-frames', '1'], check=True)
            capped_events = json.loads((capped / 'anomalies.json').read_text())
            self.assertTrue(capped_events['frames_truncated'])
            self.assertEqual(len(capped_events['events']), len(events))
            self.assertIsNotNone(capped_events['events'][0]['frame'])
            self.assertTrue(all(e['frame'] is None for e in capped_events['events'][1:]))

            clean = root / 'clean.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x240:rate=10:duration=4', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', str(clean)], check=True)
            qa_video.detect(clean, root / 'clean-out', 'reference', -60, .5, .1, 10, 40, 60)
            clean_events = json.loads((root / 'clean-out/anomalies.json').read_text())['events']
            self.assertFalse([e for e in clean_events if e['type'] in ('freeze', 'black')])
            with self.assertRaises(FileExistsError):
                qa_video.detect(clean, root / 'clean-out', 'reference', -60, .5, .1, 10, 40, 60)
            with self.assertRaisesRegex(ValueError, 'positive'):
                qa_video.detect(clean, root / 'never', 'candidate', -60, .5, .1, 10, 0, 60)
            self.assertFalse((root / 'never').exists())

    def test_open_event_closes_at_duration(self):
        frames = qa_video.parse_metadata(
            'frame:0    pts:0       pts_time:0\nlavfi.signalstats.YAVG=100\n'
            'frame:1    pts:1024    pts_time:0.1\nlavfi.signalstats.YAVG=20\n'
            'lavfi.freezedetect.freeze_start=0.1\n')
        events = qa_video.find_events(frames, 2.0, 40, .1, 'candidate')
        self.assertEqual([(e['id'], e['type'], e['start'], e['end']) for e in events],
                         [('candidate-anomaly-0000', 'brightness_jump', .1, .1),
                          ('candidate-anomaly-0001', 'freeze', .1, 2.0)])
        self.assertEqual(events[0]['value'], -80)
        self.assertEqual(events[1]['duration'], 1.9)

    def test_black_shorter_than_minimum_is_dropped(self):
        # blackdetect's d= gates only its log line; its metadata reports every black run.
        frames = qa_video.parse_metadata(
            'frame:60   pts:60   pts_time:2\nlavfi.black_start=2\n'
            'frame:61   pts:61   pts_time:2.033\nlavfi.black_end=2.033\n'
            'frame:90   pts:90   pts_time:3\nlavfi.black_start=3\n'
            'frame:96   pts:96   pts_time:3.2\nlavfi.black_end=3.2\n'
            'frame:119  pts:119  pts_time:3.967\nlavfi.black_start=3.967\n')
        events = qa_video.find_events(frames, 4.0, 40, .1, 'candidate')
        self.assertEqual([(e['id'], e['type'], e['start'], e['end']) for e in events],
                         [('candidate-anomaly-0000', 'black', 3.0, 3.2)])

    def test_check_findings(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            video = root / 'clip.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x240:rate=10:duration=2', '-c:v', 'mpeg4', str(video)], check=True)
            packet = root / 'packet'
            qa_video.extract(video, packet, 1, 0, None, 10, None, '')
            (packet / 'anomalies-candidate').mkdir()
            (packet / 'anomalies-candidate/anomalies.json').write_text(
                json.dumps({'events': [{'id': 'candidate-anomaly-0000'}]}))
            (root / 'outside.jpg').write_bytes((packet / 'candidate/0000_000000.000s.jpg').read_bytes())
            finding = {'id': 'QA-001', 'title': 'Test pattern stalls', 'category': 'game',
                       'severity': 'minor', 'observed': 'o', 'expected': 'e', 'expected_source': 'unknown',
                       'impact': 'i', 'confidence': 'low', 'confidence_rationale': 'r', 'alternatives': 'a',
                       'evidence': [{'file': 'candidate/0001_000001.000s.jpg', 'seconds': 1},
                                    {'anomaly_id': 'candidate-anomaly-0000', 'seconds': 0}],
                       'repro_steps': ['Play the clip']}
            good = {'coverage': 'Two sampled frames.', 'follow_up': [], 'findings': [finding],
                    'timeline': [{'role': 'candidate', 'file': 'candidate/0000_000000.000s.jpg',
                                  'seconds': 0, 'observation': 'Pattern | visible'}]}
            self.assertEqual(qa_video.check_findings(packet, good), [])
            script = str(Path(qa_video.__file__))
            path = packet / 'findings.json'
            path.write_text(json.dumps(good))
            subprocess.run([sys.executable, script, 'check-findings', str(packet), str(path)], check=True)
            review = (packet / 'review.md').read_text()
            for text in ('QA-001: Test pattern stalls', 'UNVERIFIED', 'Pattern \\| visible',
                         'candidate-anomaly-0000', '1. Play the clip'):
                self.assertIn(text, review)

            bad_evidence = [{'file': 'candidate/9999.jpg'}, {'file': '../outside.jpg'},
                            {'anomaly_id': 'candidate-anomaly-9999'}, {'seconds': 3}]
            bad = dict(good, findings=[dict(finding, category='bug', evidence=bad_evidence),
                                       dict(finding, evidence=[])])
            problems = '\n'.join(qa_video.check_findings(packet, bad))
            for text in ('candidate/9999.jpg', '../outside.jpg', 'candidate-anomaly-9999',
                         'file or anomaly_id', 'category must be', 'duplicate id', 'at least one evidence'):
                self.assertIn(text, problems)
            path.write_text(json.dumps(bad))
            (packet / 'review.md').write_text('previous')
            result = subprocess.run([sys.executable, script, 'check-findings', str(packet), str(path)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('Evidence check failed', result.stderr)
            self.assertEqual((packet / 'review.md').read_text(), 'previous')

            empty = dict(good, findings=[])
            self.assertEqual(qa_video.check_findings(packet, empty), [])
            self.assertIn('No supported issue in sampled frames', qa_video.render_review(empty))
            self.assertIn('timeline: must be a list', '\n'.join(qa_video.check_findings(packet, {'coverage': 'c'})))
            with self.assertRaisesRegex(ValueError, 'manifest.json'):
                qa_video.check_findings(root, good)


if __name__ == '__main__':
    unittest.main()
