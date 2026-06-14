// ccstats — self-hosted Claude Code usage stats (badge firmware + server)
// Copyright (C) 2026 Zapador <zapador@zapador.net>
//
// This program is free software; you can redistribute it and/or modify it under
// the terms of version 2 of the GNU General Public License as published by the
// Free Software Foundation. See the LICENSE file for the full text.
//
// This program is distributed WITHOUT ANY WARRANTY; without even the implied
// warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

/* === screens.js — canvas screen registry for /viewscreens (PicoGraphics-style port) ===
   Each screen is a pure sequence of pico.js draw calls at absolute 320×240 coordinates — no DOM/CSS/flex.
   This is the form that ports ~1:1 to the Tufty MicroPython firmware. index.html renders every screen
   via boot(). Ported screens:
   ACTIVITY (first). Time-based behaviour (live avatar, countdowns) is deferred to the real firmware port. */

const THEME = Object.assign({}, THEME_DEFAULTS);   // from pico.js (the built-in default)
// live theme colours (per-browser, set by the Palettes tweaks panel). buildPalette() derives ~20 shades from
// these 5 base colours, so applying a palette / editing a colour just re-renders.
function getTheme(){ let o={}; try{ o=JSON.parse(localStorage.getItem('viewscreens_theme')||'{}')||{}; }catch(e){} return Object.assign({}, THEME_DEFAULTS, o); }
function setThemeColors(obj){ let o={}; try{ o=JSON.parse(localStorage.getItem('viewscreens_theme')||'{}')||{}; }catch(e){} Object.assign(o, obj); try{ localStorage.setItem('viewscreens_theme', JSON.stringify(o)); }catch(e){} }
function resetTheme(){ try{ localStorage.removeItem('viewscreens_theme'); }catch(e){} }

/* ---------- tiny formatters ---------- */
function fmtInt(n){ n=Math.round(n||0); return n.toLocaleString('en-US'); }
const trim = s => String(s).replace(/\.0$/,'');
// value→unit label: one decimal, EXCEPT >=100 of the unit drops it so the label stays ~4 chars
// ("110M" not "110.3M"; "107K" not "107.3K"), keeping big values off the PROJECTS/TOOLS bars.
// Mirrors firmware formatters._scaled.
function fmtScaled(n, unit, suffix){ const s=n/unit; return (s>=100 ? String(Math.round(s)) : trim(s.toFixed(1)))+suffix; }
function fmtTokens(n){ n=n||0; if(n>=1e9) return trim((n/1e9).toFixed(1))+'B'; if(n>=1e6) return fmtScaled(n,1e6,'M'); if(n>=1e3) return Math.round(n/1e3)+'K'; return String(Math.round(n)); }
function fmtCompact(n){ n=n||0; if(n>=1e9) return trim((n/1e9).toFixed(1))+'B'; if(n>=1e6) return fmtScaled(n,1e6,'M'); if(n>=1e3) return fmtScaled(n,1e3,'K'); return String(Math.round(n)); }
function fmtMin(min){ min=Math.max(0,Math.round(min||0)); const h=Math.floor(min/60), m=min%60; return h>0 ? h+'H '+(m<10?'0':'')+m+'M' : m+'M'; }
function fmtUSD(n){ n=n||0; return '$'+(n>=1000 ? trim((n/1000).toFixed(1))+'K' : String(Math.round(n))); }   // whole dollars; ≥$1000 → "1.1K" / "3.7K"
function fmtDur(sec){ sec=Math.max(0,Math.round(sec||0));   // seconds → "1H 42M" / "37M 10S" / "12S"
  const h=Math.floor(sec/3600), m=Math.floor(sec%3600/60), s=sec%60;
  if(h>0) return h+'H '+(m<10?'0':'')+m+'M'; if(m>0) return m+'M '+(s<10?'0':'')+s+'S'; return s+'S'; }
const pct1 = v => (v==null ? '-' : (Math.round(v*10)/10)+'%');
// ---- viewscreens options (live, per-browser, set by the Theme Tweaks panel) — separate from the type scale ----
const OPT_DEFAULTS = { tokenMode:'nocache', avatarStats:true, avatarSessBar:true };
function getOpts(){ let o={}; try{ o=JSON.parse(localStorage.getItem('viewscreens_opts')||'{}')||{}; }catch(e){} return Object.assign({}, OPT_DEFAULTS, o); }
function setOpt(k,v){ let o={}; try{ o=JSON.parse(localStorage.getItem('viewscreens_opts')||'{}')||{}; }catch(e){} o[k]=v; try{ localStorage.setItem('viewscreens_opts', JSON.stringify(o)); }catch(e){} }
function resetOpts(){ try{ localStorage.removeItem('viewscreens_opts'); }catch(e){} }
let _OPTS = Object.assign({}, OPT_DEFAULTS);   // refreshed from getOpts() each render (paint2)
// Footer B-button hint, mirroring the badge's contextual-B label (navigation.py).
// /viewscreens is a STATIC mirror — it shows the label the badge would show but
// never simulates the press (no paging/zoom/edit on the web, by design). paint2
// sets it per screen; chrome() draws it under the (also static) A/C arrows.
let _footerB = '';
function footerBLabel(slug, data){
  if(slug==='projects'){ const n=((data&&data.projects)||[]).length; return n>4 ? 'MORE' : ''; }
  // EXPLAIN/EDIT/PREVIEW match firmware B_HINTS; avatar's LIVE toggle is battery-only ⇒ blank here
  return ({trophies:'EXPLAIN', optdisplay:'EDIT', optscreens:'EDIT',
           optpalettes:'PREVIEW', optavatar:'PREVIEW'})[slug] || '';
}
// token total honouring the cache mode: 'all' = tokens_total (incl. cache) · 'nocache' = input+output (the truer "work").
function tokVal(o){ if(!o) return 0; return _OPTS.tokenMode==='all' ? (o.tokens_total||0) : ((o.tokens_input||0)+(o.tokens_output||0)); }
function dayMetric(){ return _OPTS.tokenMode==='all' ? 'tokens' : 'tokens_io'; }   // per-day series field by mode
const levOf  = w => (w&&w.prompts) ? tokVal(w)/w.prompts : 0;   // leverage = tokens-per-prompt (honours the cache mode)
// USAGE LIMITS reset countdown — seconds until reset from an absolute resets_at (exact regardless of feed age),
// falling back to resets_in_sec; then formatted "3D 5H" / "2H 14M" / "<1M" (ported from /view).
function secFrom(b){ if(!b||!b.resets_at) return (b&&b.resets_in_sec!=null)?b.resets_in_sec:null;
  const t=Date.parse(b.resets_at); return isNaN(t)?null:Math.max(0,Math.round((t-Date.now())/1000)); }
function fmtReset(sec){ if(sec==null) return '-'; if(sec<=0) return 'NOW';
  const d=Math.floor(sec/86400), h=Math.floor(sec%86400/3600), m=Math.floor(sec%3600/60);
  if(d>0) return d+'D '+h+'H'; if(h>0) return h+'H '+m+'M'; return (m||'<1')+'M'; }

/* ---------- TYPE SCALE — ELEMENT-TYPE ROLES, each → {font,px}. Screens reference a ROLE (what the text IS —
   a rowLabel, a heroValue, an axisTick…), never a raw size, so a "font theme" can re-map every role's font+px
   without touching screen code (analogous to a colour palette — future: ship presets). P.scale (set in
   paint2) is what text() reads. `font` is a key in pico.js FONTS (built-ins pico=Press Start 2P / silk=
   Silkscreen; library fonts registered from fonts.json at boot). px should be the font's NATIVE size or an
   integer multiple (N, N×2…) to stay crisp. Default theme = "true to /view (view1)": Press Start 2P (pico)
   for the title + all numbers, Silkscreen (silk) for labels/captions, Visitor TT1 for the 10px name tier.
   (SCALE_SIZES keeps its name for back-compat with the Tweaks panel / getScale, but now holds ROLE keys.) */
const SCALE_SIZES = ['screenTitle','sectionLabel','rowLabel','rowValue','heroValue','caption','axisTick','legendLabel','tag','compareValue','modelShareLabel','modelTurnLabel','speechBubble'];
// Default theme — user-chosen per-role font + px (all crisp: native or integer multiple of the font's
// native size). Position tweaking to re-align elements to these sizes follows separately.
const DEFAULT_SCALE = {
  screenTitle:  { font:'visitor_tt1',  px:20 },  // Visitor TT1 (native 10) ×2
  sectionLabel: { font:'silk',         px:8  },  // Silkscreen (native 8)
  rowLabel:     { font:'aurora_24',    px:9  },  // Aurora 24 (native 9) — project/tool/model/VERSUS names + card labels
  rowValue:     { font:'silk',         px:16 },  // Silkscreen (native 8) ×2 — card/bar/versus values
  heroValue:    { font:'5x7_mt_pixel', px:21 },  // 5x7 MT Pixel (native 7) ×3 — big hero totals
  caption:      { font:'silk',         px:8  },  // Silkscreen (native 8) — hero captions, sub-lines, "BY", "VS"
  axisTick:     { font:'5x5_mt_pixel', px:5  },  // 5x5 MT Pixel (native 5) — chart-axis numerals
  legendLabel:  { font:'5x5_mt_pixel', px:5  },  // 5x5 MT Pixel (native 5) — legend labels
  tag:          { font:'5x5_mt_pixel', px:5  },  // 5x5 MT Pixel (native 5) — top-right tag, footer clock, corners
  compareValue:    { font:'aurora_24',    px:9  },  // Aurora 24 (native 9) — VERSUS me/rival values (cmpRow), distinct from card box values (rowValue)
  modelShareLabel: { font:'3x5_mt_pixel', px:5  },  // 3x5 MT Pixel (native 5) — MODELS share-legend model names (top row)
  modelTurnLabel:  { font:'visitor_tt1',  px:10 },  // Visitor TT1 (native 10) — MODELS "BY TURNS" model names (list)
  speechBubble:    { font:'silk',         px:8  }   // Silkscreen (native 8) — avatar speech-bubble text (firmware role; web renders a static avatar, kept for roster parity)
};
// merge DEFAULT_SCALE with a per-browser localStorage override (set live by the Tweaks panel)
function getScale(){
  let ov={}; try{ ov=JSON.parse(localStorage.getItem('viewscreens_scale')||'{}')||{}; }catch(e){}
  const s={}; SCALE_SIZES.forEach(k=>{ s[k]=Object.assign({}, DEFAULT_SCALE[k], ov[k]||{}); }); return s;
}
function setScaleSize(name, font, px){
  let ov={}; try{ ov=JSON.parse(localStorage.getItem('viewscreens_scale')||'{}')||{}; }catch(e){}
  ov[name]=Object.assign({}, ov[name]||{}); if(font!=null) ov[name].font=font; if(px!=null) ov[name].px=+px;
  try{ localStorage.setItem('viewscreens_scale', JSON.stringify(ov)); }catch(e){}
}
function resetScale(){ try{ localStorage.removeItem('viewscreens_scale'); }catch(e){} }
// Named font presets — complete role→{font,px} maps, selectable from the Tweaks panel's preset dropdown.
// Preset1 = the original /viewscreens scale (DEFAULT_SCALE); Preset2 = user-authored alt set (2026-06-11).
// All sizes are native or integer multiples of the font's native px (crisp).
const FONT_PRESETS = {
  Preset1: DEFAULT_SCALE,
  Preset2: {
    screenTitle:  { font:'visitor_tt1',  px:20 },  // Visitor TT1 (native 10) ×2
    sectionLabel: { font:'visitor_tt1',  px:10 },  // Visitor TT1 (native 10)
    rowLabel:     { font:'pico',         px:8  },  // Press Start 2P (native 8)
    rowValue:     { font:'silk',         px:16 },  // Silkscreen (native 8) ×2
    heroValue:    { font:'visitor_tt1',  px:50 },  // Visitor TT1 (native 10) ×5
    caption:      { font:'visitor_tt1',  px:10 },  // Visitor TT1 (native 10)
    axisTick:     { font:'5x5_mt_pixel', px:5  },  // 5x5 MT Pixel (native 5)
    legendLabel:  { font:'5x5_mt_pixel', px:5  },  // 5x5 MT Pixel (native 5)
    tag:          { font:'visitor_tt1',  px:10 },  // Visitor TT1 (native 10)
    compareValue:    { font:'pico',         px:8  },  // Press Start 2P (native 8)
    modelShareLabel: { font:'3x5_mt_pixel', px:5  },  // 3x5 MT Pixel (native 5)
    modelTurnLabel:  { font:'visitor_tt1',  px:10 },  // Visitor TT1 (native 10)
    speechBubble:    { font:'silk',         px:8  }   // Silkscreen (native 8) — avatar speech-bubble text
  }
};
function applyFontPreset(name){ const p=FONT_PRESETS[name]; if(!p) return;
  const ov={}; SCALE_SIZES.forEach(k=>{ ov[k]={font:p[k].font, px:p[k].px}; });
  try{ localStorage.setItem('viewscreens_scale', JSON.stringify(ov)); }catch(e){}
}
// which preset (if any) the CURRENT scale matches exactly — derived, so a hand-edited role reads as '' (custom)
function currentFontPreset(){ const s=getScale();
  for(const name of Object.keys(FONT_PRESETS)){ const p=FONT_PRESETS[name];
    if(SCALE_SIZES.every(k=> s[k].font===p[k].font && s[k].px===p[k].px)) return name; }
  return ''; }

