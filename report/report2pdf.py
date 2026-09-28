"""Multi-page markdown report -> PDF via headless Chrome, images included. Usage: python report/report2pdf.py report.md

Supports headings, pipe tables, lists, code, blockquotes, links and images (alt text becomes the caption).
Image paths are relative to the markdown file. Set CHROME to the browser executable if it is not found.
"""
import html, os, re, shutil, subprocess, sys
from pathlib import Path

CHROME = next((c for c in [os.environ.get('CHROME'), r'C:\Program Files\Google\Chrome\Application\chrome.exe',
                           r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                           '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                           shutil.which('google-chrome'), shutil.which('chromium'), shutil.which('chrome')]
               if c and Path(c).is_file()), None)


def inline(text):
    parts = re.split(r'(`[^`]+`)', text)
    out = []
    for part in parts:
        if part.startswith('`') and part.endswith('`') and len(part) > 1:
            out.append(f'<code>{html.escape(part[1:-1])}</code>')
            continue
        s = html.escape(part, quote=False)
        s = re.sub(r'!\[([^\]]*)\]\(<?([^)>]+)>?\)', r'<figure><img alt="\1" src="\2"><figcaption>\1</figcaption></figure>', s)
        s = re.sub(r'\[([^\]]+)\]\(<?([^)>]+)>?\)', r'<a href="\2">\1</a>', s)
        s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
        s = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<em>\1</em>', s)
        out.append(s)
    return ''.join(out)


def cells(row):
    row = row.strip()
    row = row[1:] if row.startswith('|') else row
    row = row[:-1] if row.endswith('|') and not row.endswith(r'\|') else row
    return [c.strip().replace(r'\|', '|') for c in re.split(r'(?<!\\)\|', row)]


def convert(md):
    lines, out, i = md.splitlines(), [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = re.match(r'(#{1,4})\s+(.*)', line)
        if heading:
            n = len(heading.group(1))
            out.append(f'<h{n}>{inline(heading.group(2))}</h{n}>')
            i += 1
        elif line.lstrip().startswith('|') and i + 1 < len(lines) and re.match(r'^\s*\|?\s*:?-{3,}', lines[i + 1]):
            head = cells(line)
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith('|'):
                rows.append(cells(lines[i]))
                i += 1
            out.append('<table><thead><tr>' + ''.join(f'<th>{inline(c)}</th>' for c in head) + '</tr></thead><tbody>'
                       + ''.join('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>' for r in rows)
                       + '</tbody></table>')
        elif re.match(r'\s*([-*]|\d+\.)\s+', line):
            ordered = bool(re.match(r'\s*\d+\.\s+', line))
            items = []
            while i < len(lines) and lines[i].strip():
                m = re.match(r'\s*([-*]|\d+\.)\s+(.*)', lines[i])
                if m and bool(re.match(r'\d+\.', m.group(1))) == ordered:
                    items.append(m.group(2))
                elif m:
                    break
                else:
                    items[-1] += ' ' + lines[i].strip()
                i += 1
            tag = 'ol' if ordered else 'ul'
            out.append(f'<{tag}>' + ''.join(f'<li>{inline(t)}</li>' for t in items) + f'</{tag}>')
        elif line.strip().startswith('```'):
            i += 1
            block = []
            while i < len(lines) and not lines[i].strip().startswith('```'):
                block.append(lines[i])
                i += 1
            i += 1
            out.append('<pre>' + html.escape('\n'.join(block)) + '</pre>')
        elif line.startswith('>'):
            block = []
            while i < len(lines) and lines[i].startswith('>'):
                block.append(lines[i].lstrip('> '))
                i += 1
            out.append('<blockquote>' + inline(' '.join(block)) + '</blockquote>')
        else:
            para = []
            while (i < len(lines) and lines[i].strip() and not re.match(r'(#{1,4})\s|\s*\||\s*([-*]|\d+\.)\s|```|>', lines[i])):
                para.append(lines[i].strip())
                i += 1
            if not para:  # a line no branch claimed (e.g. a lone "|"); keep it as text
                para, i = [lines[i].strip()], i + 1
            out.append('<p>' + inline(' '.join(para)) + '</p>')
    return '\n'.join(out)


CSS = """
@page { size: A4; margin: 14mm 13mm 16mm; }
body { font: 9.6pt/1.4 "Segoe UI", Calibri, Arial, sans-serif; color: #1a1a1a; margin: 0; }
h1 { font-size: 17pt; margin: 0 0 4pt; }
h2 { font-size: 12pt; margin: 16pt 0 6pt; padding-bottom: 2pt; border-bottom: 1px solid #bbb; break-after: avoid; }
h3 { font-size: 10.5pt; margin: 12pt 0 4pt; break-after: avoid; }
h4 { font-size: 9.8pt; margin: 10pt 0 3pt; break-after: avoid; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 6pt; padding-left: 16pt; }
li { margin-bottom: 2pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 10pt; font-size: 8.4pt; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th, td { border: 1px solid #c8c8c8; padding: 3pt 4pt; text-align: left; vertical-align: top; }
th { background: #eef0f3; font-weight: 600; }
code { font-family: Consolas, monospace; font-size: 8.6pt; background: #f3f3f3; padding: 0 2pt; }
pre { font-family: Consolas, monospace; font-size: 8.2pt; background: #f5f5f5; padding: 6pt; white-space: pre-wrap; }
blockquote { margin: 0 0 6pt; padding-left: 8pt; border-left: 3px solid #bbb; color: #444; }
img { max-width: 100%; max-height: 95mm; display: block; margin: 4pt 0 8pt; border: 1px solid #ccc; break-inside: avoid; }
figure { margin: 4pt 0 10pt; break-inside: avoid; }
figcaption { font-size: 8.4pt; color: #555; margin-top: -4pt; }
td:first-child { white-space: nowrap; }
a { color: #1a4f8b; text-decoration: none; }
"""


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if not CHROME:
        sys.exit('Chrome or Edge not found; set CHROME to its executable')
    src = Path(sys.argv[1]).resolve()
    out = src.with_suffix('.pdf')
    page = (f'<!doctype html><html><head><meta charset="utf-8"><base href="{src.parent.as_uri()}/">'
            f'<title>{html.escape(src.stem)}</title><style>{CSS}</style></head><body>'
            f'{convert(src.read_text(encoding="utf-8-sig"))}</body></html>')
    tmp = src.with_suffix('.tmp.html')
    tmp.write_text(page, encoding='utf-8')
    try:
        subprocess.run([CHROME, '--headless', '--disable-gpu', '--no-pdf-header-footer', '--allow-file-access-from-files',
                        f'--print-to-pdf={out}', tmp.as_uri()], check=True, capture_output=True)
    finally:
        tmp.unlink(missing_ok=True)
    pages = len(re.findall(rb'/Type\s*/Page[^s]', out.read_bytes()))
    missing = [m for m in re.findall(r'<img alt="[^"]*" src="([^"]+)"', page) if not (src.parent / m).is_file()]
    print(f'wrote {out} ({out.stat().st_size // 1024} KB, ~{pages} pages)' + (f'; MISSING IMAGES: {missing}' if missing else ''))


if __name__ == '__main__':
    main()
