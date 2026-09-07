"""Build a single-file version of index.html: every image, video and font
embedded as a data URI, so the page works when forwarded on its own and with
no network. Usage: python build_standalone.py <repo dir> <output file>
"""
import base64
import mimetypes
import os
import re
import sys
import urllib.request

repo, out_path = sys.argv[1], sys.argv[2]
html = open(os.path.join(repo, 'index.html'), encoding='utf-8').read()
# A complete WebKit UA string: Google Fonts serves woff2 only to browsers it
# recognises, and falls back to TTF (three times the size) otherwise.
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'}

FONT_MIME = {b'wOF2': 'font/woff2', b'wOFF': 'font/woff', b'OTTO': 'font/otf',
             bytes([0, 1, 0, 0]): 'font/ttf'}


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    with open(path, 'rb') as f:
        return 'data:%s;base64,%s' % (mime, base64.b64encode(f.read()).decode('ascii'))


# 1. every assets/... reference, wherever it appears (img src and the MEDIA map)
assets = sorted(set(re.findall(r'assets/[A-Za-z0-9_.-]+', html)))
for rel in assets:
    full = os.path.join(repo, rel.replace('/', os.sep))
    if not os.path.isfile(full):
        sys.exit('missing asset: ' + rel)
    html = html.replace(rel, data_uri(full))
    print('  embedded %-28s %8.1f KB' % (rel, os.path.getsize(full) / 1024))

# 2. Google Fonts: fetch the stylesheet, then each font file it points at
link_re = re.compile(r'\s*<link[^>]*fonts\.(?:googleapis|gstatic)\.com[^>]*>')
links = link_re.findall(html)
css_url = None
for tag in links:
    m = re.search(r'href="(https://fonts\.googleapis\.com/css2[^"]+)"', tag)
    if m:
        css_url = m.group(1).replace('&amp;', '&')

font_css = None
if css_url:
    try:
        req = urllib.request.Request(css_url, headers=UA)
        font_css = urllib.request.urlopen(req, timeout=30).read().decode('utf-8')
        urls = sorted(set(re.findall(r'url\((https://fonts\.gstatic\.com/[^)]+)\)', font_css)))
        total = 0
        fmts = set()
        for u in urls:
            blob = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30).read()
            total += len(blob)
            mime = next((v for k, v in FONT_MIME.items() if blob.startswith(k)), 'font/woff2')
            font_css = font_css.replace(u, 'data:%s;base64,%s' % (mime, base64.b64encode(blob).decode('ascii')))
            fmts.add(mime)
        print('  embedded %-28s %8.1f KB (%d files, %s)' % ('web fonts', total / 1024, len(urls), ', '.join(sorted(fmts))))
    except Exception as e:
        font_css = None
        print('  fonts NOT embedded (%s) - keeping the CDN link' % e)

if font_css:
    for tag in links:
        html = html.replace(tag, '')
    html = html.replace('<style>', '<style>\n/* Web fonts embedded for offline use */\n' + font_css + '\n', 1)

open(out_path, 'w', encoding='utf-8', newline='\n').write(html)
print('\nwrote %s  (%.1f MB)' % (out_path, os.path.getsize(out_path) / 1048576))
print('remaining external references:',
      sorted(set(re.findall(r'(?:src|href)="(https?://[^"]+)"', html))) or 'none')