/* ---------- sample feed (used only when no ?token= / fetch fails), ~140 days so the block is full ---------- */
const SAMPLE = (function(){
  const N=140, days=[]; const end=new Date('2026-06-08T00:00:00');
  for(let i=0;i<N;i++){ const dt=new Date(end); dt.setDate(dt.getDate()-(N-1-i));
    const m=dt.getMonth()+1, dd=dt.getDate(), ds=dt.getFullYear()+'-'+(m<10?'0':'')+m+'-'+(dd<10?'0':'')+dd;
    const t=Math.round((0.15+0.85*Math.abs(Math.sin(i*0.7)))*1400000)*((i%9===3)?0:1);
    days.push({date:ds, tokens:t, tokens_io:Math.round(t*0.06), prompts:t?Math.max(1,Math.round(t/90000)):0,
      sessions:t?Math.max(1,Math.round(t/350000)):0, active_min:t?Math.round(t/18000):0}); }
  const hours=[0,0,0,0,0,1,3,12,28,45,62,58,42,38,71,65,58,48,35,22,14,8,3,1];
  const weekdays=[142,168,185,153,131,32,9], wtot=weekdays.reduce((a,b)=>a+b,0)||1;
  const weekday_hour=weekdays.map(wv=>hours.map(hv=>Math.round(wv*hv/wtot)));   // outer product for the preview
  return { meta:{corpus_days:N, corpus_start:days[0].date, generated_at:'2026-06-08T14:30:00', servers:['main','edge']},
    totals:{current_streak:7, longest_streak:24, active_days:120, sessions:480, peak_hour:14, peak_weekday:2,
      tokens_input:14300000, tokens_output:2590000, cache_hit_ratio:0.72, user_prompts:820,
      user_words:560000, user_chars_typed:3100000, tool_uses:8963,
      total_active_min:8050, longest_session_min:174, nightowl_active_min:2360},
    cost_estimate:{total_usd:246.65},
    limits:{ stale:false, generated_at:'2026-06-08T14:30:00',
      session:{utilization:65, resets_in_sec:8040},    // ~2H 14M
      weekly: {utilization:45, resets_in_sec:277800} },  // ~3D 5H
    top_tools:[{name:'Bash',count:1620},{name:'Read',count:980},{name:'Edit',count:610},
      {name:'Write',count:240},{name:'Grep',count:180},{name:'Agent',count:157},{name:'Glob',count:96},{name:'TodoWrite',count:74}],
    models:[{name:'claude-opus-4-7',turns:3100,pct:44.0},{name:'claude-opus-4-6',turns:1900,pct:27.0},
      {name:'claude-sonnet-4-6',turns:760,pct:10.8},{name:'claude-haiku-4-5',turns:650,pct:9.2}],
    histograms:{hours, weekdays, weekday_hour},
    daily_activity:days,
    projects:[
      {name:'Oxygen',tokens_input:5600000,tokens_output:1000000,cost_estimate_usd:98.40,user_prompts:312,user_words:48200,total_active_min:3120,agent_launches:505},
      {name:'Helium',tokens_input:3200000,tokens_output:580000,cost_estimate_usd:54.10,user_prompts:188,user_words:29400,total_active_min:1845,agent_launches:0},
      {name:'Cobalt',tokens_input:2400000,tokens_output:440000,cost_estimate_usd:41.20,user_prompts:141,user_words:21700,total_active_min:1290,agent_launches:6},
      {name:'Neon',tokens_input:1900000,tokens_output:350000,cost_estimate_usd:33.05,user_prompts:121,user_words:17350,total_active_min:980,agent_launches:14},
      {name:'Ccstats',tokens_input:1200000,tokens_output:220000,cost_estimate_usd:19.90,user_prompts:58,user_words:8900,total_active_min:515,agent_launches:28} ],
    competition:{   // mirrors the real competition.json shape ({ me, peers:[…] })
      me:{ alias:'Zapador',
        metrics:{ words_typed_total:560000, user_chars_typed:3100000, prompts_total:4200, bottleneck_sec_total:8040, total_active_min:52000, active_days:120, agents_total:573,
          current_streak:7, longest_streak:24, endurance_longest_session_min:187, cache_hit_ratio:0.72, peak_day_io:{date:'2026-05-21',tokens:1870000},
          record_day_words:{date:'2026-05-09',value:9590}, record_day_prompts:{date:'2026-04-06',value:204}, record_day_active_min:{date:'2026-06-07',value:789}, record_day_sessions:{date:'2026-04-06',value:80} },
        windows:{ '24h':{tokens_input:1200000,tokens_output:240000}, '7d':{tokens_input:9000000,tokens_output:1800000},
          '30d':{tokens_input:30000000,tokens_output:6000000}, all:{ tokens_input:55000000, tokens_output:11000000, prompts:4200, night_owl_pct:18.3 } },
        limits:{ session_limit_hits:7, weekly_limit_hits:2 } },
      peers:[{ alias:'Rival',
        metrics:{ words_typed_total:412000, user_chars_typed:2350000, prompts_total:3380, bottleneck_sec_total:12060, total_active_min:38400, active_days:96, agents_total:177,
          current_streak:6, longest_streak:14, endurance_longest_session_min:208, cache_hit_ratio:0.69, peak_day_io:{date:'2026-05-27',tokens:1100000},
          record_day_words:{date:'2026-06-08',value:13557}, record_day_prompts:{date:'2026-06-07',value:131}, record_day_active_min:{date:'2026-06-07',value:723}, record_day_sessions:{date:'2026-06-07',value:11} },
        windows:{ '24h':{tokens_input:900000,tokens_output:180000}, '7d':{tokens_input:7000000,tokens_output:1400000},
          '30d':{tokens_input:22000000,tokens_output:4400000}, all:{ tokens_input:38000000, tokens_output:6600000, prompts:3380, night_owl_pct:11.4 } },
        limits:{ session:{utilization:38, resets_in_sec:5400}, weekly:{utilization:52, resets_in_sec:190800} },
        projects:[{name:'Orbit',tokens_input:3200000,tokens_output:600000,cost_estimate_usd:42.10,user_prompts:180,user_words:22000,total_active_min:1600,agent_launches:30},
          {name:'Quartz',tokens_input:1800000,tokens_output:340000,cost_estimate_usd:24.50,user_prompts:110,user_words:14000,total_active_min:920,agent_launches:8},
          {name:'Pelican',tokens_input:900000,tokens_output:170000,cost_estimate_usd:12.30,user_prompts:60,user_words:7000,total_active_min:480,agent_launches:3}] }] } };
})();

/* ---------- shared chrome (topbar / rule / footer) — IDENTICAL on every screen ---------- */
const HEADER_H=23, FOOTER_Y=227;           // header bar height (spark centred ⇒ equal gap above/below); footer is 240-FOOTER_Y=13px
function chrome(P, title, tag){
  const C=P.pal;
  P.clear(C.bg);                             // fill the whole screen with the palette background first
  // header bar
  P.rect(0,0,320,HEADER_H, C.titlebar);
  P.hline(0,HEADER_H-1,320, C.rim);
  P.text(title, 6, 6, C.a1, 'screenTitle', {shadow:[1,1,C.a1sh]});
  // spark/star at the far right — exact match to /view's 16×16 spark (cross in Accent 1, dots+centre in
  // Accent 1 light); tag text right-aligned to its left.
  const spx=320-6-16, spy=3;
  P.rect(spx+7,spy,2,16, C.a1); P.rect(spx,spy+7,16,2, C.a1);                 // cross bars
  P.rect(spx+3,spy+3,2,2, C.a1l);  P.rect(spx+11,spy+3,2,2, C.a1l);           // diagonal dots
  P.rect(spx+3,spy+11,2,2, C.a1l); P.rect(spx+11,spy+11,2,2, C.a1l);
  P.rect(spx+6,spy+6,4,4, C.a1l);                                            // centre
  if(tag) P.text(tag, spx-7, 9, C.creamD, 'tag', {sp:1, align:'r'});   // 3px more gap between the tag text and the spark
  // dashed rule (2px) directly under the header
  for(let i=0;i<320;i+=8) P.rect(i,HEADER_H,4,2, C.line);
  // footer bar
  P.rect(0,FOOTER_Y,320,240-FOOTER_Y, C.titlebar);
  // status dot = connection light: palette status pen when online, fixed black when offline (matches firmware screen_shared)
  P.rect(6,232,4,4, P.connectionOnline===false ? '#000000' : C.green); P.text(P.clock||'--:--', 13, 231, C.creamD, 'tag', {sp:1});
  // battery (outline + 3 green cells), right side
  const bx=320-6-16, by=230; P.border(bx,by,14,8, C.creamD,1); P.rect(bx+14,by+2,2,4, C.creamD);
  for(let k=0;k<3;k++) P.rect(bx+2+k*3,by+2,2,4, C.green);
  // STATIC footer chrome mirroring the badge (navigation.py draw_footer): A/C arrows
  // either side + the contextual-B label centred. Purely a picture of what the badge
  // shows — /viewscreens never simulates the press (no paging/zoom/edit on the web).
  P.tri(58,230,'l', C.cream); P.tri(257,230,'r', C.cream);
  if(_footerB) P.text(_footerB, 160, 231, C.cream, 'tag', {sp:1, align:'c'});
}
// shared stat box — accent-bordered label+value card. Same 35px height & spacing wherever reused.
const CARD_H=35;
function card(P, x, y, w, label, value, n){
  const C=P.pal, a=accentPen(C,n);
  P.rect(x,y,w,CARD_H, C.panel);
  P.border(x,y,w,CARD_H, a.d,2);
  P.border(x+2,y+2,w-4,CARD_H-4, C.edge,1);
  P.rect(x+8, y+8, 4,4, a.c);                        // accent dot
  P.text(label, x+16, y+7, C.creamD, 'rowLabel', {sp:1});    // label — top margin 7
  P.text(value, x+8, y+18, a.c, 'rowValue', {sp:1, shadow:[1,1,a.sh]});  // value — 3px below label, 4px above box bottom
}

const SECLABEL_Y=32;   // shared: y of the section label on every screen (header +1 pushed all content down 1)

// shared progress bar — track + accent checker fill (2px tiles of c/c2) + 2px top highlight. Reused by
// every bar-row screen (PROJECTS / TOOLS / MODELS / VERSUS). frac is 0..1.
function bar(P, x, y, w, h, frac, n){
  const C=P.pal, a=accentPen(C,n), c=a.c, c2=a.d, cl=a.l;
  P.rect(x,y,w,h, C.track); P.border(x,y,w,h, C.edge,2);                 // track + inset edge
  const fw=Math.max(0,Math.min(w, Math.round(w*frac)));
  for(let py=0;py<h;py+=2) for(let px=0;px<fw;px+=2)                     // 2px checker of c / c2
    P.rect(x+px, y+py, 2, 2, ((px+py)/2)%2 ? c2 : c);
  if(fw>0) P.rect(x,y,fw,2, cl);                                        // top highlight line
}
// shared bar-row: NAME (left) + progress bar + VALUE (right), with two optional dim sub-lines under it.
// One definition for PROJECTS/TOOLS/MODELS/VERSUS so the rows are identical by construction.
const ROW_NAME_X=6, ROW_NAME_W=76, ROW_BAR_X=86, ROW_BAR_W=180, ROW_BAR_H=9, ROW_VAL_R=314;
function barRow(P, y, name, frac, value, n, sub1, sub2, nameRole, barX, barW){
  const C=P.pal; nameRole=nameRole||'rowLabel';                                    // name role is overridable (MODELS uses its own)
  const bx=barX||ROW_BAR_X, bw=barW||ROW_BAR_W;                                    // bar geometry is overridable (PROMPTS shifts, PROJECTS shortens)
  const _rlpx=(P.scale[nameRole]&&P.scale[nameRole].px)||10, maxC=Math.floor(ROW_NAME_W/(P.charW(_rlpx)+1)); if(name.length>maxC) name=name.slice(0,maxC);   // truncate to fit
  P.text(name, ROW_NAME_X, y, C.cream, nameRole, {sp:1});                          // name (bold)
  bar(P, bx, y, bw, ROW_BAR_H, frac, n);                                          // progress bar
  P.text(value, ROW_VAL_R, y, accentPen(C,n).c, 'rowValue', {align:'r'});           // value (right) — large, cap-top aligned with the name
  if(sub1) P.text(sub1, ROW_BAR_X, y+14, C.creamD, 'caption', {sp:1});            // sub-line 1 (1px below bar)
  if(sub2) P.text(sub2, ROW_BAR_X, y+25, C.creamD, 'caption', {sp:1});           // sub-line 2 (1px below sub-line 1)
}
function seclabel(P, text, y){
  const C=P.pal; P.rect(6,y,5,5, C.creamD);
  const w=P.text(text, 16, y, C.creamD, 'sectionLabel', {sp:2});
  for(let i=16+w+5;i<314;i+=6) P.rect(i,y+2,2,2, C.line);   // trailing dashed line
}

// distribute n columns across width w (gap between) — pixel-exact, fills w. Returns [{x,w},…]. Shared by the
// bar charts and the matrix so their columns line up when they use the same gap.
function cols(x, w, n, gap){
  const tg=(n-1)*gap, base=Math.floor((w-tg)/n), rem=(w-tg)-base*n, out=[]; let cx=x;
  for(let i=0;i<n;i++){ const cw=base+(i<rem?1:0); out.push({x:cx, w:cw}); cx+=cw+gap; }
  return out;
}
// shared vertical bar chart — bars bottom-aligned in (x,y,w,h); peak bar = Accent 1, rest = Accent 2, zero =
// faint stub; 2px top highlight. Reused by RHYTHM (hours / weekdays) and any future bar chart.
function vbars(P, x, y, w, h, arr, peak, gap){
  const C=P.pal, mx=Math.max.apply(null, arr.length?arr:[1])||1, cs=cols(x,w,arr.length||1,gap);
  arr.forEach((v,i)=>{ const c=cs[i], pk=i===peak;
    const bh = v===0 ? 2 : Math.max(Math.round(h*0.12), Math.round(v/mx*h)), by=y+h-bh;
    P.rect(c.x, by, c.w, bh, v===0?C.a2zero:(pk?C.a1:C.a2));
    if(v>0) P.rect(c.x, by, c.w, Math.min(2,bh), pk?C.a1l:C.a2l); });   // top highlight
}
// shared weekday×hour matrix — 7 rows × 24 cols, heat-ramped (4 active levels); columns align to a bar chart.
function rhythmMatrix(P, x, y, w, wh, ch, rgap, gap){
  const C=P.pal; wh=wh||[]; let mx=1;
  for(const row of wh) for(const v of (row||[])) if(v>mx) mx=v;
  const cs=cols(x,w,24,gap);
  for(let r=0;r<7;r++){ const row=wh[r]||[];
    for(let c=0;c<24;c++){ const v=row[c]||0, lvl=v===0?0:Math.min(4,Math.max(1,Math.ceil(v/mx*4)));
      P.rect(cs[c].x, y+r*(ch+rgap), cs[c].w, ch, lvl===0?C.heatZero:C.heat[lvl+1]); } }   // empty=heatZero, active=heat[2..5]
}

