// ccstats — self-hosted Claude Code usage stats (badge firmware + server)
// Copyright (C) 2026 Zapador <zapador@zapador.net>
//
// This program is free software; you can redistribute it and/or modify it under
// the terms of version 2 of the GNU General Public License as published by the
// Free Software Foundation. See the LICENSE file for the full text.
//
// This program is distributed WITHOUT ANY WARRANTY; without even the implied
// warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

/* === pico.js — PicoGraphics-shaped canvas drawing shim for /viewscreens ===
   The Tufty firmware reimplements these ~10 primitives in MicroPython against PicoGraphics; screen draw
   code (screens.js) calls ONLY these, so it ports ~1:1. The browser backend is a 320×240 <canvas>.
   No CSS layout, no flex, no zoom — every element is placed at explicit integer pixel coordinates with
   (0,0) at the top-left, exactly like the device. Monospace fonts ⇒ text width is pure arithmetic. */

/* ---------- colour maths (ported verbatim from screens.js applyTheme) ---------- */
const clamp8 = n => Math.max(0, Math.min(255, Math.round(n)));
const parseHex = h => { h = String(h).replace('#',''); if (h.length===3) h=h.replace(/./g,c=>c+c);
  const n=parseInt(h,16); return [(n>>16)&255,(n>>8)&255,n&255]; };
const toHex = rgb => '#'+rgb.map(v=>clamp8(v).toString(16).padStart(2,'0')).join('');
const scale = (h,f) => { const [r,g,b]=parseHex(h); return toHex([r*f,g*f,b*f]); };
const tint  = (h,f) => { const [r,g,b]=parseHex(h); return toHex([r+(255-r)*f,g+(255-g)*f,b+(255-b)*f]); };
const rgbToHsv = (r,g,b) => { r/=255;g/=255;b/=255; const mx=Math.max(r,g,b),mn=Math.min(r,g,b),d=mx-mn;
  let h=0; if(d){ if(mx===r)h=((g-b)/d)%6; else if(mx===g)h=(b-r)/d+2; else h=(r-g)/d+4; h*=60; if(h<0)h+=360; }
  return [h, mx===0?0:d/mx, mx]; };
const hsvToHex = (h,s,v) => { s=Math.max(0,Math.min(1,s)); v=Math.max(0,Math.min(1,v));
  const c=v*s, x=c*(1-Math.abs((h/60)%2-1)), m=v-c; let r,g,b;
  if(h<60){r=c;g=x;b=0;}else if(h<120){r=x;g=c;b=0;}else if(h<180){r=0;g=c;b=x;}
  else if(h<240){r=0;g=x;b=c;}else if(h<300){r=x;g=0;b=c;}else{r=c;g=0;b=x;}
  return toHex([(r+m)*255,(g+m)*255,(b+m)*255]); };

/* Derive the full pen palette from the theme base colours — same shades the CSS produces.
   a1 = Accent 1, a2 = Accent 2 (colour-neutral names; the actual hue is whatever the palette sets). */
function buildPalette(t){
  const M=t.bg, A1=t.accent1, A2=t.accent2, C=t.text, S=t.status, AV=t.avatarColor||A1;
  const P = {
    bg:M, a1:A1, a2:A2, cream:C, green:S, avatar:AV,
    eyeWhite:'#d3d3d3',   // FIXED cream, palette-independent (matches firmware Theme.eye_white) — avatar eyes/blink slits/ghost/BLIP happy; immune to dark-text palettes (e.g. RETRO DULLNESS)
    titlebar:scale(M,1.35), rim:scale(M,1.85), line:scale(M,1.72), screenborder:scale(M,1.27),
    panel:scale(M,0.74), track:scale(M,0.58), edge:scale(M,0.36),
    a1d:scale(A1,0.76), a1l:tint(A1,0.30), a1sh:scale(A1,0.43),
    a2d:scale(A2,0.64), a2l:tint(A2,0.34), a2sh:scale(A2,0.37), a2zero:scale(A2,0.575),
    avatarD:scale(AV,0.76), avatarL:tint(AV,0.30), avatarSh:scale(AV,0.43),
    creamD:scale(C,0.74), greenD:scale(S,0.34), heatZero:scale(M,0.5)
  };
  const [gh,gs,gv]=rgbToHsv.apply(null,parseHex(A1)); const step=k=>hsvToHex(gh, gs-0.15*k, gv-0.15*k);
  P.heat = [P.heatZero, step(4), step(3), step(2), step(1), A1];  // heatmap ramp derived from Accent 1
  return P;
}
// accent N (1 or 2) → its colour set {c, d(ark), l(ight), sh(adow)}. Used by every accent-coloured element.
const accentPen = (C,n) => n===2 ? {c:C.a2,d:C.a2d,l:C.a2l,sh:C.a2sh} : {c:C.a1,d:C.a1d,l:C.a1l,sh:C.a1sh};
const THEME_DEFAULTS = { bg:'#292929', accent1:'#ff6422', accent2:'#2cdd17', text:'#d3d3d3', status:'#00ea06', avatarColor:'#ff6422' };

