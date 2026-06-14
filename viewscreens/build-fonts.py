#!/usr/bin/env python3
# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

import os, re, json, zipfile, shutil
from fontTools.ttLib import TTFont

_HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get('FONT_SRC', os.path.expanduser('~/font-zips'))   # raw font .zip archives (NOT in the repo)
OUT = os.path.join(_HERE, 'fonts')                                    # organized library beside this script (per-font folders + catalog)

# slug -> (display name, native px size, dafont url)
META = {
 'visitor':('Visitor',10,'https://www.dafont.com/visitor.font'),
 '3x5_mt_pixel':('3x5 MT Pixel',5,'https://www.dafont.com/3x5-mt-pixel.font'),
 '5x5_mt_pixel':('5x5 MT Pixel',5,'https://www.dafont.com/5x5-mt-pixel.font'),
 '5x7_mt_pixel':('5x7 MT Pixel',7,'https://www.dafont.com/5x7-mt-pixel.font'),
 '7_squared':('7 Squared',9,'https://www.dafont.com/7-squared.font'),
 'thaleahfat':('Thaleah Fat',16,'https://www.dafont.com/thaleahfat.font'),
 'aurora_24':('Aurora 24',9,'https://www.dafont.com/aurora-24.font'),
 'retro_gaming':('Retro Gaming',11,'https://www.dafont.com/retro-gaming.font'),
 'deer_diary':('Deer Diary',11,'https://www.dafont.com/deer-diary.font'),
 'org_v01':('Org v01',8,'https://www.dafont.com/org-v01.font'),
 'virtual_dj':('Virtual DJ',8,'https://www.dafont.com/virtual-dj.font'),
 'free_pixel':('Free Pixel',16,'https://www.dafont.com/free-pixel.font'),
 'hachicro':('Hachicro',8,'https://www.dafont.com/hachicro.font'),
}
# tables to strip before the woff2 save, per slug — Chrome's OTS rejects some legacy/zero-length tables
# (org_v01 ships an empty `kern` table that fails OTS: "kern: zero-length table").
STRIP = { 'org_v01': ['PCLT','hdmx','cvt ','fpgm','prep','kern'] }

if os.path.isdir(OUT): shutil.rmtree(OUT)
os.makedirs(OUT)

def fontinfo(p):
    f=TTFont(p, fontNumber=0, lazy=True); n=f['name']
    fam=n.getDebugName(16) or n.getDebugName(1) or ''
    sub=n.getDebugName(17) or n.getDebugName(2) or ''
    full=n.getDebugName(4) or ''
    f.close(); return fam.strip(), sub.strip(), full.strip()

catalog=[]
for slug,(name,px,url) in META.items():
    zp=os.path.join(SRC, slug+'.zip')
    if not os.path.exists(zp): print('MISSING zip', slug); continue
    tmp='/tmp/fx_'+slug; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
    with zipfile.ZipFile(zp) as z: z.extractall(tmp)
    fontfiles, docs = [], []
    for root,_,files in os.walk(tmp):
        if '__MACOSX' in root: continue
        for fn in files:
            ext=fn.lower().rsplit('.',1)[-1]
            full=os.path.join(root,fn)
            if ext in ('ttf','otf'): fontfiles.append(full)
            elif ext in ('txt','md','rtf') or re.search(r'readme|license|licence|ofl', fn, re.I): docs.append(full)
    dest=os.path.join(OUT, slug); os.makedirs(dest)
    entry={'slug':slug,'name':name,'nativePx':px,'dafont':url,'files':[],'docs':[]}
    for ff in sorted(fontfiles):
        base=os.path.basename(ff); stem=os.path.splitext(base)[0]
        shutil.copy2(ff, os.path.join(dest, base))
        woff2=stem+'.woff2'
        try:
            f=TTFont(ff)
            for t in STRIP.get(slug, []):
                if t in f: del f[t]
            f.flavor='woff2'; f.save(os.path.join(dest, woff2))
        except Exception as e:
            print('woff2 FAIL', slug, base, e); woff2=None
        fam,sub,full=fontinfo(ff)
        entry['files'].append({'src':base,'woff2':woff2,'family':fam,'style':sub or 'Regular','fullName':full})
    for d in docs:
        b=os.path.basename(d); shutil.copy2(d, os.path.join(dest, b)); entry['docs'].append(b)
    catalog.append(entry)
    print(f"  {name:24s} {px:>2}px  {len(entry['files'])} font file(s), {len(entry['docs'])} doc(s)")