// shared head-to-head comparison row: LABEL (left) | me value (Accent 1) · rival value (Accent 2). One
// definition for VERSUS HUMAN / VS RECORDS / VS AWARDS so the columns line up. label='' draws just the values.
const CMP_LABEL_X=6, CMP_ME_C=134, CMP_DOT_X=195, CMP_RV_C=255;
function cmpRow(P, y, label, meVal, rivalVal, meNum, rvNum, hasRival, higherWins){
  const C=P.pal;
  if(label) P.text(label, CMP_LABEL_X, y, C.creamD, 'rowLabel', {sp:1});
  P.text(meVal,    CMP_ME_C, y, C.a1, 'compareValue', {align:'c'});
  P.text(rivalVal, CMP_RV_C, y, C.a2, 'compareValue', {align:'c'});
  // separator = win chevron (like /view): '>' me wins · '<' rival wins · '=' tie · '·' no rival.
  // "wins" respects the metric direction (higherWins=false ⇒ lower is better, e.g. BOTTLENECK).
  let sep='·';
  if(hasRival && meNum!=null && rvNum!=null){
    if(meNum===rvNum) sep='=';
    else sep=(higherWins ? meNum>rvNum : meNum<rvNum) ? '>' : '<';
  }
  P.text(sep, CMP_DOT_X, y, C.creamD, 'caption', {align:'c'});
}
// shared VERSUS-screen tag: SOLO (no rival) · STALE (rival configured but its last pull failed,
// peer._fetch.ok===false → numbers are last-known) · else the live label ('LIVE' / 'ALL TIME' / …).
function vsTag(has, rival, liveLabel){
  if(!has) return 'SOLO';
  return (rival && rival._fetch && rival._fetch.ok===false) ? 'STALE' : (liveLabel||'LIVE');
}

/* ---------- ACTIVITY ---------- */
const HEAT_ROWS=9, HEAT_COLS=12, HCELL_W=14, HCELL_H=12, HGAP=2;
const HX=6, HGRID_TOP=61;                                   // grid origin
const HRIGHT=HX + HEAT_COLS*(HCELL_W+HGAP) - HGAP;          // grid right edge (196)

function heatLevel(v, mx, prompts){
  let l = v===0?0:Math.min(5,Math.max(1,Math.ceil(v/mx*5)));
  if(!l && (prompts||0)>0) l=1; return l;                   // active-day floor (prompts>0 ⇒ never empty)
}
function drawActivity(P, d){
  const C=P.pal, t=d.totals||{}, meta=d.meta||{};
  chrome(P, 'ACTIVITY', 'TOKENS');   // top-right = active metric (days count dropped; ACTIVE card still shows N/M)
  seclabel(P, 'DAILY TOKENS', SECLABEL_Y);

  // --- heatmap density block (row-major: oldest top-left, today bottom-right) ---
  const rows=d.daily_activity||[], metric=dayMetric();
  const vals=rows.map(r=>r[metric]||0), mx=Math.max.apply(null, vals.length?vals:[1])||1;
  const n=vals.length, total=HEAT_ROWS*HEAT_COLS;
  for(let r=0;r<HEAT_ROWS;r++) for(let c=0;c<HEAT_COLS;c++){
    const x=HX+c*(HCELL_W+HGAP), y=HGRID_TOP+r*(HCELL_H+HGAP), di=n-total+(r*HEAT_COLS+c);
    if(di<0||di>=n){ P.border(x,y,HCELL_W,HCELL_H, C.heatZero,1); }   // not-yet-existing day: 1px outline
    else { P.rect(x,y,HCELL_W,HCELL_H, C.heat[ heatLevel(vals[di],mx,rows[di].prompts) ]); }
  }
  // corner labels with pixel triangles
  P.tri(6, 51, 'l', C.creamD); P.text((total-1)+' DAYS AGO', 14, 52, C.creamD, 'tag', {sp:1});   // arrow nudged up 1px
  const gridBottom=HGRID_TOP+HEAT_ROWS*(HCELL_H+HGAP)-HGAP;          // 184
  P.tri(HRIGHT-4, gridBottom+2, 'r', C.creamD);
  P.text('TODAY', HRIGHT-4-4, gridBottom+3, C.creamD, 'tag', {sp:1, align:'r'});   // TODAY text nudged down 1px

  // legend (LESS ▢▢▢▢▢ MORE), bottom-left, 4px above footer
  const ly=215; let lx=6;
  lx += P.text('LESS', lx, ly, C.creamD, 'legendLabel', {sp:1}) + 4;
  for(let k=1;k<=5;k++){ P.rect(lx,ly-1,8,8, C.heat[k]); P.border(lx,ly-1,8,8, C.edge,1); lx+=8+3; }
  P.text('MORE', lx+1, ly, C.creamD, 'legendLabel', {sp:1});

  // --- 4-card right stack: STREAK/BEST/ACTIVE/SESSIONS, alternating Accent 1 / Accent 2 (shared card()) ---
  const CX=320-6-104, CW=104, CGAP=8, CTOP=56;
  const cards=[['STREAK',(t.current_streak||0)+'D',1],['BEST',(t.longest_streak||0)+'D',2],
               ['ACTIVE',(t.active_days||0)+'/'+(meta.corpus_days||0),1],['SESSIONS',fmtInt(t.sessions),2]];
  cards.forEach((cd,i)=>card(P, CX, CTOP+i*(CARD_H+CGAP), CW, cd[0], cd[1], cd[2]));
}

/* ---------- CALENDAR (ACTIVITY) — week-aligned month grid (the ACTIVITY B-zoom) ---------- */
const MONTHS=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
function ymdLocal(dt){ const m=dt.getMonth()+1, day=dt.getDate(); return dt.getFullYear()+'-'+(m<10?'0':'')+m+'-'+(day<10?'0':'')+day; }
function fmtRecDate(s){ const m=/^(\d{4})-(\d{2})-(\d{2})/.exec(s||''); return m ? MONTHS[(+m[2])-1]+' '+(+m[3]) : ''; }   // "2026-05-09" → "MAY 9"
function drawCalendar(P, d){
  const C=P.pal, rows=d.daily_activity||[], metric=dayMetric();
  chrome(P, 'CALENDAR', 'TOKENS');   // top-right = active metric; the days count moved to the legend line
  // index days by local date; ramp uses the whole-corpus max (same as the heatmap)
  const map={}; let lastKey=null;
  rows.forEach(r=>{ if(r.date){ map[r.date]=r; lastKey=r.date; } });
  const vals=rows.map(r=>r[metric]||0), mx=Math.max.apply(null, vals.length?vals:[1])||1;
  // anchor "today" = last day; build the most-recent 5 weeks (Mon→Sun cols, oldest week on top)
  const anchor = lastKey ? new Date(lastKey+'T00:00:00') : new Date();
  const todW=(anchor.getDay()+6)%7, CAL_ROWS=5;
  const bottomMon=new Date(anchor); bottomMon.setDate(bottomMon.getDate()-todW);
  const gridStart=new Date(bottomMon); gridStart.setDate(gridStart.getDate()-(CAL_ROWS-1)*7);
  const cs=cols(6, 308, 7, 2), CELL_H=28, RGAP=2, HDR_Y=46, GRID_Y=56;
  ['M','T','W','T','F','S','S'].forEach((s,c)=>P.text(s, Math.round(cs[c].x+cs[c].w/2), HDR_Y, C.creamD, 'tag', {sp:1, align:'c'}));
  let spanA=null, spanB=null;
  for(let r=0;r<CAL_ROWS;r++) for(let c=0;c<7;c++){
    const dt=new Date(gridStart); dt.setDate(dt.getDate()+r*7+c);
    const key=ymdLocal(dt), e=map[key], future=dt>anchor;
    const cx=cs[c].x, cy=GRID_Y+r*(CELL_H+RGAP), cw=cs[c].w;
    if(!e||future){ P.border(cx,cy,cw,CELL_H, C.heatZero, 1); continue; }   // empty / not-yet-existing day
    if(!spanA) spanA=dt; spanB=dt;
    const l=heatLevel(e[metric]||0, mx, e.prompts), dark=l>=4;
    P.rect(cx,cy,cw,CELL_H, C.heat[l]);
    if(dt.getDate()===1) P.text(MONTHS[dt.getMonth()], cx+3, cy+3, dark?C.bg:C.creamD, 'tag', {sp:0});   // month tag on the 1st (small)
    P.text(String(dt.getDate()), cx+cw-3, cy+CELL_H-13, dark?C.bg:C.cream, 'rowValue', {sp:0, align:'r'}); // day-of-month, 2× (5x5 @10)
    if(key===lastKey) P.border(cx,cy,cw,CELL_H, C.cream, 1);                                              // today outline
  }
  // seclabel: DAILY TOKENS + the visible date range (like /view)
  const span = spanA ? (spanA.getDate()+' '+MONTHS[spanA.getMonth()]+' - '+spanB.getDate()+' '+MONTHS[spanB.getMonth()]) : '';   // '-' not '→' (Silkscreen lacks the arrow → falls back to a heavier font)
  seclabel(P, 'DAILY TOKENS'+(span?' • '+span:''), SECLABEL_Y);
  // LESS → MORE legend (same as the ACTIVITY heatmap), bottom-left + corpus-days count right-aligned
  const ly=215; let lx=6;
  lx += P.text('LESS', lx, ly, C.creamD, 'legendLabel', {sp:1}) + 4;
  for(let k=1;k<=5;k++){ P.rect(lx,ly-1,8,8, C.heat[k]); P.border(lx,ly-1,8,8, C.edge,1); lx+=8+3; }
  P.text('MORE', lx+1, ly, C.creamD, 'legendLabel', {sp:1});
  P.text((d.meta&&d.meta.corpus_days||0)+' DAYS', 314, ly, C.creamD, 'legendLabel', {sp:1, align:'r'});
}

/* ---------- FONT TEST (dev screen) — see every used size, labelled, to judge crispness on-device ---------- */
// DEV font-test — an OVERSIZED screen (not the 320×240 device size): every available font (native ≤16) at a
// range of crisp sizes — native ≤8px → up to 4× (8,16,24,32); ≤10px → up to 3× (e.g. 9,18,27); else 2×
// (e.g. 11→11,22 · 16→16,32). EACH SIZE gets its OWN bordered box with the green "NAME  NPX" label sitting
// just ABOVE the box; the sample text is top-left anchored inside so per-font offset/rendering quirks show.
const FONT_SAMPLE='WERTYQ 2.3M 1,467 13.8K 4/17 8% $302 2H 51M';
const FONTTEST_W=810, FONTTEST_H=2740;
// box background: false = solid C.panel; true = 1px checkerboard (C.panel + 25% lighter). Toggled on-canvas; ?ftgrid=1 starts it on.
let FONTTEST_GRID=(typeof location!=='undefined' && /[?&]ftgrid=1/.test(location.search));
let _ftGridHit=null;       // hitbox of the TOGGLE GRID control (canvas coords), set each draw
function drawFontTest(P){
  const C=P.pal, W=P.W, X=8, BW=W-16;
  P.clear(C.bg);
  const tw=P.text('FONT TEST', X, 6, C.a1, 13, {font:'pico'});
  // TOGGLE GRID — click to switch the text background between solid and a 1×1 pixel grid (dev aid for alignment)
  const tgx=X+tw+18, tgy=8, on=FONTTEST_GRID;
  P.border(tgx, tgy, 9, 9, C.creamD, 1);
  if(on) P.rect(tgx+2, tgy+2, 5, 5, C.a2);
  const lw=P.text('TOGGLE GRID', tgx+14, tgy, on?C.a2:C.creamD, 'caption', {sp:1});
  _ftGridHit={x:tgx-4, y:tgy-4, w:(14+lw)+8, h:17};
  P.text('native + multiples (≤8px ×4 · ≤10px ×3 · else ×2), sorted small to large', X, 25, C.creamD, 'caption');
  P.hline(X, 33, BW, C.line);
  // box background: solid, or a 1px checkerboard pattern (built once, tiles from canvas origin so the grid is continuous)
  let boxFill=null;
  if(FONTTEST_GRID){
    const tile=document.createElement('canvas'); tile.width=2; tile.height=2; const tx=tile.getContext('2d');
    tx.fillStyle=C.panel; tx.fillRect(0,0,2,2);
    tx.fillStyle=tint(C.panel,0.25); tx.fillRect(1,0,1,1); tx.fillRect(0,1,1,1);  // 25% lighter on the checker squares
    boxFill=P.x.createPattern(tile,'repeat');
  }
  const fillBox=(x,y,w,h)=>{ if(boxFill){ P.x.fillStyle=boxFill; P.x.fillRect(x,y,w,h); } else P.rect(x,y,w,h,C.panel); };
  // font list: built-ins (reference) + library fonts with native ≤16, sorted by native then name
  const list=[
    {key:'pico',  name:'PRESS START 2P', native:8},
    {key:'silk',  name:'SILKSCREEN',     native:8}
  ];
  const cat=(typeof window!=='undefined' && window.FONT_CATALOG) || null;
  if(cat&&cat.fonts) cat.fonts.forEach(f=>{ if(f.nativePx<=16) list.push({key:f.slug, name:(f.name||f.slug).toUpperCase(), native:f.nativePx}); });
  list.sort((a,b)=> a.native-b.native || (a.name<b.name?-1:a.name>b.name?1:0));
  const LBL=8, LBL_GAP=2, PAD=4, BOX_GAP=6, FONT_GAP=25;   // 25px between a font's last box and the next font's name
  let y=40;
  list.forEach(f=>{
    // crisp size multiples: ≤8px native → up to 4×, ≤10px → up to 3×, else 2×
    const maxMult = f.native<=8 ? 4 : f.native<=10 ? 3 : 2;
    const sizes=[]; for(let m=1;m<=maxMult;m++) sizes.push(f.native*m);
    sizes.forEach(px=>{
      P.text(f.name+'  '+px+'PX', X, y, C.a2, 8, {sp:1, font:'silk'});       // green label, ABOVE the box
      y += LBL + LBL_GAP;
      const boxH = px + PAD*2;
      fillBox(X, y, BW, boxH);
      P.border(X, y, BW, boxH, C.rim, 1);
      P.text(FONT_SAMPLE, X+6, y+PAD, C.cream, px, {font:f.key});            // sample top-left inside box
      y += boxH + BOX_GAP;
    });
    y += FONT_GAP - BOX_GAP;   // a little extra space between fonts
  });
}