/* ---------- the drawing surface ---------- */
// Fonts: monospace pixel fonts, 0.6em advance per char (measured). FONTS maps a logical name to the
// CSS font shorthand pieces; advance() returns the integer pixel width of n chars at a given size.
// Font registry — keyed font families. Screens never name a font directly; they use an ELEMENT-TYPE ROLE
// (rowLabel, heroValue, axisTick…), and P.scale maps that role → {font:key, px}. Library fonts get registered here at boot.
let FONTS = {
  pico:  { family:"'Press Start 2P'", weight:'400' },   // chunky title/number font (Press Start 2P)
  silk:  { family:"'Silkscreen'",     weight:'400' }    // small label font, regular
};
function registerFont(key, family, weight){ FONTS[key]={ family:"'"+String(family).replace(/'/g,"\\'")+"'", weight:weight||'400' }; }
class Pico {
  // W/H come from the canvas itself (most screens are 320×240; the DEV font-test screen is larger).
  constructor(canvas){ this.W=canvas.width||320; this.H=canvas.height||240; this.c=canvas; this.x=canvas.getContext('2d');
    this.x.imageSmoothingEnabled=false;
    // offscreen text buffer: we render each string here, BINARIZE its alpha (kill anti-aliasing), then
    // blit it — canvas fillText is always smoothed, so this is how we get crisp pixel-font edges that
    // match the device's bitmap fonts. threshold tunes apparent weight (coverage ≥ T% ⇒ solid pixel).
    // wide enough for a long sample string at 2× (the font-test screen, up to 32px) — clamped per-draw, so no cost.
    this._tc=document.createElement('canvas'); this._tc.width=1400; this._tc.height=80;
    this._tx=this._tc.getContext('2d'); this._tx.imageSmoothingEnabled=false;
    this.textThreshold=140; this.scale=null; this._capCache={}; }   // scale = type-scale; _capCache = per font@px cap-top gap
  clear(pen){ this.x.fillStyle=pen; this.x.fillRect(0,0,this.W,this.H); }
  rect(x,y,w,h,pen){ this.x.fillStyle=pen; this.x.fillRect(x|0,y|0,w|0,h|0); }
  // 1..t-px outline rectangle (a "border" — like PicoGraphics drawing 4 thin rects)
  border(x,y,w,h,pen,t){ t=t||1; this.rect(x,y,w,t,pen); this.rect(x,y+h-t,w,t,pen);
    this.rect(x,y,t,h,pen); this.rect(x+w-t,y,t,h,pen); }
  hline(x,y,w,pen){ this.rect(x,y,w,1,pen); }
  pixel(x,y,pen){ this.rect(x,y,1,1,pen); }
  // dashed horizontal rule: `on`px drawn, `off`px gap
  dash(x,y,w,pen,on,off){ on=on||4; off=off==null?4:off; for(let i=0;i<w;i+=on+off) this.rect(x+i,y,Math.min(on,w-i),1,pen); }
  charW(size){ return Math.round(size*0.6); }        // monospace advance (px) per char at `size`
  textW(str,size,sp){ sp=sp||0; return str.length*this.charW(size) + (str.length>0?(str.length-1)*sp:0); }
  // text() — pen colour, top-left at (x,y). font='pico'|'silk'. sp=extra letter-spacing px. shadow=[dx,dy,pen].
  // align: 'l'(default)|'r'|'c' — horizontal anchor of (x); for 'r', x is the RIGHT edge.
  // size is either a TYPE-SCALE name ('xsmall'…'huge') resolved via this.scale → {font,px}, or a raw px number.
  text(str,x,y,pen,size,opts){ opts=opts||{}; let key, px;
    if(typeof size==='string'){ const e=(this.scale&&this.scale[size])||{}; key=e.font||'silk'; px=e.px||8; }
    else { px=size; key=opts.font||'silk'; }
    const f=FONTS[key]||FONTS.silk, sp=opts.sp||0, sh=opts.shadow;
    const cap=this._capTop(key, px);   // per-font cap-top gap ⇒ seat every font's cap-top at the draw-y (alignment)
    str=String(str);
    const T=this._tx, TW=this._tc.width, TH=this._tc.height;
    T.textBaseline='top'; T.textAlign='left'; T.font=f.weight+' '+px+'px '+f.family+',monospace';
    if('letterSpacing' in T) T.letterSpacing=sp+'px';
    const w=Math.ceil(T.measureText(str).width);   // REAL rendered width (not an estimate ⇒ no clipping)
    const alignR=opts.align==='r', alignC=opts.align==='c';
    if(alignR) x=x-w; else if(alignC) x=Math.round(x-w/2);
    x=Math.round(x); y=Math.round(y);
    T.clearRect(0,0,TW,TH);
    if(sh){ T.fillStyle=sh[2]; T.fillText(str, sh[0], sh[1]); }   // shadow first (offsets are small +ve)
    T.fillStyle=pen; T.fillText(str, 0, 0);
    if('letterSpacing' in T) T.letterSpacing='0px';
    // binarize alpha so glyph edges are hard pixels (no grey anti-alias fringe).
    // ih headroom is generous (px×1.5): some pixel fonts seat their glyphs LOW in the em box, so a tight
    // px+4 clamp would clip them (Dogica vanished entirely). The extra rows are transparent ⇒ no cost/overlap.
    const iw=Math.min(TW, w+(sh?sh[0]:0)+3), ih=Math.min(TH, Math.ceil(px*1.5)+(sh?sh[1]:0)+4);
    const img=T.getImageData(0,0,iw,ih), d=img.data, th=this.textThreshold;
    for(let i=3;i<d.length;i+=4) d[i] = d[i]>=th ? 255 : 0;
    T.putImageData(img,0,0);
    // horizontal: for left-anchored text, trim the first glyph's left bearing so left edges align across fonts
    let lc=0;
    if(!alignR && !alignC){ for(let col=0; col<iw; col++){ let hit=false;
      for(let r=0;r<ih;r++){ if(d[(r*iw+col)*4+3]){ hit=true; break; } } if(hit){ lc=col; break; } } }
    this.x.drawImage(this._tc, 0,0, iw,ih, x-lc, y-cap, iw,ih);   // shift left by bearing, up by cap-top gap
    return w;
  }
  // cap-top gap (px) of a font at a size: rows between the em-top (textBaseline 'top') and where capital 'W'
  // starts. Cached per font@px. Seating this at the draw-y makes fonts swappable without vertical drift; it's
  // measured at the EXACT px (not a scaled fraction) so it's pixel-exact even where the gap isn't linear.
  _capTop(key, px){
    const ck=key+'@'+px, c=this._capCache; if(ck in c) return c[ck];
    const f=FONTS[key]||FONTS.silk, T=this._tx, TH=this._tc.height;
    const ih=Math.min(TH, Math.ceil(px*1.5)+4), iw=Math.min(this._tc.width, px*2+4);
    T.clearRect(0,0,this._tc.width,TH);
    T.textBaseline='top'; T.textAlign='left'; if('letterSpacing' in T) T.letterSpacing='0px';
    T.font=f.weight+' '+px+'px '+f.family+',monospace'; T.fillStyle='#fff'; T.fillText('W',0,0);
    const d=T.getImageData(0,0,iw,ih).data, th=this.textThreshold; let off=0;
    for(let r=0;r<ih;r++){ for(let col=0;col<iw;col++){ if(d[(r*iw+col)*4+3]>=th){ off=r; c[ck]=off; return off; } } }
    c[ck]=off; return off;
  }
  // pixel-staircase triangle, 4×7, pointing 'l' or 'r'; (x,y)=top-left box. Mirrors the SVG .tri in /view.
  tri(x,y,dir,pen){ const cols=[7,5,3,1];           // heights of the 4 columns (base→point)
    for(let i=0;i<4;i++){ const h=cols[i], cy=y+((7-h)>>1);
      const cx = dir==='r' ? x+i : x+(3-i); this.rect(cx,cy,1,h,pen); } }
}