# Split designated multi-variant fonts into one catalog entry (and folder) per variant, so each is
# independently selectable + named. Map: source slug -> {file stem: (new slug, display name)}.
SPLIT = { 'visitor': { 'visitor1': ('visitor_tt1','Visitor TT1'), 'visitor2': ('visitor_tt2','Visitor TT2') } }
for src_slug, variants in SPLIT.items():
    base_entry = next((e for e in catalog if e['slug']==src_slug), None)
    if not base_entry: continue
    catalog = [e for e in catalog if e['slug']!=src_slug]
    src_dir = os.path.join(OUT, src_slug)
    for fileinfo in base_entry['files']:
        stem = os.path.splitext(fileinfo['src'])[0]
        if stem not in variants: continue
        new_slug, new_name = variants[stem]
        dest = os.path.join(OUT, new_slug); os.makedirs(dest, exist_ok=True)
        for ext in (fileinfo['src'], fileinfo['woff2']):
            if ext and os.path.exists(os.path.join(src_dir, ext)): shutil.copy2(os.path.join(src_dir, ext), os.path.join(dest, ext))
        docs = []
        for db in base_entry['docs']:
            shutil.copy2(os.path.join(src_dir, db), os.path.join(dest, db)); docs.append(db)
        catalog.append({'slug':new_slug,'name':new_name,'nativePx':base_entry['nativePx'],'dafont':base_entry['dafont'],'files':[fileinfo],'docs':docs})
        print(f"  split {src_slug} -> {new_name}")
    shutil.rmtree(src_dir, ignore_errors=True)

# size index: a native-D font is crisp at D, 2D, 3D ... (cap 32)
bysize={}
for e in catalog:
    D=e['nativePx']
    for k in range(1, 32//D+1):
        s=k*D; bysize.setdefault(s,[]).append({'slug':e['slug'],'name':e['name'],'mult':k})

cat={'fonts':catalog,'bySize':{str(k):bysize[k] for k in sorted(bysize)}}
with open(os.path.join(OUT,'fonts.json'),'w') as fp: json.dump(cat, fp, indent=2)

# human catalog
md=['# Font library','', 'Pixel/bitmap fonts for the Tufty port (`/viewscreens`). Each font is crisp at its **native px**',
    'size and integer multiples of it. Each per-font folder holds the original TTF/OTF + a generated',
    "WOFF2, plus the font's own license/readme where the source archive included one.",'',
    '## By font','','| Font | Native | Crisp at | Files | dafont |','|---|---|---|---|---|']
for e in sorted(catalog, key=lambda x:(x['nativePx'],x['name'])):
    D=e['nativePx']; mult=', '.join(str(k*D) for k in range(1,32//D+1))
    md.append(f"| {e['name']} | {D}px | {mult} | {len(e['files'])} | [link]({e['dafont']}) |")
md += ['','## By size slot','','*Which fonts give a crisp glyph at each pixel size (native, or via ×N scale).*','']
for s in sorted(bysize):
    items=', '.join(f"{x['name']}"+("" if x['mult']==1 else f" (×{x['mult']})") for x in bysize[s])
    md.append(f"- **{s}px** — {items}")
with open(os.path.join(OUT,'CATALOG.md'),'w') as fp: fp.write('\n'.join(md)+'\n')

print('\nWrote', len(catalog), 'fonts ->', OUT)