/* ---------- TODAY (LIVE) — today's activity vs the daily average ---------- */
// 5×3 up/down triangle (the pixel fonts have no ▲/▼ glyph, so draw it).
function arrowUD(P, x, y, up, pen){
  if(up){ P.rect(x+2,y,1,1,pen); P.rect(x+1,y+1,3,1,pen); P.rect(x,y+2,5,1,pen); }     // ▲
  else  { P.rect(x,y,5,1,pen);   P.rect(x+1,y+1,3,1,pen); P.rect(x+2,y+2,1,1,pen); }   // ▼
}
// one TODAY row: LABEL + today value (Accent n) + right-aligned "AVG <x>" + arrow (green up / dim down).
function todayRow(P, y, label, now, avg, fmt, n){
  const C=P.pal, a=accentPen(C,n), up=now>=avg, cc=up?C.green:C.creamD;
  P.text(label, 6, y, C.cream, 'rowLabel', {sp:1});
  P.text(fmt(now), 88, y, a.c, 'rowValue', {sp:1, shadow:[1,1,a.sh]});
  const arX=314-5;
  arrowUD(P, arX, y+2, up, cc);
  P.text('AVG '+fmt(avg), arX-4, y, cc, 'caption', {sp:1, align:'r'});
}
function drawToday(P, d){
  const t=d.totals||{}, days=d.daily_activity||[];
  const today=days.length?days[days.length-1]:{tokens_io:0,prompts:0,sessions:0,active_min:0};
  const ad=Math.max(1, t.active_days||0);
  chrome(P, 'TODAY', 'VS AVG');
  seclabel(P, 'TODAY VS DAILY AVERAGE', SECLABEL_Y);
  const Y=54, PI=26;
  todayRow(P, Y+0*PI, 'TOKENS',   today[dayMetric()]||0,  tokVal(t)/ad,               fmtTokens, 1);
  todayRow(P, Y+1*PI, 'PROMPTS',  today.prompts||0,    (t.user_prompts||0)/ad,     n=>fmtInt(Math.round(n)), 2);
  todayRow(P, Y+2*PI, 'SESSIONS', today.sessions||0,   (t.sessions||0)/ad,         n=>String(Math.round(n)), 1);
  todayRow(P, Y+3*PI, 'ACTIVE',   today.active_min||0, (t.total_active_min||0)/ad, fmtMin, 2);
  // (SERVERS count now lives in the PROJECTS header)
}

/* ---------- USAGE LIMITS (LIVE) — session/weekly utilization bars + reset countdown cards ---------- */
// Mirrors /view's USAGE screen: YOUR USAGE (SESSION gold + WEEKLY teal utilization bars), an OPPONENT USAGE
// block (a rival's bars + per-row reset countdowns, shown only when a peer with limits exists), and a
// bottom-pinned RESETS section (my SESSION/WEEKLY reset countdowns as cards). My limits come from the separate
// /claude-limits.json feed (d.limits); the rival's from the competition feed (peers[0].limits). Countdowns are
// derived from absolute resets_at at paint time (exact); they refresh on each repaint (≤10 s via the book-cycle
// rerender) — live per-second ticking is the firmware's job.
// Top-right is intentionally blank for now; flip SHOW_CONN to surface a LIVE/STALE freshness chip later.
const SHOW_CONN=false;
// opponent usage row: LABEL + reset countdown (under the label) + utilization bar + pct. Same column geometry
// as barRow so YOUR and OPPONENT rows line up.
function oppRow(P, y, label, util, resetStr, n){
  const C=P.pal;
  P.text(label, ROW_NAME_X, y, C.cream, 'rowLabel', {sp:1});
  if(resetStr) P.text(resetStr, ROW_NAME_X, y+11, C.creamD, 'caption', {sp:1});   // reset countdown under the label
  bar(P, ROW_BAR_X, y, ROW_BAR_W, ROW_BAR_H, util!=null?Math.max(0,Math.min(1,util/100)):0, n);
  P.text(util!=null?Math.round(util)+'%':'-', ROW_VAL_R, y, accentPen(C,n).c, 'rowValue', {align:'r'});
}
function drawUsage(P, d){
  const C=P.pal, L=d.limits||{}, sess=L.session||{}, wk=L.weekly||{};
  chrome(P, 'USAGE LIMITS', '');   // top-right intentionally blank (set SHOW_CONN=true for a LIVE/STALE chip)
  if(SHOW_CONN){
    const spx=320-6-16, age=L.generated_at?(Date.now()-Date.parse(L.generated_at))/60000:999;
    const fresh=!L.stale && age>=0 && age<10, cc=fresh?C.green:C.creamD, ctext=fresh?'LIVE':'STALE';
    const tw=P.textW(ctext, (P.scale.tag&&P.scale.tag.px)||5, 1);
    P.text(ctext, spx-7, 9, cc, 'tag', {sp:1, align:'r'});
    P.rect(spx-7-tw-5, 10, 3,3, cc);                               // status dot left of the chip text
  }
  // YOUR USAGE — SESSION (Accent 1) + WEEKLY (Accent 2) utilization bar-rows (label + bar + pct)
  seclabel(P, 'YOUR USAGE', SECLABEL_Y);
  const sp=sess.utilization, wp=wk.utilization;
  barRow(P, 48, 'SESSION', sp!=null?Math.max(0,Math.min(1,sp/100)):0, sp!=null?Math.round(sp)+'%':'-', 1);
  barRow(P, 70, 'WEEKLY',  wp!=null?Math.max(0,Math.min(1,wp/100)):0, wp!=null?Math.round(wp)+'%':'-', 2);
  // OPPONENT USAGE — a rival's session/weekly bars (+ reset countdown under each label), shown only with a peer
  const rival=(d.competition&&d.competition.peers&&d.competition.peers[0])||null, rvLim=(rival&&rival.limits)||null;
  if(rvLim){
    seclabel(P, 'OPPONENT USAGE', 94);
    // stale rival data: resets_at stays correct until it passes, so keep the countdown ticking while it's
    // still in the future — but once it expires a fresh read would have delivered the NEXT window's
    // resets_at, which stale data can't, so blank it ('-') instead of pinning at 'NOW' forever.
    // Two stale layers, same symptom: our pull of his feed failing (_fetch.ok=false), and his own limits
    // poller serving last-known values because he hasn't run Claude Code lately (limits.stale=true).
    const rvStale=!!((rival._fetch && rival._fetch.ok===false) || rvLim.stale);
    const rvReset=b=>{ const s=secFrom(b); return (rvStale && s!=null && s<=0) ? '-' : fmtReset(s); };
    oppRow(P, 110, 'SESSION', (rvLim.session||{}).utilization, rvReset(rvLim.session), 1);
    oppRow(P, 134, 'WEEKLY',  (rvLim.weekly||{}).utilization,  rvReset(rvLim.weekly),  2);
  }
  // RESETS — my reset countdowns, pinned to the bottom (like /view's margin-top:auto)
  seclabel(P, 'RESETS', 171);
  const cw=cols(6, 308, 2, 8), cy=187;
  card(P, cw[0].x, cy, cw[0].w, 'SESSION RESET', fmtReset(secFrom(sess)), 1);
  card(P, cw[1].x, cy, cw[1].w, 'WEEKLY RESET',  fmtReset(secFrom(wk)),   2);
}

/* ---------- TOKEN USAGE — hero total + 30d trend sparkline + COST/CACHE cards ---------- */
// Default lens = no-cache (input+output), like every other /viewscreens screen (tokVal). The /view cache toggle
// (B) becomes the device toggle later; here we render the cache-free view. Sparkline reuses vbars (peak day
// in Accent 1); the two cards reuse card(). seclabel + hero echo the /view tokens screen.
function drawTokens(P, d){
  const C=P.pal, t=d.totals||{}, meta=d.meta||{}, cost=d.cost_estimate||{};
  chrome(P, 'TOKEN USAGE', 'ALL TIME');
  seclabel(P, _OPTS.tokenMode==='all'?'TOTAL TOKENS':'IN + OUT TOKENS', SECLABEL_Y);
  // hero — big total (left) + 2-line caption (right)
  P.text(fmtTokens(tokVal(t)), 6, 44, C.a1, 'heroValue', {sp:1, shadow:[1,1,C.a1sh]});
  P.text('OVER '+(meta.corpus_days||0)+' DAYS', 314, 45, C.creamD, 'caption', {sp:1, align:'r'});
  P.text(fmtInt(t.user_prompts)+' PROMPTS',     314, 57, C.creamD, 'caption', {sp:1, align:'r'});
  // 30-day token trend (no-cache per-day series) — peak day highlighted by vbars
  seclabel(P, 'TOKENS / DAY · 30D', 84);
  const days=(d.daily_activity||[]).slice(-30).map(x=>x[dayMetric()]||0);
  let pk=0; for(let i=1;i<days.length;i++) if(days[i]>days[pk]) pk=i;
  vbars(P, 6, 96, 308, 62, days, days.length?pk:-1, 1);
  // COST EST (Accent 1) + CACHE HIT (Accent 2) cards, side by side
  const CY=178, CW=150;
  card(P, 6,   CY, CW, 'COST EST',  fmtUSD(cost.total_usd||0),                       1);
  card(P, 164, CY, CW, 'CACHE HIT', Math.round((t.cache_hit_ratio||0)*100)+'%',      2);
}

/* ---------- PROMPTS (TOKENS) — prompts by window + 30-day prompts/day sparkline (the TOKENS B-variant) ---------- */
function drawPrompts(P, d){
  const C=P.pal, t=d.totals||{};
  chrome(P, 'PROMPTS', 'ALL TIME');
  seclabel(P, 'PROMPTS • BY WINDOW', SECLABEL_Y);
  const prd=(d.daily_activity||[]).map(x=>x.prompts||0), sumLast=k=>prd.slice(-k).reduce((a,b)=>a+b,0);
  const rows=[['24H',sumLast(1),1],['7D',sumLast(7),2],['30D',sumLast(30),2],['TOTAL',t.user_prompts||0,2]];
  const mx=Math.max(t.user_prompts||0,1), LIST_Y=48, PITCH=22;
  rows.forEach((r,i)=>barRow(P, LIST_Y+i*PITCH, r[0], r[1]/mx, fmtInt(r[1]), r[2], null, null, null, ROW_BAR_X-30));   // bars shifted 30px left for more space before the numbers
  // 30-day prompts/day trend — peak day highlighted
  seclabel(P, 'PROMPTS / DAY • 30D', 144);
  const days=prd.slice(-30); let pk=0; for(let i=1;i<days.length;i++) if(days[i]>days[pk]) pk=i;
  vbars(P, 6, 156, 308, 58, days, days.length?pk:-1, 1);
}

/* ---------- VERSUS RECORDS — head-to-head personal bests (all-time) ---------- */
function drawVsRecords(P, d){
  const C=P.pal, cp=d.competition||{}, me=cp.me||{}, rv=(cp.peers&&cp.peers[0])||{}, has=!!(cp.peers&&cp.peers.length);
  const mM=me.metrics||{}, rM=rv.metrics||{};
  const peakOf=m=> (m.peak_day_io||m.peak_day||{});   // no-cache default: the cache-free biggest day
  const mePk=peakOf(mM), rvPk=peakOf(rM);
  chrome(P, 'VERSUS - RECORDS', vsTag(has, rv, 'ALL TIME'));
  seclabel(P, 'PERSONAL BESTS', SECLABEL_Y);
  // header — YOU VS RIVAL (aliases)
  const hy=46;
  P.text((me.alias||'YOU').toUpperCase(),                  CMP_ME_C, hy, C.a1, 'rowLabel', {align:'c'});
  P.text('VS',                                             CMP_DOT_X, hy, C.creamD, 'caption', {sp:1, align:'c'});
  P.text(has?(rv.alias||'RIVAL').toUpperCase():'NO RIVAL', CMP_RV_C, hy, C.a2, 'rowLabel', {align:'c'});
  const rvv=(s)=> has? s : '-';
  // all rows: higher wins. [label, meStr, rivalStr, meNum, rivalNum]
  const rows=[
    ['STREAK',   (mM.current_streak||0)+'D', rvv((rM.current_streak||0)+'D'), mM.current_streak, rM.current_streak],
    ['BEST',     (mM.longest_streak||0)+'D', rvv((rM.longest_streak||0)+'D'), mM.longest_streak, rM.longest_streak],
    ['PEAKDAY',  fmtTokens(mePk.tokens),     rvv(fmtTokens(rvPk.tokens)),     mePk.tokens, rvPk.tokens],
    ['ENDURE',   fmtMin(mM.endurance_longest_session_min), rvv(fmtMin(rM.endurance_longest_session_min)), mM.endurance_longest_session_min, rM.endurance_longest_session_min],
    ['CACHEHIT', pct1((mM.cache_hit_ratio||0)*100), rvv(pct1((rM.cache_hit_ratio||0)*100)), mM.cache_hit_ratio, rM.cache_hit_ratio]
  ];
  const ry=66, pitch=22;
  rows.forEach((r,i)=>cmpRow(P, ry+i*pitch, r[0], r[1], r[2], r[3], r[4], has, true));
}

