# Gameplay video QA

Tools for reviewing a gameplay recording as a QA engineer. They cover every frame, measure HUD bars that
show no numbers, produce labelled screenshots for bug reports, and check that written findings cite real
evidence. A Claude Code skill and a multi-agent workflow drive the review itself.

I built these to review a recorded boss fight played by an AI agent against a reference run of the same
fight, in an Unreal Engine editor capture. Nothing is specific to that game: bar positions, crops and game
context are inputs.

Requirements: Python 3.10+ (standard library only), FFmpeg and ffprobe on PATH, and Chrome or Edge for PDF
export. No pip packages.

## What is here

| Path | What it does |
| --- | --- |
| `qa_video.py` | Samples frames, measures freezes, black frames, scene cuts and brightness jumps on every frame, cuts clips, and checks a `findings.json` against the evidence packet |
| `hud/hud_bars.py` | Reads HUD bars (health, stamina, boss...) off every frame as fill fractions, from a small pixel layout file |
| `hud/hud_events.py` | Turns those readings into events: every drop of every bar and every time a bar sits empty |
| `hud/hud_chart.py` | Charts one to three runs as an SVG, with optional bands and markers for bug windows |
| `evidence/evidence.py` | `sheets`: contact sheets that together hold every frame, each tile labelled with its time. `shots`: full-resolution screenshots and before/during/after strips for bug reports |
| `report/report2pdf.py` | Markdown report to PDF with images and tables, via headless Chrome |
| `.claude/skills/gameplay-qa/` | Claude Code skill: the review procedure and the `findings.json` format |
| `workflows/full-frame-qa.js` | Claude Code workflow: many reviewers over every frame, merge, three-way verification, completeness pass |
| `bug-report-template.md`, `context.example.txt` | Bug report template; test-rules file for the reviewer |

## 1. First pass: sample and measure

```text
python qa_video.py extract run.mp4 --reference reference.mp4 --interval 5 --out output/run
python qa_video.py detect run.mp4 --out output/run/anomalies-candidate
python qa_video.py detect reference.mp4 --role reference --out output/run/anomalies-reference
```

`extract` writes sampled frames, `manifest.json` and `frames.csv`. `detect` runs one FFmpeg pass over every
frame and writes `anomalies.json`, `anomalies.csv` and one frame per event:

| Type | Meaning | Threshold flag (default) |
| --- | --- | --- |
| `freeze` | Picture stopped changing | `--freeze-noise` (-60 dB), `--freeze-min` (0.5 s) |
| `black` | Picture went black | `--black-min` (0.1 s) |
| `scene_cut` | Abrupt picture change | `--scene-threshold` (10) |
| `brightness_jump` | Mean brightness jumped between frames | `--brightness-jump` (40 of 255) |

These are measurements, not bugs. A freeze in a 10 fps capture is not a game FPS figure, a scene cut may be
a fast camera pan, and black may be a loading screen. For a closer look at a window:

```text
python qa_video.py extract run.mp4 --start 68 --end 73 --interval 0.5 --out output/run/detail-68-73
python qa_video.py clip run.mp4 --start 68 --duration 5 --out output/run/detail-68-73/clip.mp4
```

## 2. HUD telemetry

Many HUDs show bars without numbers. Open one frame at full size, note the pixel rows and columns of each
bar's track, and write a layout file (see `hud/layout.example.json`). Supported fill colours: red, green,
blue, yellow; the empty track must be light grey.

```text
python hud/hud_bars.py run.mp4 hud/layout.example.json output/hud_run.csv
python hud/hud_events.py output/hud_events.json candidate=output/hud_run.csv reference=output/hud_ref.csv
python hud/hud_chart.py output/hud.svg --bars boss,health --series "Agent run=output/hud_run.csv" --series "Reference=output/hud_ref.csv"
```

Every value is a fraction of the bar's length, not an HP number. A frame where the bar cannot be read
(hidden, or washed out by an effect) is left empty and noted. Drops are only counted when the bar stays
lower for three frames, so one-pixel edge flicker is ignored.

## 3. Evidence for the reviewer and the report

```text
python evidence/evidence.py sheets run.mp4 output/sheets_run --crop 1804:854:6:168
python evidence/evidence.py shots output/shots.json output/screenshots
```