/* ---------- PROJECTS — per-project bar-rows (name + tokens bar + value, two sub-lines) ---------- */
// shared top-4 project list (mine on PROJECTS, the rival's on VS PROJECTS): name + tokens bar + two sub-lines.
function projectRows(P, projs){
  const pmax = projs.length ? (tokVal(projs[0])||1) : 1;
  const LIST_Y=48, PITCH=46;   // +2px before the first project (vs the seclabel, which itself moved +1)
  projs.slice(0,4).forEach((p,i)=>{
    const time=p.total_active_min?fmtMin(p.total_active_min):'';
    const agents=fmtInt(p.agent_launches||0)+' AGENTS';
    const cost=(p.cost_estimate_usd!=null)?fmtUSD(p.cost_estimate_usd):'';
    const sub1=[time,agents,cost].filter(Boolean).join(' • ');
    const sub2=fmtInt(p.user_prompts||0)+' PROMPTS • '+fmtCompact(p.user_words||0)+' WORDS';
    barRow(P, LIST_Y+i*PITCH, (p.name||'').toUpperCase(), tokVal(p)/pmax, fmtTokens(tokVal(p)), i===0?1:2, sub1, sub2, null, null, ROW_BAR_W-8);   // bars 8px shorter for number space
  });
}
function drawProjects(P, d){
  const projs=(d.projects||[]).slice().sort((a,b)=>tokVal(b)-tokVal(a));
  const nsrv=((d.meta||{}).servers||[]).length||1;
  chrome(P, 'PROJECTS', 'SERVERS: '+nsrv+' • PROJECTS: '+projs.length);
  seclabel(P, 'BY TOKENS • '+(_OPTS.tokenMode==='all'?'ALL':'NO CACHE'), SECLABEL_Y);
  projectRows(P, projs);
}
/* ---------- VS PROJECTS (VERSUS) — the rival's per-project breakdown, like my PROJECTS screen ---------- */
function drawVsProjects(P, d){
  const C=P.pal, cp=d.competition||{}, rival=(cp.peers&&cp.peers[0])||null, has=!!rival;
  const projs=((rival&&rival.projects)||[]).slice().sort((a,b)=>tokVal(b)-tokVal(a));
  chrome(P, 'VERSUS - PROJECTS', 'PROJECTS: '+projs.length);
  seclabel(P, (rival?(rival.alias||'RIVAL').toUpperCase():'RIVAL')+' • BY TOKENS • '+(_OPTS.tokenMode==='all'?'ALL':'NO CACHE'), SECLABEL_Y);
  if(!projs.length){ P.text(has?'NO PROJECT DATA YET':'NO RIVAL', 6, 60, C.creamD, 'rowLabel', {sp:1}); return; }
  projectRows(P, projs);
}

/* ---------- RHYTHM — hour + weekday bar charts and the weekday×hour matrix ---------- */
const RDAYS=['MON','TUE','WED','THU','FRI','SAT','SUN'], RDAY1=['M','T','W','T','F','S','S'];
function hourLabel(h){ h=((h%24)+24)%24; return h===0?'12AM':h===12?'12PM':h<12?h+'AM':(h-12)+'PM'; }
function drawRhythm(P, d){
  const C=P.pal, t=d.totals||{}, h=d.histograms||{}, X=6, W=308;
  chrome(P, 'RHYTHM', 'PROMPTS');   // top-right = active metric (the peak hour is the highlighted bar)
  // BY HOUR (24 bars) + axis — tall, since the matrix is now a toggle-only view (frees the lower 2/3)
  seclabel(P, 'BY HOUR • 0-23', SECLABEL_Y);
  const hy=44, hh=84; vbars(P, X, hy, W, hh, h.hours||[], t.peak_hour, 2);
  { const cs=cols(X,W,24,2), HDX={0:0,6:0,12:-1,18:-1,23:0}; [0,6,12,18,23].forEach(i=>P.text(String(i), Math.round(cs[i].x+cs[i].w/2)+HDX[i], hy+hh+2, C.creamD, 'axisTick', {align:'c'})); }
  // BY WEEKDAY (7 bars) + axis
  seclabel(P, 'BY WEEKDAY', 144);
  const wy=156, wh1=54; vbars(P, X, wy, W, wh1, h.weekdays||[], t.peak_weekday, 6);
  { const cs=cols(X,W,7,6); RDAY1.forEach((s,i)=>P.text(s, Math.round(cs[i].x+cs[i].w/2), wy+wh1+2, C.creamD, 'axisTick', {align:'c'})); }
}

/* ---------- RHYTHM MATRIX (ACTIVITY) — weekday×hour heatmap (the RHYTHM B-variant) ---------- */
function drawRhythmMatrix(P, d){
  const C=P.pal, wh=(d.histograms&&d.histograms.weekday_hour)||[];
  // busiest cell (peak weekday × hour)
  let bR=0, bC=0, bV=-1;
  for(let r=0;r<wh.length;r++){ const row=wh[r]||[]; for(let c=0;c<row.length;c++) if(row[c]>bV){ bV=row[c]; bR=r; bC=c; } }
  chrome(P, 'RHYTHM MATRIX', 'PROMPTS');   // top-right = active metric (was 'WHEN')
  seclabel(P, 'WEEKDAY × HOUR', SECLABEL_Y);
  const MX=18, MW=296, MY=52, CH=18, RGAP=3;
  rhythmMatrix(P, MX, MY, MW, wh, CH, RGAP, 1);
  RDAY1.forEach((s,r)=>P.text(s, 6, MY+r*(CH+RGAP)+Math.round(CH/2)-3, C.creamD, 'tag', {sp:0}));   // weekday rail
  const cs=cols(MX, MW, 24, 1), ax=MY+7*(CH+RGAP)+1, HDX={12:-1,18:-1};                              // hour axis under (12/18 nudged 1px left)
  [0,6,12,18,23].forEach(i=>P.text(String(i), Math.round(cs[i].x+cs[i].w/2)+(HDX[i]||0), ax, C.creamD, 'axisTick', {align:'c'}));
  const p2=n=>(n<10?'0':'')+n;
  const busy = bV>0 ? RDAYS[bR]+' '+p2(bC)+'-'+p2((bC+1)%24) : '-';   // hour range, e.g. "MON 14-15"
  P.text('BUSIEST • '+busy, 6, ax+14, C.creamD, 'caption', {sp:1});
}

// Screens carry a `cat` (category). The rack shows every screen grouped by category; the device nav (later)
// is up/down = category, left/right = screen within a category. A "toggle group" (undecided) would just be a
// category that collapses a primary+secondary pair — pure metadata. Old toggle-hidden views (ACTIVITY
// calendar, RHYTHM matrix, …) get ported as their own screens here.
const CATEGORY_ORDER = ['LIVE','TOKENS','ACTIVITY','BREAKDOWN','VERSUS','TROPHIES','OPTIONS','DEV'];
/* ---------- VERSUS — head-to-head token race (24h/7d/30d/all) + agents launched ---------- */
function drawVersus(P, d){
  const C=P.pal, cp=d.competition||{}, me=cp.me||{}, rv=(cp.peers&&cp.peers[0])||{}, has=!!(cp.peers&&cp.peers.length);
  const tok=(o,k)=> (o&&o.windows&&o.windows[k]) ? tokVal(o.windows[k]) : 0;   // input+output (no-cache), the truer race
  chrome(P, 'VERSUS', vsTag(has, rv, 'LIVE'));
  seclabel(P, 'TOKEN RACE • '+(_OPTS.tokenMode==='all'?'ALL':'NO CACHE'), SECLABEL_Y);
  // header — YOU VS RIVAL (aliases)
  const hy=46;
  P.text((me.alias||'YOU').toUpperCase(),                  CMP_ME_C, hy, C.a1, 'rowLabel', {align:'c'});
  P.text('VS',                                             CMP_DOT_X, hy, C.creamD, 'caption', {sp:1, align:'c'});
  P.text(has?(rv.alias||'RIVAL').toUpperCase():'NO RIVAL', CMP_RV_C, hy, C.a2, 'rowLabel', {align:'c'});
  // token race rows (higher wins) — me vs rival per window
  const rvv=(s)=> has? s : '-';
  const periods=[['24H','24h'],['7D','7d'],['30D','30d'],['TOTAL','all']];
  const ry=66, pitch=22;
  periods.forEach((p,i)=>{ const mv=tok(me,p[1]), rvN=tok(rv,p[1]);
    cmpRow(P, ry+i*pitch, p[0], fmtTokens(mv), rvv(fmtTokens(rvN)), mv, rvN, has, true); });
  // AGENTS — all-time subagent launches (rival '-' until they ship agents_total)
  seclabel(P, 'AGENTS', 156);
  const mA=(me.metrics&&me.metrics.agents_total), rA=(rv.metrics&&rv.metrics.agents_total);
  cmpRow(P, 174, 'LAUNCHED', mA!=null?fmtInt(mA):'-', (has&&rA!=null)?fmtInt(rA):'-', mA, rA, has, true);
}

/* ---------- VERSUS HUMAN — head-to-head effort: me vs rival across 8 metrics ---------- */
function drawVsHuman(P, d){
  const C=P.pal, cp=d.competition||{}, me=cp.me||{}, rv=(cp.peers&&cp.peers[0])||{}, has=!!(cp.peers&&cp.peers.length);
  const mM=me.metrics||{}, rM=rv.metrics||{}, mW=(me.windows&&me.windows.all)||{}, rW=(rv.windows&&rv.windows.all)||{};
  chrome(P, 'VERSUS - HUMAN', vsTag(has, rv, 'LIVE'));
  seclabel(P, 'HUMAN EFFORT • ALL', SECLABEL_Y);
  // header — YOU VS RIVAL (aliases)
  const hy=46;
  P.text((me.alias||'YOU').toUpperCase(),                  CMP_ME_C, hy, C.a1, 'rowLabel', {align:'c'});
  P.text('VS',                                             CMP_DOT_X, hy, C.creamD, 'caption', {sp:1, align:'c'});
  P.text(has?(rv.alias||'RIVAL').toUpperCase():'NO RIVAL', CMP_RV_C, hy, C.a2, 'rowLabel', {align:'c'});
  const dash='-', rvv=(s)=> has? s : dash;
  // [label, meStr, rivalStr, meNum, rivalNum, higherWins] — higherWins=false ⇒ lower is better (BOTTLENECK)
  const rows=[
    ['WORDS',    fmtCompact(mM.words_typed_total), rvv(fmtCompact(rM.words_typed_total)), mM.words_typed_total, rM.words_typed_total, true],
    ['CHARS',    fmtCompact(mM.user_chars_typed),  rvv(fmtCompact(rM.user_chars_typed)),  mM.user_chars_typed,  rM.user_chars_typed,  true],
    ['PROMPTS',  fmtInt(mM.prompts_total),         rvv(fmtInt(rM.prompts_total)),         mM.prompts_total,     rM.prompts_total,     true],
    ['LEVERAGE', fmtCompact(levOf(mW)),            rvv(fmtCompact(levOf(rW))),            levOf(mW),            levOf(rW),            true],
    ['NIGHTOWL', pct1(mW.night_owl_pct),           rvv(pct1(rW.night_owl_pct)),           mW.night_owl_pct,     rW.night_owl_pct,     true],
    ['BOTTLENK', fmtDur(mM.bottleneck_sec_total),  rvv(fmtDur(rM.bottleneck_sec_total)),  mM.bottleneck_sec_total, rM.bottleneck_sec_total, false],
    ['ACTIVE',   fmtMin(mM.total_active_min),      rvv(fmtMin(rM.total_active_min)),      mM.total_active_min,  rM.total_active_min,  true],
    ['DAYS',     fmtInt(mM.active_days),           rvv(fmtInt(rM.active_days)),           mM.active_days,       rM.active_days,       true]
  ];
  const ry=66, pitch=19;   // +4px under the nicknames; 2px tighter line pitch
  rows.forEach((r,i)=>cmpRow(P, ry+i*pitch, r[0], r[1], r[2], r[3], r[4], has, r[5]));
}

/* ---------- VS BEST DAY (VERSUS) — single-day personal bests, me vs rival (the VERSUS HUMAN B-variant) ---------- */
function drawVsHumanBest(P, d){
  const C=P.pal, cp=d.competition||{}, me=cp.me||{}, rv=(cp.peers&&cp.peers[0])||{}, has=!!(cp.peers&&cp.peers.length);
  const mM=me.metrics||{}, rM=rv.metrics||{};
  chrome(P, 'VERSUS - BEST DAY', vsTag(has, rv, 'LIVE'));
  seclabel(P, 'BEST SINGLE DAY', SECLABEL_Y);
  const hy=46;
  P.text((me.alias||'YOU').toUpperCase(),                  CMP_ME_C, hy, C.a1, 'rowLabel', {align:'c'});
  P.text('VS',                                             CMP_DOT_X, hy, C.creamD, 'caption', {sp:1, align:'c'});
  P.text(has?(rv.alias||'RIVAL').toUpperCase():'NO RIVAL', CMP_RV_C, hy, C.a2, 'rowLabel', {align:'c'});
  // one record family per row (higher wins): value head-to-head + each side's date underneath
  const recs=[['WORDS','record_day_words',fmtCompact],['PROMPTS','record_day_prompts',fmtInt],
              ['ACTIVE','record_day_active_min',fmtMin],['SESSIONS','record_day_sessions',fmtInt]];
  const ry=68, pitch=32;
  recs.forEach((rec,i)=>{ const y=ry+i*pitch, mr=mM[rec[1]]||{}, rr=rM[rec[1]]||{};
    cmpRow(P, y, rec[0], mr.value!=null?rec[2](mr.value):'-', (has&&rr.value!=null)?rec[2](rr.value):'-', mr.value, rr.value, has, true);
    P.text(fmtRecDate(mr.date), CMP_ME_C, y+11, C.creamD, 'caption', {align:'c'});
    if(has) P.text(fmtRecDate(rr.date), CMP_RV_C, y+11, C.creamD, 'caption', {align:'c'});
  });
}

/* ---------- WORDS (BREAKDOWN) — human-input volume + a "= N× <book>" flourish + EFFORT cards ---------- */
// Book-comparison table (ported from /view): words written vs famous books, "your words = N× <title>". /view
// rotates a random book each render; here we pick deterministically (stable per data, no Math.random) — the
// rotation, like other time-based behaviour, is deferred to the firmware.
const BOOKS=[
  {t:"Fahrenheit 451",a:"Ray Bradbury",w:46000},{t:"Brave New World",a:"Aldous Huxley",w:64000},
  {t:"Do Androids Dream?",a:"Philip K. Dick",w:64000},{t:"Neuromancer",a:"William Gibson",w:68000},
  {t:"Frankenstein",a:"Mary Shelley",w:75000},{t:"Canticle for Leibowitz",a:"Walter M. Miller Jr.",w:83000},
  {t:"Cryptonomicon",a:"Neal Stephenson",w:412000},{t:"Atlas Shrugged",a:"Ayn Rand",w:565000},
  {t:"Steppenwolf",a:"Hermann Hesse",w:67000},{t:"The Glass Bead Game",a:"Hermann Hesse",w:140000},
  {t:"The Alchemist",a:"Paulo Coelho",w:39000},{t:"The Little Prince",a:"Antoine de Saint-Exupery",w:17000},
  {t:"Jonathan Livingston Seagull",a:"Richard Bach",w:10000},{t:"Zen in the Art of Archery",a:"Eugen Herrigel",w:20000},
  {t:"Crime and Punishment",a:"Fyodor Dostoevsky",w:211000},{t:"The Idiot",a:"Fyodor Dostoevsky",w:242000},
  {t:"Manufacturing Consent",a:"Edward S. Herman & Noam Chomsky",w:103000},{t:"1984",a:"George Orwell",w:88942},
  {t:"Borderliners",a:"Peter Hoeg",w:75000},{t:"Understanding Power",a:"Noam Chomsky",w:125000},
  {t:"Necessary Illusions",a:"Noam Chomsky",w:120000},{t:"Scattered Minds",a:"Gabor Mate",w:85000},
  {t:"Beyond Chutzpah",a:"Norman Finkelstein",w:100000},{t:"The Mustard Seed",a:"Bhagwan Shree Rajneesh",w:140000},
  {t:"Free to Choose",a:"Milton & Rose Friedman",w:88000},{t:"Sea-Wolf",a:"Jack London",w:57000},
  {t:"I, Robot",a:"Isaac Asimov",w:69000},{t:"Foundation",a:"Isaac Asimov",w:68000},
  {t:"Dune",a:"Frank Herbert",w:188000},{t:"Out of the Silent Planet",a:"C.S. Lewis",w:58000},
  {t:"Notes from the Underground",a:"Fyodor Dostoevsky",w:19000},{t:"The Silo Saga",a:"Hugh Howey",w:360000},
  {t:"A Tale of Two Cities",a:"Charles J.H. Dickens",w:135000},{t:"Great Expectations",a:"Charles J.H. Dickens",w:183000},
  {t:"Oliver Twist",a:"Charles J.H. Dickens",w:155000},{t:"The Road",a:"Cormac McCarthy",w:58000},
  {t:"Animal Farm",a:"George Orwell",w:29966},{t:"Homage to Catalonia",a:"George Orwell",w:38000},
  {t:"Pelle the Conqueror",a:"Martin A. Nexo",w:190000},{t:"A Clockwork Orange",a:"J. Anthony Burgess W.",w:61000},
  {t:"Starship Troopers",a:"Robert A. Heinlein",w:120000},{t:"Space Odyssey series",a:"Arthur C. Clarke",w:260000},
  {t:"The Hobbit",a:"J.R.R. Tolkien",w:95000},{t:"The Lord of the Rings",a:"J.R.R. Tolkien",w:455000},
  {t:"The Silmarillion",a:"J.R.R. Tolkien",w:130000},{t:"The Martian",a:"Andy Weir",w:104000},
  {t:"A Song of Ice and Fire",a:"George R.R. Martin",w:1770000},{t:"The Art of War",a:"Sun Tzu",w:6500},
  {t:"Alice in Wonderland",a:"Lewis Carroll",w:26000},{t:"Through the Looking Glass",a:"Lewis Carroll",w:27000},
  {t:"Discworld",a:"Terry Pratchett",w:8000000},{t:"Hyperion Cantos",a:"Dan Simmons",w:450000},
  {t:"The Witcher Saga",a:"Andrzej Sapkowski",w:350000},{t:"A New Earth",a:"Eckhart Tolle",w:72000},
  {t:"The Handmaid's Tale",a:"Margaret E. Atwood",w:100000},{t:"Misery",a:"Stephen King",w:170000},
  {t:"The Iliad",a:"Homer",w:152000},{t:"The Odyssey",a:"Homer",w:121000},
  {t:"Ready Player One",a:"Ernest C. Cline",w:137000},{t:"The Time Machine",a:"H.G. Wells",w:32000}
];
// WORDS book line rotates every 10 s to a fresh random title (matches /view's BOOK_CYCLE_MS=10000).
let bookLineIdx=-1;
function cycleBook(){ if(!BOOKS.length) return; let n; do{ n=Math.floor(Math.random()*BOOKS.length); }while(BOOKS.length>1 && n===bookLineIdx); bookLineIdx=n; viewscreensRerender(); }
function drawWords(P, d){
  const C=P.pal, t=d.totals||{}, cp=d.competition||{}, mM=(cp.me&&cp.me.metrics)||{};
  chrome(P, 'WORDS', 'ALL TIME');
  seclabel(P, 'HUMAN INPUT', SECLABEL_Y);
  // two hero rows: WORDS (Accent 1) + CHARS (Accent 2), each big number left + 2-line caption right
  P.text(fmtCompact(t.user_words), 6, 44, C.a1, 'heroValue', {sp:1, shadow:[1,1,C.a1sh]});
  P.text('WORDS WRITTEN',          314, 45, C.creamD, 'caption', {sp:1, align:'r'});
  P.text(fmtInt(t.user_prompts)+' PROMPTS', 314, 57, C.creamD, 'caption', {sp:1, align:'r'});
  // +10 from here down: a 10px gap added between WORDS WRITTEN and CHARACTERS (first hero stays put)
  P.text(fmtCompact(t.user_chars_typed), 6, 86, C.a2, 'heroValue', {sp:1, shadow:[1,1,C.a2sh]});
  P.text('CHARACTERS', 314, 87, C.creamD, 'caption', {sp:1, align:'r'});
  P.text('TYPED',      314, 99, C.creamD, 'caption', {sp:1, align:'r'});
  // book line: "= N× <TITLE>" + "BY <AUTHOR>" — deterministic pick keyed on the word count
  const w=t.user_words||0;
  if(w && BOOKS.length){
    if(bookLineIdx<0 || bookLineIdx>=BOOKS.length) bookLineIdx=w%BOOKS.length;   // initial pick; cycleBook() rotates it every 10 s
    const b=BOOKS[bookLineIdx], mult=w/b.w, m=mult>=10?Math.round(mult):(Math.round(mult*10)/10);
    const by=128;   // 108 +10 (the below-hero shift) +10 (book-specific nudge) = +20
    const mw=P.text('= '+m+'X', 6, by+4, C.a1, 'rowValue', {sp:1, shadow:[1,1,C.a1sh]});
    const tx=6+mw+8, px=(P.scale.rowLabel&&P.scale.rowLabel.px)||10, maxC=Math.floor((314-tx)/(P.charW(px)+1));
    let title=b.t.toUpperCase(); if(title.length>maxC) title=title.slice(0,maxC);
    P.text(title, tx, by, C.cream, 'rowLabel', {sp:1});
    P.text('BY '+(b.a||'').toUpperCase(), tx, by+11, C.creamD, 'caption', {sp:1});
  }
  // EFFORT — three cards: PROMPTS / LEVERAGE / BOTTLENECK
  seclabel(P, 'EFFORT', 171);
  const lev=t.user_prompts?Math.round(tokVal(t)/t.user_prompts):0;
  const cw=cols(6, 308, 3, 6), cy=187;   // box bottom (cy+CARD_H=222) sits 5px above the footer (FOOTER_Y=227)
  card(P, cw[0].x, cy, cw[0].w, 'PROMPTS',  fmtInt(t.user_prompts),           1);
  card(P, cw[1].x, cy, cw[1].w, 'LEVERAGE', fmtCompact(lev),                  2);
  card(P, cw[2].x, cy, cw[2].w, 'BOTTLENK', fmtDur(mM.bottleneck_sec_total),  1);
}

/* ---------- TOOLS (BREAKDOWN) — top tools by call count (bar-rows) ---------- */
function drawTools(P, d){
  const t=d.totals||{}, tools=(d.top_tools||[]).slice(0,8), tmax=tools.length?(tools[0].count||1):1;
  chrome(P, 'TOOLS', fmtInt(t.tool_uses)+' USES');
  seclabel(P, 'TOP TOOLS', SECLABEL_Y);
  const LIST_Y=48, PITCH=22;
  tools.forEach((tt,i)=>barRow(P, LIST_Y+i*PITCH, (tt.name||'').toUpperCase(),
    (tt.count||0)/tmax, fmtCompact(tt.count), i===0?1:2,
    undefined, undefined, undefined, undefined, ROW_BAR_W-10));   // bar 10px shorter so high counts (10.2K+) clear it
}

/* ---------- MODELS (BREAKDOWN) — share stack + legend + per-model rows (by turns) ---------- */
function shortModel(n){ if(!n) return '-'; n=String(n);   // "claude-opus-4-7" -> "OPUS 4.7"
  const m=n.match(/(opus|sonnet|haiku)\D*(\d+)\D+(\d+)/i);
  return m ? m[1].toUpperCase()+' '+m[2]+'.'+m[3] : n.replace(/^claude-/,'').toUpperCase(); }
function drawModels(P, d){
  // share colours: Accent 1, Accent 2, then both at -15% saturation/lightness — 4 distinct pens, pattern
  // repeats in order so a model's colour is recoverable from its position even when pens recur.
  const C=P.pal, dim=h=>{ const [hh,s,v]=rgbToHsv.apply(null,parseHex(h)); return hsvToHex(hh, s-0.15, v-0.15); };
  const COLS=[C.a1, C.a2, dim(C.a1), dim(C.a2)];
  const models=(d.models||[]).slice().sort((a,b)=>(b.pct||0)-(a.pct||0));
  chrome(P, 'MODELS', models.length+' MODEL'+(models.length===1?'':'S'));
  seclabel(P, 'MODEL SHARE', SECLABEL_Y);
  // SHARE shows up to 10 models (5 per legend row, 2 rows); OTHER folds anything beyond 10
  const shareTop=models.slice(0,10), otherPct=Math.max(0,100-shareTop.reduce((s,m)=>s+(m.pct||0),0));
  const segs=shareTop.map((m,i)=>({lab:shortModel(m.name),pct:m.pct||0,col:COLS[i%COLS.length]}));
  if(models.length>10 && otherPct>0.5) segs.push({lab:'OTHER',pct:otherPct,col:C.creamD});
  // stacked share bar (segments proportional to pct)
  const SX=6, SW=308, SY=44, SH=12; let sx=SX;
  P.rect(SX,SY,SW,SH, C.track);
  segs.forEach(s=>{ const w=Math.round(SW*s.pct/100); P.rect(sx,SY,w,SH, s.col); sx+=w; });
  P.border(SX,SY,SW,SH, C.edge,1);
  // legend — fixed 5-per-row grid (cols distributed across the width, 4px gap), 6th–10th wrap to a 2nd row
  const PERROW=5, lgCols=cols(SX,SW,PERROW,4), LROW_H=11, LY0=SY+SH+7;
  segs.forEach((s,i)=>{ const cx=lgCols[i%PERROW].x, cy=LY0+Math.floor(i/PERROW)*LROW_H;
    P.rect(cx,cy-2,6,6, s.col); P.border(cx,cy-2,6,6, C.edge,1);     // swatch nudged up 2px to sit with the small label
    P.text(s.lab, cx+9, cy-1, C.creamD, 'modelShareLabel', {sp:1}); });
  // per-model rows by turns — capped at 6 (fits the remaining space). +36px below the last legend row.
  const lgRows=Math.ceil(segs.length/PERROW), byY=LY0+(lgRows-1)*LROW_H+36;
  seclabel(P, 'BY TURNS', byY);
  const turnTop=models.slice(0,6), mmax=turnTop.length?(turnTop[0].turns||1):1, LIST_Y=byY+14;
  const PITCH=turnTop.length?Math.min(22, Math.floor((222-LIST_Y)/turnTop.length)):22;
  turnTop.forEach((m,i)=>barRow(P, LIST_Y+i*PITCH, shortModel(m.name),
    (m.turns||0)/mmax, fmtCompact(m.turns), i===0?1:2, null, null, 'modelTurnLabel'));
}