`sheets` puts 20 consecutive frames on each sheet (4x5, configurable), so a reviewer who can only look at
images still sees every frame. `--crop` keeps just the game viewport of an editor or desktop capture.
`shots` takes a spec of bug IDs and times and writes a full-resolution frame per bug plus a
before/during/after strip. The label sits in a band above the frame, so it never hides the HUD. The spec
format is in the script's help.

## 4. Review with Claude Code

Open this folder in Claude Code and ask, for example: *"Run a gameplay QA review of run.mp4 against
reference.mp4."* The skill in `.claude/skills/gameplay-qa/` tells Claude to extract, detect, open every
sampled and flagged frame, look closer at anything suspicious, and write `findings.json`. Then check it:

```text
python qa_video.py check-findings output/run output/run/findings.json
```

This rejects any finding whose evidence is not a frame inside the packet or a known anomaly ID, and any
missing field or invalid category, severity or confidence. On success it writes `review.md`, with every
reproduction step labelled UNVERIFIED.

## 5. Multi-agent review of every frame (optional)

`workflows/full-frame-qa.js` is a Claude Code workflow for a full review. It runs these steps:

1. One reviewer per 10 s window opens every contact sheet in its window, explains every HUD event from the
   frames, and logs a timeline and candidate issues against a QA checklist (camera, animation, collision,
   VFX, HUD, game logic, agent behaviour, capture).
2. A merge step dedupes the issues across windows and builds one timeline per video.
3. Each issue gets three independent checks: *observe* (re-extract every frame around it and fix the exact
   start, end and best frame), *refute* (argue it is intended, agent behaviour, a capture artifact or a
   misreading), and *severity*.
4. A completeness critic raises open questions; each gets a follow-up, and any new issue is verified the
   same way.
5. Optionally, every claim in other QA outputs is extracted and checked against the frames.

Prepare the sheets and HUD data first, then run the workflow with arguments like these:

```json
{
  "scratch": "output/agents",
  "context": "- Unreal Editor PIE capture, 1920x1200, 10 fps, no audio. A sword-and-shield player fights a boss.\n- HUD: health (red) and stamina (green) top-left, boss bar at the bottom. No numbers on the bars.",
  "fps": 10,
  "events": "output/hud_events.json",
  "videos": {
    "candidate": {"path": "run.mp4", "duration": 100, "crop": "1804:854:6:168", "sheets": "output/sheets_run", "hud_csv": "output/hud_run.csv"},
    "reference": {"path": "reference.mp4", "duration": 66, "crop": "1816:866:6:168", "sheets": "output/sheets_ref", "hud_csv": "output/hud_ref.csv"}
  },
  "external": []
}
```

It returns the verified issues with their verdicts, both timelines, and the follow-up answers. A person
still makes the final call on each issue.

Cost: the run this was built on used 466 agents for 166 s of video. Scale `windowSeconds` or the checks to
your budget.

## 6. Export the report

```text
python report/report2pdf.py output/report.md
```

This prints the page count and any image the report references but cannot find. Set `CHROME` if Chrome or
Edge is not in a standard location.

## Optional: automated review through the OpenAI API

`qa_video.py review` sends the sampled frames and your test context to an OpenAI vision model (billed; set
`OPENAI_API_KEY`). It sets `store: false`, which is not a promise of zero retention. Check the frames for
confidential content first.

```text
python qa_video.py review output/run --model YOUR_VISION_MODEL --out output/run-ai
```

## Limits

- Stills cannot show continuous motion, input lag or audio. A 10 fps capture hides anything shorter than
  0.1 s.
- Without test rules or expected behaviour (`--context`), findings are hypotheses. A reference run is a
  comparison, not a specification.
- Causes are inferred from pixels. Reproduction needs the build, and every reproduction step these tools
  write is labelled UNVERIFIED.

## Tests

```text
python -m unittest -v
```

The tests build synthetic videos with known defects: black, freeze and flash segments, and a HUD bar that
drops from full to half at 1.0 s. They check that each tool finds them at the right frame. They also check
the findings checker, the report converter and the API request handling (against a fake HTTP response).
They do not measure how accurate a review is.