/* ---------- TROPHIES — 14 families × 4 tiers; grid of glyph + name + pips (+ NEXT UP / VS AWARDS) ---------- */
// Glyphs as [x,y,w,h] rects in a 12×12 box (ported from /view's TROPHY_GLYPHS SVGs).
const TROPHY_GLYPHS={
  titan:[[3,2,6,2],[2,4,8,2],[3,6,6,2],[2,8,8,2]], prompter:[[1,2,10,6],[3,8,3,2],[3,4,2,2],[6,4,2,2]],
  novelist:[[8,1,2,2],[6,3,2,2],[4,5,2,2],[3,7,2,2],[2,9,4,1]], flame:[[5,1,2,2],[4,3,4,2],[3,5,6,3],[3,8,6,2],[4,10,4,1]],
  calendar:[[3,1,1,2],[8,1,1,2],[2,2,8,2],[2,4,8,6],[4,6,2,2]], flag:[[3,1,1,10],[4,2,6,4]],
  gear:[[4,4,4,4],[5,1,2,2],[5,9,2,2],[1,5,2,2],[9,5,2,2]], moon:[[3,2,6,2],[2,4,4,2],[2,6,4,2],[3,8,6,2],[9,3,1,1]],
  wrench:[[2,8,2,2],[3,6,2,2],[5,4,2,2],[7,2,3,3]], star:[[5,0,2,12],[0,5,12,2],[2,2,2,2],[8,2,2,2],[2,8,2,2],[8,8,2,2]],
  robot:[[5,1,2,1],[3,2,6,1],[2,3,8,7]], chars:[[5,2,2,1],[4,3,1,7],[7,3,1,7],[5,6,2,1],[3,10,6,1]],
  gauge:[[2,9,8,1],[2,7,1,2],[9,7,1,2],[3,5,2,1],[7,5,2,1],[5,4,2,1],[6,6,1,3]], meter:[[1,3,10,6],[2,4,2,4],[5,4,2,4],[8,4,1,4]]
};
function drawGlyph(P, rects, x, y, scale, pen){ (rects||[]).forEach(r=>P.rect(x+r[0]*scale, y+r[1]*scale, r[2]*scale, r[3]*scale, pen)); }
// 14 families: thresholds (COMMON/RARE/EPIC/LEGENDARY) + value fn over (totals, competition.me).
const TROPHY_FAMILIES=[
  {key:'titan',name:'TOKENS',glyph:'titan',fmt:'tokens',thr:[1e6,1e7,2.5e7,1e8],val:t=>(t.tokens_input||0)+(t.tokens_output||0)},
  {key:'prompter',name:'PROMPTS',glyph:'prompter',fmt:'int',thr:[100,1000,2500,10000],val:t=>t.user_prompts||0},
  {key:'novelist',name:'WORDS',glyph:'novelist',fmt:'compact',thr:[10000,50000,250000,500000],val:t=>t.user_words||0},
  {key:'chars',name:'CHARS',glyph:'chars',fmt:'compact',thr:[50000,250000,500000,2000000],val:t=>t.user_chars_typed||0},
  {key:'relentless',name:'STREAK',glyph:'flame',fmt:'day',thr:[3,14,30,60],val:t=>t.longest_streak||0},
  {key:'regular',name:'ACTIVE',glyph:'calendar',fmt:'day',thr:[7,30,120,270],val:t=>t.active_days||0},
  {key:'marathon',name:'MARATHON',glyph:'flag',fmt:'min',thr:[60,180,360,540],val:t=>t.longest_session_min||0},
  {key:'grinder',name:'GRIND',glyph:'gear',fmt:'min',thr:[480,4800,24000,48000],val:t=>t.total_active_min||0},
  {key:'owl',name:'NIGHTOWL',glyph:'moon',fmt:'min',thr:[300,1500,6000,15000],val:t=>t.nightowl_active_min||0},
  {key:'toolsmith',name:'TOOLS',glyph:'wrench',fmt:'compact',thr:[1000,10000,50000,100000],peerOk:false,val:t=>t.tool_uses||0},
  {key:'bigbang',name:'BIGBANG',glyph:'star',fmt:'tokens',thr:[100000,500000,1000000,2000000],val:(t,me)=>((me.metrics&&me.metrics.peak_day_io&&me.metrics.peak_day_io.tokens)||0)},
  {key:'bottleneck',name:'BOTTLE',glyph:'robot',fmt:'dur',thr:[900,3600,18000,54000],val:(t,me)=>((me.metrics&&me.metrics.bottleneck_sec_total)||0)},
  {key:'sesspush',name:'SESSION',glyph:'gauge',fmt:'int',thr:[1,6,30,60],val:(t,me)=>((me.limits&&me.limits.session_limit_hits)||0)},
  {key:'weekpush',name:'WEEKLY',glyph:'meter',fmt:'int',thr:[1,3,10,25],val:(t,me)=>((me.limits&&me.limits.weekly_limit_hits)||0)}
];
function trophyEval(t, me){ t=t||{}; me=me||{};
  return TROPHY_FAMILIES.map(f=>{ const v=f.val(t,me)||0; let tier=0;
    for(let i=0;i<f.thr.length;i++) if(v>=f.thr[i]) tier=i+1;
    return {name:f.name,glyph:f.glyph,fmt:f.fmt,tier:tier,value:v,next: tier<f.thr.length ? f.thr[tier] : null}; }); }
// peer competition payload → a totals-like object so trophyEval works on the rival too
function peerTotals(peer){ const m=(peer&&peer.metrics)||{}, w=(peer&&peer.windows&&peer.windows.all)||{};
  return { tokens_input:w.tokens_input||0, tokens_output:w.tokens_output||0, user_prompts:m.prompts_total||0,
    user_words:m.words_typed_total||0, user_chars_typed:m.user_chars_typed||0, longest_streak:m.longest_streak||0,
    active_days:m.active_days||0, total_active_min:m.total_active_min||0, nightowl_active_min:m.nightowl_active_min||0,
    longest_session_min:m.endurance_longest_session_min||0, tool_uses:m.tool_uses||0 }; }
const TIER_NAMES=['LOCKED','COMMON','RARE','EPIC','LEGENDARY'];
const tierCols=C=>[C.edge, C.a2d, C.a2, C.a1d, C.a1];   // LOCKED / COMMON / RARE / EPIC / LEGENDARY
function tfmt(k,v){ const M={tokens:fmtTokens,int:fmtInt,compact:fmtCompact,min:fmtMin,dur:fmtDur,
  pct:n=>Math.round(n)+'%',day:n=>(n||0)+'D',usd:fmtUSD}; return (M[k]||String)(v); }
function trophyCell(P, cx, cy, cw, x){
  const C=P.pal, col=tierCols(C)[x.tier], gs=2, gw=12*gs;
  drawGlyph(P, TROPHY_GLYPHS[x.glyph], cx+Math.round((cw-gw)/2), cy, gs, col);          // glyph (×2, tier-coloured)
  P.text(x.name, cx+Math.round(cw/2), cy+26, x.tier?C.cream:C.creamD, 'tag', {sp:0, align:'c'});
  const pw=4, pg=2, tw=4*pw+3*pg, px0=cx+Math.round((cw-tw)/2), py=cy+34;               // 4 tier pips
  for(let i=0;i<4;i++) P.rect(px0+i*(pw+pg), py, pw, 3, i<x.tier?col:C.edge);
}
function drawTrophies(P, d){
  const tr=trophyEval(d.totals||{}, (d.competition&&d.competition.me)||{});
  const level=tr.reduce((s,x)=>s+x.tier,0);
  chrome(P, 'TROPHIES', level+'/'+(tr.length*4));
  const cs=cols(6, 308, 5, 4), RY=36, PITCH=58;   // 5 trophies per row
  tr.forEach((x,i)=>trophyCell(P, cs[i%5].x, RY+Math.floor(i/5)*PITCH, cs[i%5].w, x));
}

/* ---------- VS AWARDS (VERSUS) — head-to-head trophy tiers (pips), me vs rival per family ---------- */
function drawVsAwards(P, d){
  const C=P.pal, cp=d.competition||{}, me=cp.me||{}, rv=(cp.peers&&cp.peers[0])||null, has=!!rv;
  const myEval=trophyEval(d.totals||{}, me), rvEval=has?trophyEval(peerTotals(rv), rv):null;
  chrome(P, 'VERSUS - TROPHIES', '');
  seclabel(P, 'TROPHY TIERS', SECLABEL_Y);
  const hy=44;
  P.text((me.alias||'YOU').toUpperCase(),                  CMP_ME_C, hy, C.a1, 'rowLabel', {align:'c'});
  P.text('VS',                                             CMP_DOT_X, hy, C.creamD, 'caption', {sp:1, align:'c'});
  P.text(has?(rv.alias||'RIVAL').toUpperCase():'NO RIVAL', CMP_RV_C, hy, C.a2, 'rowLabel', {align:'c'});
  const pips=(cx,y,tier)=>{ const col=tierCols(C)[tier], pw=4, pg=1, tw=4*pw+3*pg, x0=cx-Math.round(tw/2);
    for(let i=0;i<4;i++) P.rect(x0+i*(pw+pg), y, pw, 4, i<tier?col:C.edge); };
  // peer-eligible families only (TOOLS is peerOk:false): name + my pips · chevron · rival pips
  const ry=58, pitch=13; let r=0;
  TROPHY_FAMILIES.forEach((f,k)=>{ if(f.peerOk===false) return;
    const y=ry+r*pitch; r++;
    const at=myEval[k].tier, bt=has?rvEval[k].tier:0;
    P.text(f.name, 6, y, C.creamD, 'tag', {sp:0});
    pips(CMP_ME_C, y, at);
    P.text(!has?'·':at>bt?'>':at<bt?'<':'=', CMP_DOT_X, y, C.creamD, 'caption', {align:'c'});
    if(has) pips(CMP_RV_C, y, bt); else P.text('-', CMP_RV_C, y, C.creamD, 'caption', {align:'c'});
  });
}

/* ---------- NEXT UP (TROPHIES) — the 4 trophies closest to their next tier, with progress bars ---------- */
function drawNextUp(P, d){
  const C=P.pal, tr=trophyEval(d.totals||{}, (d.competition&&d.competition.me)||{});
  chrome(P, 'NEXT UP', 'TROPHIES');
  seclabel(P, 'CLOSEST TO NEXT TIER', SECLABEL_Y);
  const near=tr.filter(x=>x.next!=null).map(x=>{ x.prog=x.next?x.value/x.next:0; return x; })
    .sort((a,b)=>b.prog-a.prog).slice(0,4);
  const LIST_Y=50, PITCH=42;
  near.forEach((x,i)=>{ const y=LIST_Y+i*PITCH;
    P.text(x.name+' → '+TIER_NAMES[x.tier+1], 6, y, C.cream, 'rowLabel', {sp:1});
    P.text(tfmt(x.fmt,x.value)+' / '+tfmt(x.fmt,x.next), 314, y, C.creamD, 'caption', {sp:1, align:'r'});
    bar(P, 6, y+12, 308, 9, Math.max(0,Math.min(1,x.prog)), 1);
  });
}

/* ---------- AVATAR (LIVE) — the CLAUDE CODE mascot. Representative static (STANDBY) frame; the live
   status/word-ticker/animation is the firmware's job. Default GLOOM ghost sprite ported to canvas. ---------- */
const GHOST={
  fill:[[5,2,5,1],[4,3,7,1],[3,4,9,1],[2,5,11,1],[2,6,11,1],[2,7,11,1],[2,8,11,1],[2,9,11,1],[2,10,11,1],[2,11,11,1],[2,12,2,2],[5,12,2,2],[8,12,2,2],[11,12,2,2]],
  shade:[[12,5,1,7],[11,12,2,2]], hi:[[4,3,2,1],[3,4,1,2]],
  eyesW:[[4,5,2,3],[9,5,2,3]], eyesP:[[5,6,1,2],[9,6,1,2]] };
function drawSprite(P, x, y, scale){   // GLOOM ghost, idle frame (fill / shade / highlight / eyes)
  const C=P.pal;
  drawGlyph(P, GHOST.fill,  x, y, scale, C.avatar);  drawGlyph(P, GHOST.shade, x, y, scale, C.avatarD);
  drawGlyph(P, GHOST.hi,    x, y, scale, C.avatarL); drawGlyph(P, GHOST.eyesW, x, y, scale, C.eyeWhite);
  drawGlyph(P, GHOST.eyesP, x, y, scale, C.bg);
}
function drawAvatar(P, d){
  const C=P.pal, L=d.limits||{}, sess=L.session||{}, days=d.daily_activity||[];
  const today=days.length?days[days.length-1]:{tokens_io:0,prompts:0,words:0};
  chrome(P, 'CLAUDE CODE', 'STANDBY');
  // SESSION bar at the very top (utilization), then the today line below it
  if(_OPTS.avatarSessBar){ const sp=sess.utilization;
    P.text('SESSION', 6, 30, C.creamD, 'caption', {sp:1});
    bar(P, 52, 29, 230, 8, sp!=null?Math.max(0,Math.min(1,sp/100)):0, 1);
    P.text(sp!=null?Math.round(sp)+'%':'-', 314, 30, C.a1, 'caption', {align:'r'}); }
  if(_OPTS.avatarStats) P.text(fmtTokens(today[dayMetric()]||0)+' TOKENS • '+fmtInt(today.prompts||0)+' PROMPTS • '+fmtCompact(today.words||0)+' WORDS',
    160, 44, C.creamD, 'caption', {sp:1, align:'c'});
  // mascot — centred, sitting lower (below the info lines)
  const scale=7, sw=16*scale, gx=Math.round((320-sw)/2), gy=66;
  drawSprite(P, gx, gy, scale);
  P.text('STANDBY', 160, gy+sw+12, C.avatar, 'rowLabel', {sp:2, align:'c'});            // status word, under the mascot (avatar colour)
}

/* ---------- OPTIONS — device settings screens (visuals only; the B-edit state machine is a later phase) ---------- */
function optBox(P, y, h){ const C=P.pal; P.rect(4, y, 312, h, C.panel); P.border(4, y, 312, h, C.edge, 1); }   // bordered option box (shared by DISPLAY/SCREENS/PALETTES/WIFI)
function drawOptDisplay(P, d){
  const C=P.pal;
  chrome(P, 'DISPLAY', 'OPTIONS');
  seclabel(P, 'PREFERENCES', SECLABEL_Y);
  const rows=[['TOKENS DEFAULT','WITHOUT CACHE'],['BOOT SCREEN','AVATAR'],['ANIMATION SPEED','1.0X'],
    ['BRIGHTNESS','100%'],['AVATAR LINE 1','MY SESSION'],['AVATAR LINE 2','DAILY STATS'],['RESET DEFAULTS','>']];
  const LIST_Y=44, PITCH=23, BOXH=18;
  rows.forEach((r,i)=>{ const y=LIST_Y+i*PITCH; optBox(P, y, BOXH);
    P.text(r[0], 10, y+5, C.cream, 'rowLabel', {sp:1});                            // label (Aurora 24 @9)
    P.text(r[1], 308, y+5, C.a1, 'rowLabel', {align:'r'}); });                     // value (Aurora 24 @9)
}
function drawOptScreens(P, d){
  const C=P.pal;
  chrome(P, 'SCREENS', 'OPTIONS');
  seclabel(P, 'SHOW / HIDE SCREENS', SECLABEL_Y);
  // every device-hideable screen (DEV excluded) + its ON/OFF state. Static preview: all ON. Windowed since
  // viewscreens has ~25 screens; the device scrolls the full list.
  const slugs=Object.keys(SCREENS).filter(s=>SCREENS[s].cat!=='DEV');
  const LIST_Y=44, PITCH=21, BOXH=18, MAXROWS=8;
  slugs.slice(0,MAXROWS).forEach((s,i)=>{ const y=LIST_Y+i*PITCH; optBox(P, y, BOXH);
    P.text(SCREENS[s].title, 10, y+5, C.cream, 'rowLabel', {sp:1});
    P.text('ON', 308, y+5, C.green, 'rowLabel', {align:'r'}); });
}
// preset palettes (name + [bg, accent1, accent2, text, status, avatarColor]) — ported from /view's PALETTES
const PALETTES=[
  ['DEFAULT',['#292929','#ff6422','#2cdd17','#d3d3d3','#00ea06','#ff6422']], ['NEON',['#020c22','#b1ff14','#14d8ff','#d0ecf1','#c3f859','#b1ff14']],
  ['MONOCHROME',['#787878','#434343','#e0e0e0','#fafafa','#292929','#c6c6c6']], ['SPRING',['#9cf09c','#19db3b','#4a9eff','#f1a2eb','#434343','#f3e84c']],
  ['AUTUMN',['#f1dc9e','#7a5c00','#f78a4b','#f46a34','#434343','#f8d059']], ['BLOOD',['#2c0303','#a40000','#f85b00','#ff3c3c','#5e5e5e','#ec7e7e']],
  ['BLURANGE',['#191919','#ff640a','#14d8ff','#bababa','#14d8ff','#14d8ff']], ['ACIDIC WATERMELON',['#191028','#69eb00','#ff08eb','#97b8f1','#8aea00','#ff6422']],
  ['COMFY',['#1d1b1b','#ff3f0c','#fe8234','#ffb45f','#8aea00','#ff6422']], ['PURDEE',['#1d1b1b','#33a9ff','#b50cff','#4bc0ff','#ff2598','#e045a8']],
  ['MILLENIUM',['#1b1f22','#33a9ff','#ff620c','#4bc0ff','#91e900','#ff620c']], ['DJINKZED',['#192024','#ff33fd','#ff620c','#4cbffe','#91e900','#ff33fd']],
  ['BLUEFEELS',['#191c1f','#33a1ff','#0c42ff','#5fc1ff','#00eac1','#228aff']], ['SANDEE',['#2c2626','#ffb622','#de7216','#a3a3a3','#fe8847','#ff7822']],
  ['GRRLY',['#1d1b1b','#ea54ce','#f06b6b','#ff705f','#8aea00','#ff3692']], ['PASTELLICIOUS',['#171515','#63e955','#f26969','#ff705f','#8aea00','#77bbbe']],
  ['RETRO DULLNESS',['#a69e9e','#2629ff','#d01212','#000000','#19b30f','#004fa7']]
];
function drawOptPalettes(P, d){
  const C=P.pal;
  chrome(P, 'PALETTES', 'OPTIONS');
  seclabel(P, 'COLOR THEMES', SECLABEL_Y);
  const LIST_Y=44, PITCH=19, BOXH=16, MAXROWS=8;
  PALETTES.slice(0,MAXROWS).forEach((p,i)=>{ const y=LIST_Y+i*PITCH, active=i===0;   // DEFAULT = active
    optBox(P, y, BOXH);
    if(active) P.rect(7, y+3, 2, 10, C.a1);                                           // active marker (inside box)
    P.text(p[0], 13, y+4, active?C.cream:C.creamD, 'rowLabel', {sp:1});
    const sw=10, sg=1, cols5=p[1], x0=308-(cols5.length*(sw+sg)-sg);                  // swatch strip (10×10), right-aligned in box
    cols5.forEach((col,k)=>{ const sx=x0+k*(sw+sg); P.rect(sx, y+3, sw, 10, col); P.border(sx, y+3, sw, 10, C.edge, 1); });
  });
}
function drawOptAvatar(P, d){
  // Mirrors the firmware AVATAR screen (screens_options.draw_options_avatar): the
  // active pick centred over a static mascot, plus the two B-preview instruction
  // lines. The badge opens a live preview on B; /viewscreens is a static picture
  // of the cycle-OFF state (GLOOM active) and never simulates the press.
  const C=P.pal;
  chrome(P, 'AVATAR', 'OPTIONS');
  seclabel(P, 'AVATAR STYLE', SECLABEL_Y);
  P.text('GLOOM • ACTIVE', 160, 44, C.cream, 'caption', {sp:1, align:'c'});   // active sprite label
  // the mascot, centred on the firmware stage (SPRITE_X 104, SPRITE_Y 86, scale 7)
  const scale=7, gx=104, gy=86;
  // ground shadow (avShadow static frame: width 85, 12px inset, centred x160 y190)
  P.rect(130,190,61,1, C.edge); P.rect(118,191,85,3, C.edge); P.rect(130,194,61,1, C.edge);
  drawSprite(P, gx, gy, scale);
  // B-preview instruction lines (firmware B opens the live preview flow)
  P.text('PRESS B TO PREVIEW AVATARS', 160, 208, C.cream, 'caption', {sp:1, align:'c'});
  P.text('PRESS B AGAIN TO CONFIRM', 160, 217, C.creamD, 'caption', {sp:1, align:'c'});
}
function drawOptWifi(P, d){
  const C=P.pal;
  chrome(P, 'WIFI', 'DEVICE ONLY');
  seclabel(P, 'NETWORKS', SECLABEL_Y);
  const nets=[['CLAUDENET',4,1],['BADGE-5G',3,1],['WORKSHOP',2,1],['GUEST',1,0]];   // [ssid, signal 1-4, locked]
  const LIST_Y=46, PITCH=26, BOXH=20;
  nets.forEach((n,i)=>{ const y=LIST_Y+i*PITCH; optBox(P, y, BOXH);
    const nw=P.text(n[0], 10, y+6, C.cream, 'rowLabel', {sp:1});
    if(n[1] && n[2]) P.rect(10+nw+5, y+7, 4, 5, C.creamD);     // lock indicator (small padlock block) for secured nets
    const bw=3, bg=2, bx0=308-(4*bw+3*bg), baseY=y+15;         // 4 signal bars (rising height), right-aligned in box
    for(let b=0;b<4;b++){ const h=3+b*2; P.rect(bx0+b*(bw+bg), baseY-h, bw, h, b<n[1]?C.a2:C.edge); }
  });
  P.text('WIFI SETUP RUNS ON THE TUFTY — PREVIEW ONLY', 6, 198, C.creamD, 'caption', {sp:1});
}

const SCREENS = {
  avatar:{   title:'CLAUDE CODE',  cat:'LIVE',     draw:drawAvatar },
  usage:{    title:'USAGE LIMITS',  cat:'LIVE',     draw:drawUsage },
  // PROJECTS sits in LIVE (3rd, after USAGE LIMITS); TODAY moved to BREAKDOWN
  // (between WORDS and TOOLS). Draw fns keep their original definitions/order.
  projects:{ title:'PROJECTS',     cat:'LIVE',     draw:drawProjects },
  tokens:{   title:'TOKEN USAGE',  cat:'TOKENS',   draw:drawTokens },
  prompts:{  title:'PROMPTS',      cat:'TOKENS',   draw:drawPrompts },
  activity:{ title:'ACTIVITY',     cat:'ACTIVITY', draw:drawActivity },
  calendar:{ title:'CALENDAR',     cat:'ACTIVITY', draw:drawCalendar },
  rhythm:{   title:'RHYTHM',       cat:'ACTIVITY', draw:drawRhythm },
  rhythmmatrix:{ title:'RHYTHM MATRIX', cat:'ACTIVITY', draw:drawRhythmMatrix },
  words:{    title:'WORDS',        cat:'BREAKDOWN', draw:drawWords },
  today:{    title:'TODAY',         cat:'BREAKDOWN', draw:drawToday },
  tools:{    title:'TOOLS',        cat:'BREAKDOWN', draw:drawTools },
  models:{   title:'MODELS',       cat:'BREAKDOWN', draw:drawModels },
  versus:{   title:'VERSUS',       cat:'VERSUS',   draw:drawVersus },
  vshuman:{  title:'VERSUS - HUMAN', cat:'VERSUS',   draw:drawVsHuman },
  vshumanbest:{title:'VERSUS - BEST DAY', cat:'VERSUS',  draw:drawVsHumanBest },
  vsrecords:{title:'VERSUS - RECORDS',cat:'VERSUS',  draw:drawVsRecords },
  vsawards:{ title:'VERSUS - TROPHIES', cat:'VERSUS',  draw:drawVsAwards },
  vsprojects:{title:'VERSUS - PROJECTS',  cat:'VERSUS',  draw:drawVsProjects },
  trophies:{ title:'TROPHIES',     cat:'TROPHIES', draw:drawTrophies },
  nextup:{   title:'NEXT UP',      cat:'TROPHIES', draw:drawNextUp },
  optdisplay:{ title:'DISPLAY',    cat:'OPTIONS',  draw:drawOptDisplay },
  optscreens:{ title:'SCREENS',    cat:'OPTIONS',  draw:drawOptScreens },
  optpalettes:{title:'PALETTES',   cat:'OPTIONS',  draw:drawOptPalettes },
  optavatar:{  title:'AVATAR',     cat:'OPTIONS',  draw:drawOptAvatar },
  optwifi:{    title:'WIFI',       cat:'OPTIONS',  draw:drawOptWifi },
  fonttest:{ title:'FONT TEST',    cat:'DEV',      draw:drawFontTest, w:FONTTEST_W, h:FONTTEST_H }
};

/* ---------- boot (shared by index) ---------- */
function paint2(canvas, slug, data){ const P=new Pico(canvas); P.pal=buildPalette(getTheme()); P.scale=getScale(); _OPTS=getOpts();
  P.clock=((data&&data.meta&&data.meta.generated_at)||'').slice(11,16);   // HH:MM from the feed's generated_at (server-local tz)
  _footerB=footerBLabel(slug, data);   // the badge's contextual-B hint for this screen (static)
  const s=SCREENS[slug]; if(s) s.draw(P, data); }
function tokenFromUrl(){ return new URLSearchParams(location.search).get('token')||''; }
async function fetchData(){
  const tok=tokenFromUrl(); if(!tok) return SAMPLE;
  try{ const r=await fetch('/claude-stats.json?token='+encodeURIComponent(tok), {cache:'no-store'});
    if(!r.ok) throw 0; const d=await r.json();
    // head-to-head data is a SEPARATE feed — fetch it for the VERSUS screens (best-effort)
    try{ const rc=await fetch('/competition.json?token='+encodeURIComponent(tok), {cache:'no-store'});
      if(rc.ok) d.competition=await rc.json(); }catch(e){}
    // session/weekly limits are their own fast feed — fetch for the USAGE LIMITS screen (best-effort)
    try{ const rl=await fetch('/claude-limits.json?token='+encodeURIComponent(tok), {cache:'no-store'});
      if(rl.ok) d.limits=await rl.json(); }catch(e){}
    return d;
  }catch(e){ return SAMPLE; }
}
let _targets=[], _lastData=null;
async function boot(targets){   // targets: [{canvas, slug}]
  _targets=targets;
  async function tick(){ const data=await fetchData(); _lastData=data; targets.forEach(t=>paint2(t.canvas, t.slug, data)); }
  await tick(); setInterval(tick, 60000);
  setInterval(cycleBook, 10000);   // rotate the WORDS book line to a fresh title every 10 s (like /view)
}
// repaint every target with the last-fetched data — used by the Tweaks panel for live font/size preview
function viewscreensRerender(){ if(_lastData) _targets.forEach(t=>paint2(t.canvas, t.slug, _lastData)); }
window.SCREENS=SCREENS; window.CATEGORY_ORDER=CATEGORY_ORDER; window.boot=boot; window.paint2=paint2;
window.SCALE_SIZES=SCALE_SIZES; window.DEFAULT_SCALE=DEFAULT_SCALE; window.getScale=getScale;
window.setScaleSize=setScaleSize; window.resetScale=resetScale; window.viewscreensRerender=viewscreensRerender;
window.getOpts=getOpts; window.setOpt=setOpt; window.resetOpts=resetOpts;
window.PALETTES=PALETTES; window.THEME_KEYS=['bg','accent1','accent2','text','status','avatarColor'];
window.getTheme=getTheme; window.setThemeColors=setThemeColors; window.resetTheme=resetTheme;
// click hit-test for the FONT TEST screen's TOGGLE GRID control; returns true if it consumed the click
window.fonttestHit=(x,y)=>{ const h=_ftGridHit; if(h && x>=h.x && x<=h.x+h.w && y>=h.y && y<=h.y+h.h){ FONTTEST_GRID=!FONTTEST_GRID; return true; } return false; };
