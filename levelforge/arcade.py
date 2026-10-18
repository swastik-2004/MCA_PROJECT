"""
LevelForge Arcade: a pixel-art, playable "mission control" view of a run.

    python play.py              # opens the arcade for the latest run
    python play.py outputs_llm  # or for a specific outputs folder

Everything shown comes from the real run data embedded in the page (levels, bot
traces, agent log, scores, throughput). The game uses the same rules as the
Python simulator. All sprites are original 8x8 pixel art drawn in code.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def build_arcade(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


def data_from_report(report_html: str | Path) -> dict:
    """Recover the run data embedded in an existing report.html."""
    text = Path(report_html).read_text(encoding="utf-8")
    m = re.search(r'<script id="data" type="application/json">(.*?)</script>', text, re.S)
    if not m:
        raise ValueError(f"no run data found in {report_html}")
    return json.loads(m.group(1).replace("<\\/", "</"))


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LevelForge Arcade</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=VT323&display=swap" rel="stylesheet">
<style>
:root{--bg:#07070d;--panel:#0e0f1a;--line:#262840;--ink:#e8e6f0;--muted:#8b8aa8;--g:#00e436;--b:#29adff;--y:#ffec27;--r:#ff004d;--o:#ffa300;--p:#ff77a8;--l:#83769c}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);overflow:hidden}
body{font:20px/1.15 'VT323',ui-monospace,Consolas,monospace}
.px{font-family:'Press Start 2P',ui-monospace,monospace}
#app{display:grid;grid-template-rows:auto 1fr auto;height:100vh;gap:8px;padding:8px}
header{display:flex;align-items:center;gap:14px;flex-wrap:wrap;border:2px solid var(--line);background:var(--panel);padding:8px 12px}
header h1{font-size:18px;margin:0;color:var(--y);text-shadow:3px 3px 0 #7e2553;letter-spacing:2px}
header .sub{color:var(--muted);font-size:18px}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
.chip{border:2px solid var(--line);padding:2px 8px;font-size:18px;background:#0a0b14}
.chip b{color:var(--g);font-weight:normal}
main{display:grid;grid-template-columns:300px 1fr 320px;gap:8px;min-height:0}
.panel{border:2px solid var(--line);background:var(--panel);padding:10px;min-height:0;display:flex;flex-direction:column;gap:8px;overflow:hidden}
.panel h2{font-size:10px;margin:0;color:var(--b);letter-spacing:1px}
.panel h2::before{content:"\25A0 ";color:var(--g)}
#feed{flex:1;overflow:hidden;font-size:18px;display:flex;flex-direction:column;justify-content:flex-end}
#feed div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.92}
.t-Generator{color:#c58bff}.t-Simulate{color:var(--g)}.t-Critic{color:var(--o)}.t-Optimizer{color:var(--b)}.t-Finalize{color:var(--y)}.t-Router{color:var(--p)}.t-other{color:var(--muted)}
.bar{display:flex;align-items:center;gap:6px;font-size:17px}.bar .lab{width:88px;color:var(--muted);overflow:hidden;white-space:nowrap;text-overflow:clip}
.bar .trk{flex:1;height:10px;background:#1a1b2b;position:relative}.bar .fil{position:absolute;inset:0 auto 0 0;background:var(--b)}
.bar .fil.a{background:#4a4866}.bar .val{width:84px;text-align:right;white-space:nowrap;font-size:16px}
#stage{position:relative;border:2px solid var(--line);background:#05050a;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:0;overflow:hidden}
#gamewrap{position:relative;line-height:0}
#game{image-rendering:pixelated;image-rendering:crisp-edges;display:block}
#fx{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.float{position:absolute;font-family:'Press Start 2P',monospace;font-size:12px;line-height:1;text-shadow:2px 2px 0 #000;animation:up .9s ease-out forwards;white-space:nowrap}
@keyframes up{from{transform:translate(-50%,0);opacity:1}to{transform:translate(-50%,-36px);opacity:0}}
#hud{width:100%;display:flex;justify-content:space-between;gap:10px;padding:6px 10px;font-size:20px;flex-wrap:wrap}
#hud .hp{display:flex;gap:2px;align-items:center}
#hud .heart{width:12px;height:12px;background:var(--r);clip-path:polygon(50% 100%,0 40%,0 15%,25% 0,50% 18%,75% 0,100% 15%,100% 40%)}
#hud .heart.off{background:#2a2234}
#msg{color:var(--y);min-height:22px;text-align:center;width:100%;font-size:20px}
#modebar{display:flex;gap:6px;padding:6px;flex-wrap:wrap;justify-content:center}
button{font-family:'Press Start 2P',monospace;font-size:10px;background:#141526;color:var(--ink);border:2px solid var(--line);padding:8px 10px;cursor:pointer}
button.on{border-color:var(--y);color:var(--y)}button:hover{border-color:var(--b)}
#banner{position:absolute;inset:0;display:none;align-items:center;justify-content:center;flex-direction:column;gap:14px;background:rgba(5,5,10,.78);text-align:center;z-index:5;line-height:1.35;padding:16px}
#banner .big{font-size:22px;color:var(--y);text-shadow:3px 3px 0 #7e2553}
#banner .small{font-size:22px;color:var(--ink);max-width:92%}
footer{border:2px solid var(--line);background:var(--panel);padding:6px 12px;display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:18px}
footer kbd{color:var(--y);font-family:inherit}
#cores{display:grid;grid-template-columns:repeat(auto-fill,minmax(52px,1fr));gap:6px}
.core{border:2px solid var(--line);padding:3px;font-size:15px;text-align:center}
.core .ld{height:8px;background:#1a1b2b;margin-top:3px;position:relative}.core .ld i{position:absolute;inset:0 auto 0 0;background:var(--g)}
#chart{width:100%;image-rendering:pixelated;background:#0a0b14;border:2px solid var(--line)}
#replaylab{font-size:17px;color:var(--muted);min-height:20px}
#race{display:none;width:100%;padding:0 10px 6px;font-size:19px}
#race .row{display:grid;grid-template-columns:100px 1fr 90px 190px;gap:10px;align-items:center;white-space:nowrap}
#race .hpb{height:8px;background:#1a1b2b;position:relative}#race .hpb i{position:absolute;inset:0 auto 0 0}
#boot{position:fixed;inset:0;background:#000;z-index:50;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:22px;cursor:pointer}
#bootlog{font-size:22px;color:var(--g);min-height:190px;width:min(760px,92vw);white-space:pre}
#title{font-size:clamp(28px,6vw,64px);color:var(--y);text-shadow:5px 5px 0 #7e2553,10px 10px 0 #1d2b53;opacity:0;transition:opacity .6s;text-align:center}
#press{font-size:14px;color:var(--ink);opacity:0;animation:blink 1s steps(2) infinite}
@keyframes blink{50%{visibility:hidden}}
#crt{position:fixed;inset:0;pointer-events:none;z-index:40;background:repeating-linear-gradient(to bottom,rgba(0,0,0,.18) 0 1px,transparent 1px 3px);box-shadow:inset 0 0 140px rgba(0,0,0,.75);animation:flick 4s infinite}
@keyframes flick{0%,100%{opacity:.9}50%{opacity:1}}
.shake{animation:shk .22s linear}
@keyframes shk{20%{transform:translate(3px,-2px)}40%{transform:translate(-3px,2px)}60%{transform:translate(2px,2px)}80%{transform:translate(-2px,-1px)}}
@media (max-width:1100px){main{grid-template-columns:1fr}.panel{max-height:260px}body{overflow:auto}html,body{overflow:auto}#app{height:auto}}
</style></head><body>
<div id="boot"><div id="bootlog"></div><div id="title" class="px">LEVELFORGE</div><div id="press" class="px">PRESS ENTER</div></div>
<div id="crt"></div>
<div id="app">
 <header><h1 class="px">LEVELFORGE</h1><span class="sub">AGENTIC DIGITAL TWIN // GAME-LEVEL OPTIMISATION</span><div class="chips" id="chips"></div></header>
 <main>
  <section class="panel"><h2 class="px">AGENT FEED</h2><div id="feed"></div>
   <h2 class="px">DESIGN BRIEF (FROM REVIEWS)</h2><div id="brief"></div></section>
  <section id="stage">
   <div id="msg"></div>
   <div id="gamewrap"><canvas id="game"></canvas><div id="fx"></div>
    <div id="banner"><div class="big px" id="bbig"></div><div class="small" id="bsmall"></div></div></div>
   <div id="hud"></div><div id="race"></div>
   <div id="modebar"><button data-m="final" class="on">1 PLAY OPTIMISED</button><button data-m="initial">2 PLAY ORIGINAL</button><button data-m="race">3 AI RACE</button><button data-m="raceinit">4 AI RACE (ORIGINAL)</button></div>
  </section>
  <section class="panel"><h2 class="px">RUN REPLAY</h2><canvas id="chart" width="150" height="70"></canvas><div id="replaylab"></div>
   <h2 class="px">PARALLEL CORE ARRAY</h2><div id="cores"></div>
   <h2 class="px">QUALITY: BEFORE / AFTER</h2><div id="comps"></div>
   <h2 class="px">BOT COMPLETION</h2><div id="pers"></div></section>
 </main>
 <footer><span><kbd>ARROWS/WASD</kbd> move</span><span><kbd>1-4</kbd> modes</span><span><kbd>R</kbd> restart</span><span><kbd>C</kbd> CRT</span><span><kbd>M</kbd> sound</span><span>All data replayed from the recorded run. Game rules = simulator rules.</span></footer>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const R = D.rules, H = D.history, FIRST = H[0], LAST = H[H.length - 1];
const PAL = {k:'#000000',n:'#1d2b53',p:'#7e2553',g:'#008751',b:'#ab5236',d:'#5f574f',l:'#c2c3c7',w:'#fff1e8',
  r:'#ff004d',o:'#ffa300',y:'#ffec27',G:'#00e436',B:'#29adff',L:'#83769c',P:'#ff77a8',f:'#ffccaa'};
const SPR = {
  knight: [["..lll...", ".lwwwl.w", ".lfkfl.w", "..fff..w", ".BBBBBBo", "fBByBB..", ".BBBBB..", ".n...n.."],
           ["..lll...", ".lwwwl.w", ".lfkfl.w", "..fff..w", ".BBBBBBo", "fBByBB..", ".BBBBB..", "..n.n..."]],
  slime: [["........", "...GG...", "..GGGG..", ".GwkGwk.", ".GGGGGG.", "GGgGGgGG", "gggggggg", "........"],
          ["........", "........", "..GGGG..", ".GGGGGG.", "GwkGGwkG", "GGGGGGGG", "gggggggg", "........"]],
  potion: [["...bb...", "...ll...", "..l..l..", ".lrrrrl.", ".lrwrrl.", ".lrrrrl.", "..llll..", "........"]],
  coin: [["........", "..yyyy..", ".yyoyyy.", ".yoyyyy.", ".yoyyyy.", ".yyyyoy.", "..yyyy..", "........"],
         ["........", "...yy...", "..yoyy..", "..yoyy..", "..yoyy..", "..yyyy..", "...yy...", "........"],
         ["........", "...y....", "...o....", "...y....", "...o....", "...y....", "...y....", "........"],
         ["........", "...yy...", "..yoyy..", "..yoyy..", "..yoyy..", "..yyyy..", "...yy...", "........"]],
  key: [["........", "........", ".yyy....", "y...y...", "y...yyyy", ".yyy..y.", "......yy", "........"]],
  door: [[".bbbbbb.", "bbobbobb", "bbobbobb", "dddddddd", "bbobkobb", "bbobbobb", "bbobbobb", "bbobbobb"]],
  stairs: [["llllllll", "dddddddd", "kkllllll", "kkdddddd", "kkkkllll", "kkkkdddd", "kkkkkkll", "kkkkkkdd"]],
  spikes: [["........", "..w...w.", ".lwl.lwl", ".lwl.lwl", "dddddddd", "d.d.d.d.", "........", "........"],
           ["........", "........", "........", "..l...l.", "dddddddd", "d.d.d.d.", "........", "........"]],
};
const BOTCOL = {rusher:'#ff004d', cautious:'#29adff', explorer:'#ffec27'};
const cache = {};
function spr(name, frame = 0, swap = null) {
  const set = SPR[name], rows = set[((frame % set.length) + set.length) % set.length];
  const key = name + '|' + frame % set.length + '|' + (swap ? JSON.stringify(swap) : '');
  if (cache[key]) return cache[key];
  const c = document.createElement('canvas'); c.width = 8; c.height = 8;
  const x = c.getContext('2d');
  rows.forEach((row, yy) => [...row].forEach((ch, xx) => {
    if (ch === '.') return;
    x.fillStyle = swap ? (swap['*'] || swap[ch] || PAL[ch]) : PAL[ch];
    x.fillRect(xx, yy, 1, 1);
  }));
  return (cache[key] = c);
}
function hash(r, c) { let n = (r * 374761393 + c * 668265263) | 0; n = (n ^ (n >>> 13)) * 1274126177 | 0; return ((n ^ (n >>> 16)) >>> 0) / 4294967295; }

// ---------------------------------------------------------------- sound
let audio = null, soundOn = true;
function beep(freq, dur = .08, type = 'square', vol = .05, slide = 0) {
  if (!soundOn) return;
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const o = audio.createOscillator(), g = audio.createGain(), t = audio.currentTime;
    o.type = type; o.frequency.setValueAtTime(freq, t);
    if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(30, freq + slide), t + dur);
    g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(.0001, t + dur);
    o.connect(g).connect(audio.destination); o.start(t); o.stop(t + dur + .02);
  } catch (e) { /* audio unavailable */ }
}
const SFX = {
  coin: () => { beep(988, .06); setTimeout(() => beep(1319, .1), 60); },
  hit: () => beep(140, .15, 'sawtooth', .06, -80),
  potion: () => [523, 659, 784].forEach((f, i) => setTimeout(() => beep(f, .08, 'triangle'), i * 60)),
  key: () => [784, 1047].forEach((f, i) => setTimeout(() => beep(f, .1, 'triangle'), i * 80)),
  door: () => beep(220, .18, 'square', .05, -100),
  kill: () => beep(600, .12, 'square', .05, -500),
  step: () => beep(90, .03, 'triangle', .02),
  win: () => [523, 659, 784, 1047, 1319].forEach((f, i) => setTimeout(() => beep(f, .14, 'square'), i * 110)),
  die: () => [400, 300, 200, 120].forEach((f, i) => setTimeout(() => beep(f, .18, 'sawtooth', .05), i * 140)),
};

// ---------------------------------------------------------------- canvas + effects
const cv = $('game'), ctx = cv.getContext('2d');
let SCALE = 4, particles = [];
function fitCanvas(grid) {
  cv.width = grid[0].length * 8; cv.height = grid.length * 8;
  const st = $('stage');
  const availW = st.clientWidth - 24, availH = st.clientHeight - 170;
  SCALE = Math.max(2, Math.floor(Math.min(availW / cv.width, availH / cv.height)));
  cv.style.width = cv.width * SCALE + 'px'; cv.style.height = cv.height * SCALE + 'px';
}
function floatText(r, c, text, color) {
  const s = document.createElement('div');
  s.className = 'float'; s.textContent = text; s.style.color = color;
  s.style.left = ((c * 8 + 4) * SCALE) + 'px'; s.style.top = ((r * 8 - 2) * SCALE) + 'px';
  $('fx').appendChild(s); setTimeout(() => s.remove(), 950);
}
function burst(r, c, color, n = 12) {
  for (let i = 0; i < n; i++) particles.push({x: c * 8 + 4, y: r * 8 + 4, vx: (Math.random() - .5) * 1.6,
    vy: (Math.random() - .8) * 1.6, life: 30 + Math.random() * 20, col: color});
}
function shake() { const w = $('gamewrap'); w.classList.remove('shake'); void w.offsetWidth; w.classList.add('shake'); }

function drawFloor(grid, r, c) {
  const h = hash(r, c);
  ctx.fillStyle = '#29273f'; ctx.fillRect(c * 8, r * 8, 8, 8);
  ctx.fillStyle = '#332f4c';
  if (h > .55) ctx.fillRect(c * 8 + Math.floor(h * 6), r * 8 + Math.floor(h * 97 % 6), 1, 1);
  if (h > .8) ctx.fillRect(c * 8 + Math.floor(h * 31 % 7), r * 8 + Math.floor(h * 53 % 7), 2, 1);
  ctx.fillStyle = '#211f33'; ctx.fillRect(c * 8, r * 8, 8, 1);
}
function drawWall(grid, r, c) {
  const below = r + 1 < grid.length && grid[r + 1][c] !== '#';
  ctx.fillStyle = '#0f0e1a'; ctx.fillRect(c * 8, r * 8, 8, 8);
  if (below) {
    ctx.fillStyle = '#5f574f'; ctx.fillRect(c * 8, r * 8 + 3, 8, 5);
    ctx.fillStyle = '#3a3640';
    ctx.fillRect(c * 8, r * 8 + 5, 8, 1);
    const off = (r + c) % 2 ? 2 : 5;
    ctx.fillRect(c * 8 + off, r * 8 + 3, 1, 2); ctx.fillRect(c * 8 + ((off + 4) % 8), r * 8 + 6, 1, 2);
    ctx.fillStyle = '#83769c'; ctx.fillRect(c * 8, r * 8 + 2, 8, 1);
  } else if (hash(r, c) > .7) {
    ctx.fillStyle = '#1a1929'; ctx.fillRect(c * 8 + 2, r * 8 + 3, 2, 1);
  }
}
function drawTiles(grid, t, start) {
  for (let r = 0; r < grid.length; r++) for (let c = 0; c < grid[r].length; c++) {
    if (grid[r][c] === '#') drawWall(grid, r, c); else drawFloor(grid, r, c);
  }
  if (start) {  // glowing rune where the run started
    ctx.strokeStyle = '#7e2553'; ctx.lineWidth = 1;
    ctx.strokeRect(start[1] * 8 + 1.5, start[0] * 8 + 1.5, 5, 5);
  }
  for (let r = 0; r < grid.length; r++) for (let c = 0; c < grid[r].length; c++) {
    const ch = grid[r][c], x = c * 8, y = r * 8, ph = hash(r, c) * 1000;
    if (ch === 'M') ctx.drawImage(spr('slime', Math.floor((t + ph) / 380)), x, y);
    else if (ch === 'C') ctx.drawImage(spr('coin', Math.floor((t + ph) / 140)), x, y);
    else if (ch === 'H') ctx.drawImage(spr('potion'), x, y + (Math.floor((t + ph) / 500) % 2 ? -1 : 0));
    else if (ch === 'K') ctx.drawImage(spr('key'), x, y + (Math.floor((t + ph) / 400) % 2 ? -1 : 0));
    else if (ch === 'D') ctx.drawImage(spr('door'), x, y);
    else if (ch === 'T') ctx.drawImage(spr('spikes', Math.floor((t + ph) / 900)), x, y);
    else if (ch === 'E') {
      ctx.drawImage(spr('stairs'), x, y);
      ctx.strokeStyle = `rgba(255,236,39,${.35 + .35 * Math.sin(t / 250)})`; ctx.lineWidth = 1;
      ctx.strokeRect(x + .5, y + .5, 7, 7);
    }
  }
}
function drawKnight(r, c, frame, face, swap) {
  const img = spr('knight', frame, swap);
  if (face < 0) { ctx.save(); ctx.translate(c * 8 + 8, r * 8); ctx.scale(-1, 1); ctx.drawImage(img, 0, 0); ctx.restore(); }
  else ctx.drawImage(img, c * 8, r * 8);
}
function drawParticles() {
  particles = particles.filter(p => p.life > 0);
  for (const p of particles) {
    p.x += p.vx; p.y += p.vy; p.vy += .05; p.life--;
    ctx.fillStyle = p.col; ctx.fillRect(Math.round(p.x), Math.round(p.y), 1, 1);
  }
}

// ---------------------------------------------------------------- play mode
let mode = 'final', G = null, RACE = null;
function findStart(grid) { for (let r = 0; r < grid.length; r++) for (let c = 0; c < grid[r].length; c++) if (grid[r][c] === 'S') return [r, c]; return [1, 1]; }
function newGame(which) {
  const L = which === 'final' ? D.final_level : D.initial_level;
  const grid = L.grid.map(row => row.split(''));
  const [r, c] = findStart(grid); grid[r][c] = '.';
  G = {which, grid, r, c, start: [r, c], hp: R.START_HP, keys: 0, coins: 0, steps: 0, over: false, won: false,
       mhp: {}, seen: new Set(), face: 1, frame: 0, hurt: 0, total: L.grid.join('').split('C').length - 1};
  grid.forEach((row, rr) => row.forEach((t, cc) => { if (t === 'M') G.mhp[rr + ',' + cc] = R.MONSTER_HP; }));
  RACE = null; $('race').style.display = 'none'; $('hud').style.display = 'flex';
  hideBanner(); fitCanvas(grid); updateHud();
  say(which === 'final' ? 'OPTIMISED LEVEL: reach the glowing stairs.' : 'ORIGINAL LEVEL: before the agents improved it.');
}
function nearMonster(r, c) { return [[0, 1], [1, 0], [0, -1], [-1, 0]].some(([a, b]) => G.grid[r + a] && G.grid[r + a][c + b] === 'M'); }
function hurt(n) {
  G.hp -= n; G.hurt = 10; shake(); SFX.hit();
  floatText(G.r, G.c, '-' + n, '#ff004d');
}
function move(dr, dc) {
  if (!G || G.over) return;
  if (dc) G.face = dc;
  const r = G.r + dr, c = G.c + dc, t = G.grid[r][c];
  if (t === '#') return;
  if (t === 'D' && !G.keys) { say('The door is locked. Find the key.'); beep(110, .1); return; }
  G.steps++; G.frame ^= 1; SFX.step();
  if (t === 'M') {
    const k = r + ',' + c; let taken = 0;
    while (G.mhp[k] > 0 && G.hp - taken > 0) {
      G.mhp[k] -= Math.random() < .5 ? 1 : 2;
      if (G.mhp[k] > 0 && Math.random() < R.MONSTER_HIT_CHANCE) taken += Math.random() < .5 ? 1 : 2;
    }
    if (taken) hurt(taken);
    if (G.hp <= 0) return end(false, 'A slime defeated you.');
    G.grid[r][c] = '.'; burst(r, c, '#00e436', 16); SFX.kill(); say('Slime defeated!' + (taken ? ` (took ${taken} damage)` : ''));
  }
  G.r = r; G.c = c;
  if (t === 'T' && Math.random() < R.TRAP_TRIGGER_CHANCE) { hurt(R.TRAP_DAMAGE); say('Spike trap!'); burst(r, c, '#c2c3c7', 8); }
  else if (t === 'T') say('You tiptoe over the spikes...');
  else if (t === 'H') { const before = G.hp; G.hp = Math.min(R.MAX_HP, G.hp + R.POTION_HEAL); G.grid[r][c] = '.'; SFX.potion();
    floatText(r, c, '+' + (G.hp - before), '#00e436'); burst(r, c, '#ff77a8', 10); say('Potion: healed.'); }
  else if (t === 'C') { G.coins++; G.grid[r][c] = '.'; SFX.coin(); floatText(r, c, '+1', '#ffec27'); burst(r, c, '#ffec27', 8); say('Coin!'); }
  else if (t === 'K') { G.keys++; G.grid[r][c] = '.'; SFX.key(); floatText(r, c, 'KEY', '#ffec27'); say('You found the key!'); }
  else if (t === 'D') { G.grid[r][c] = '.'; SFX.door(); burst(r, c, '#ab5236', 10); say('The door creaks open.'); }
  if (t !== 'M' && nearMonster(r, c) && Math.random() < R.LUNGE_CHANCE) { hurt(1); say('A slime lunges at you!'); }
  if (G.hp <= 0) return end(false, 'You died.');
  if (t === 'E') return end(true, `Escaped in ${G.steps} steps with ${G.coins}/${G.total} coins.`);
  updateHud();
}
function end(won, text) {
  G.over = true; G.won = won; updateHud();
  if (won) { SFX.win(); for (let i = 0; i < 4; i++) burst(G.r, G.c, ['#ffec27', '#00e436', '#29adff', '#ff77a8'][i], 14); }
  else { SFX.die(); burst(G.r, G.c, '#ff004d', 24); }
  showBanner(won ? 'LEVEL CLEAR!' : 'GAME OVER', text + '  [R] retry  [3] watch the AI');
}
function updateHud() {
  if (!G) return;
  let hearts = '';
  for (let i = 0; i < R.MAX_HP; i++) hearts += `<span class="heart ${i < G.hp ? '' : 'off'}"></span>`;
  $('hud').innerHTML = `<span class="hp">${hearts}</span><span>COINS ${G.coins}/${G.total}</span>` +
    `<span>KEY ${G.keys ? 'YES' : '--'}</span><span>STEPS ${G.steps}</span><span>${G.which === 'final' ? 'OPTIMISED' : 'ORIGINAL'} LEVEL</span>`;
}
function say(t) { $('msg').textContent = t; }
function showBanner(big, small) { $('bbig').textContent = big; $('bsmall').textContent = small; $('banner').style.display = 'flex'; }
function hideBanner() { $('banner').style.display = 'none'; }

function drawPlay(t) {
  drawTiles(G.grid, t, G.start);
  drawKnight(G.r, G.c, G.frame, G.face, G.hurt > 0 && G.hurt % 4 < 2 ? {'*': '#ff004d'} : null);
  if (G.hurt > 0) G.hurt--;
  drawParticles();
  // torchlight + fog of war
  const rad = 3.6 + Math.sin(t / 180) * .15;
  for (let r = 0; r < G.grid.length; r++) for (let c = 0; c < G.grid[r].length; c++) {
    const d = Math.hypot(r - G.r, c - G.c);
    if (d <= 5) G.seen.add(r * 1000 + c);
    let a;
    if (G.over) a = 0;
    else if (d <= rad) a = 0;
    else if (d <= rad + 2.2) a = .25 + (d - rad) * .2;
    else a = G.seen.has(r * 1000 + c) ? .72 : .97;
    if (a > 0) { ctx.fillStyle = `rgba(4,4,10,${Math.min(a, .97)})`; ctx.fillRect(c * 8, r * 8, 8, 8); }
  }
}

// ---------------------------------------------------------------- AI race mode (recorded bot playthroughs)
function newRace(which) {
  const L = which === 'final' ? D.final_level : D.initial_level;
  const grid = L.grid.map(row => row.split(''));
  const start = findStart(grid); grid[start[0]][start[1]] = '.';
  RACE = {which, grid, start, i: 0, last: 0, done: false,
    bots: ['rusher', 'cautious', 'explorer'].map(p => ({p, tr: D.traces[which][p].trace, res: D.traces[which][p].result, trail: []}))};
  G = null; $('hud').style.display = 'none'; $('race').style.display = 'block';
  hideBanner(); fitCanvas(grid); drawRaceHud();
  say((which === 'final' ? 'OPTIMISED' : 'ORIGINAL') + ' LEVEL: recorded playthroughs of the three simulated players.');
}
function stepRace() {
  RACE.i++;
  let alive = false;
  for (const b of RACE.bots) {
    const k = Math.min(RACE.i, b.tr.length - 1);
    if (RACE.i < b.tr.length) {
      alive = true;
      const [r, c, hp, ev] = b.tr[k];
      b.trail.push([r, c]);
      if (['coin', 'potion', 'key', 'door', 'fight'].includes(ev) && RACE.grid[r][c] !== '.') {
        RACE.grid[r][c] = '.';
        burst(r, c, ev === 'fight' ? '#00e436' : ev === 'coin' ? '#ffec27' : BOTCOL[b.p], 8);
      }
      if (ev === 'trap' || ev === 'hit') floatText(r, c, '!', BOTCOL[b.p]);
      if (ev === 'died') { burst(r, c, '#ff004d', 18); floatText(r, c, 'X', '#ff004d'); }
      if (ev === 'coin') beep(1200, .03, 'square', .02);
    }
  }
  drawRaceHud();
  if (!alive && !RACE.done) {
    RACE.done = true;
    const sum = RACE.bots.map(b => `${b.p.toUpperCase()}: ${b.res}`).join('  |  ');
    showBanner('RACE OVER', sum + '  -  press 3 or 4 to replay');
  }
}
function drawRaceHud() {
  $('race').innerHTML = RACE.bots.map(b => {
    const k = Math.min(RACE.i, b.tr.length - 1), hp = b.tr[k][2];
    const st = RACE.i >= b.tr.length - 1 ? b.res : 'running...';
    return `<div class="row"><span style="color:${BOTCOL[b.p]}">${b.p.toUpperCase()}</span>` +
      `<span class="hpb"><i style="width:${hp / R.MAX_HP * 100}%;background:${BOTCOL[b.p]}"></i></span>` +
      `<span>${k} steps</span><span>${st.toUpperCase()}</span></div>`;
  }).join('');
}
function drawRace(t) {
  drawTiles(RACE.grid, t, RACE.start);
  for (const b of RACE.bots) {
    ctx.fillStyle = BOTCOL[b.p] + '55';
    for (const [r, c] of b.trail) ctx.fillRect(c * 8 + 3, r * 8 + 3, 2, 2);
  }
  RACE.bots.forEach((b, j) => {
    const k = Math.min(RACE.i, b.tr.length - 1), [r, c, hp, ev] = b.tr[k];
    if (ev === 'died' && RACE.i >= b.tr.length - 1) return;
    const prev = b.tr[Math.max(0, k - 1)];
    drawKnight(r, c, k % 2, c - prev[1] < 0 ? -1 : 1, {B: BOTCOL[b.p]});
  });
  drawParticles();
  if (!RACE.done && t - RACE.last > 120) { RACE.last = t; stepRace(); }
}

// ---------------------------------------------------------------- side panels (real run data)
function chips() {
  const sps = D.sim_seconds ? Math.round(D.total_sims / D.sim_seconds) : 0;
  $('chips').innerHTML = [
    ['AGENTS', D.llm], ['WORKERS', D.workers], ['SIMS', D.total_sims.toLocaleString()], ['SIMS/S', sps.toLocaleString()],
    ['QUALITY', FIRST.best_score.toFixed(3) + ' → ' + LAST.best_score.toFixed(3)]
  ].map(([a, b]) => `<span class="chip">${a} <b>${b}</b></span>`).join('');
}
function brief() {
  const ps = Object.entries(D.brief.problem_share).sort((a, b) => b[1] - a[1]);
  $('brief').innerHTML = ps.map(([k, v]) => `<div class="bar"><span class="lab">${(D.problem_names[k] || k).split(' / ')[0].replace('Difficulty too high','Too hard').replace('Confusing layout','Confusing').replace('Repetitive','Repetitive').replace('Unfair traps on forced routes','Unfair traps').replace('Little reward for exploring','No reward').replace('Too easy','Too easy')}</span>` +
    `<span class="trk"><span class="fil" style="width:${v * 100 / .4}%"></span></span><span class="val">${Math.round(v * 100)}%</span></div>`).join('') +
    `<div class="bar"><span class="lab">target finish</span><span class="trk"><span class="fil" style="width:${D.brief.target_completion * 100}%;background:var(--y)"></span></span><span class="val">${Math.round(D.brief.target_completion * 100)}%</span></div>`;
}
function comps() {
  $('comps').innerHTML = ['balance', 'engagement', 'flow', 'skill', 'tension'].map(k => {
    const a = FIRST.best_quality[k], z = LAST.best_quality[k];
    return `<div class="bar"><span class="lab">${k}</span><span class="trk"><span class="fil a" style="width:${a * 100}%"></span></span>` +
      `<span class="trk"><span class="fil" style="width:${z * 100}%;background:var(--g)"></span></span><span class="val">${a.toFixed(2)}→${z.toFixed(2)}</span></div>`;
  }).join('');
  const p0 = FIRST.best_metrics.per_persona_completion, p1 = LAST.best_metrics.per_persona_completion;
  $('pers').innerHTML = ['rusher', 'cautious', 'explorer'].map(p =>
    `<div class="bar"><span class="lab" style="color:${BOTCOL[p]}">${p}</span><span class="trk"><span class="fil a" style="width:${(p0[p] || 0) * 100}%"></span></span>` +
    `<span class="trk"><span class="fil" style="width:${(p1[p] || 0) * 100}%;background:${BOTCOL[p]}"></span></span>` +
    `<span class="val">${Math.round((p0[p] || 0) * 100)}→${Math.round((p1[p] || 0) * 100)}%</span></div>`).join('');
}
// replay of the optimisation run: round by round, candidates and best score
const ch = $('chart'), cx = ch.getContext('2d');
let rp = {k: 0, t0: 0};
const allScores = H.flatMap(h => h.candidates.map(c => c.quality.total));
const lo = Math.min(...allScores) - .03, hi = Math.max(...allScores) + .03;
function cxX(i) { return 6 + i * (ch.width - 12) / Math.max(1, H.length - 1); }
function cxY(v) { return 4 + (hi - v) * (ch.height - 10) / (hi - lo); }
function drawChart(t) {
  cx.fillStyle = '#0a0b14'; cx.fillRect(0, 0, ch.width, ch.height);
  cx.fillStyle = '#1b1c2e';
  for (let g = 0; g < 4; g++) cx.fillRect(0, 4 + g * (ch.height - 10) / 3, ch.width, 1);
  for (let i = 0; i <= rp.k; i++) {
    const h = H[i];
    h.candidates.forEach(c => { cx.fillStyle = i === rp.k ? '#ffa300' : '#4a4866'; cx.fillRect(Math.round(cxX(i)) - 1, Math.round(cxY(c.quality.total)) - 1, 2, 2); });
  }
  cx.fillStyle = '#29adff';
  for (let i = 1; i <= rp.k; i++) {
    const x0 = cxX(i - 1), y0 = cxY(H[i - 1].best_score), x1 = cxX(i), y1 = cxY(H[i].best_score);
    for (let s = 0; s <= 20; s++) cx.fillRect(Math.round(x0 + (x1 - x0) * s / 20), Math.round(y0 + (y1 - y0) * s / 20), 1, 1);
  }
  for (let i = 0; i <= rp.k; i++) { cx.fillStyle = '#00e436'; cx.fillRect(Math.round(cxX(i)) - 1, Math.round(cxY(H[i].best_score)) - 1, 3, 3); }
}
function stepReplay() {
  rp.k = (rp.k + 1) % H.length;
  const h = H[rp.k];
  $('replaylab').textContent = `ROUND ${h.round}/${H.length - 1}: ${h.candidates.length} candidate(s), ${h.sims.toLocaleString()} sims in ${(+h.sweep_seconds).toFixed(2)}s, ${h.decision.split(' ')[0]}, best ${h.best_score.toFixed(3)}`;
  coreSweep(h);
}
function buildCores() {
  let s = '';
  for (let i = 0; i < D.workers; i++) s += `<div class="core">W${i}<div class="ld"><i id="ld${i}" style="width:0%"></i></div></div>`;
  $('cores').innerHTML = s;
}
function coreSweep(h) {
  // each worker fills over the recorded sweep time of this round (scaled for display)
  const dur = 900;
  for (let i = 0; i < D.workers; i++) {
    const el = $('ld' + i); if (!el) continue;
    el.style.transition = 'none'; el.style.width = '0%'; void el.offsetWidth;
    el.style.transition = `width ${dur * (0.9 + 0.2 * hash(h.round, i))}ms linear`; el.style.width = '100%';
  }
}
// agent feed: real log lines, typed out
let feedI = 0;
function feedTick() {
  if (!D.log.length) return;
  const line = D.log[feedI % D.log.length]; feedI++;
  const m = line.match(/^\s*\[(\w+)\]/); const tag = m ? m[1] : 'other';
  const div = document.createElement('div');
  div.className = 't-' + (['Generator', 'Simulate', 'Critic', 'Optimizer', 'Finalize', 'Router'].includes(tag) ? tag : 'other');
  div.textContent = line.trim();
  const f = $('feed'); f.appendChild(div);
  while (f.children.length > 60) f.firstChild.remove();
}

// ---------------------------------------------------------------- modes, input, loop
function setMode(m) {
  mode = m;
  document.querySelectorAll('#modebar button').forEach(b => b.classList.toggle('on', b.dataset.m === m));
  particles = []; $('fx').innerHTML = '';
  if (m === 'final' || m === 'initial') newGame(m);
  else newRace(m === 'race' ? 'final' : 'initial');
}
document.querySelectorAll('#modebar button').forEach(b => b.onclick = () => setMode(b.dataset.m));
const KEYS = {ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], w: [-1, 0], s: [1, 0], a: [0, -1], d: [0, 1],
  W: [-1, 0], S: [1, 0], A: [0, -1], D: [0, 1]};
let booted = false;
addEventListener('keydown', e => {
  if (!booted) { if (e.key === 'Enter' || e.key === ' ') startApp(); return; }
  if (KEYS[e.key]) { e.preventDefault(); if (G) move(...KEYS[e.key]); return; }
  if (e.key === '1') setMode('final'); else if (e.key === '2') setMode('initial');
  else if (e.key === '3') setMode('race'); else if (e.key === '4') setMode('raceinit');
  else if (e.key === 'r' || e.key === 'R') setMode(mode);
  else if (e.key === 'c' || e.key === 'C') $('crt').style.display = $('crt').style.display === 'none' ? '' : 'none';
  else if (e.key === 'm' || e.key === 'M') { soundOn = !soundOn; say(soundOn ? 'Sound on' : 'Sound off'); }
});
addEventListener('resize', () => { if (G) fitCanvas(G.grid); else if (RACE) fitCanvas(RACE.grid); });
function loop(t) {
  ctx.clearRect(0, 0, cv.width, cv.height);
  if (G) drawPlay(t); else if (RACE) drawRace(t);
  drawChart(t);
  requestAnimationFrame(loop);
}
// boot sequence
const sps = D.sim_seconds ? Math.round(D.total_sims / D.sim_seconds) : 0;
const BOOT = [
  '> LEVELFORGE BOOT SEQUENCE',
  `> DIGITAL TWIN ............................ OK (${D.final_level.grid[0].length}x${D.final_level.grid.length} grid)`,
  `> PLAYER REVIEWS ANALYSED ................. ${D.brief.reviews_analyzed}`,
  `> AGENT GRAPH: GENERATOR > SIMULATE > CRITIC > OPTIMIZER ... OK`,
  `> REASONING ENGINE ........................ ${D.llm}`,
  `> PARALLEL WORKERS ........................ ${D.workers}`,
  `> SIMULATED PLAYTHROUGHS .................. ${D.total_sims.toLocaleString()} (${sps.toLocaleString()}/s)`,
  `> LEVEL QUALITY ........................... ${FIRST.best_score.toFixed(3)} -> ${LAST.best_score.toFixed(3)}`,
];
let bootLine = 0, bootChar = 0;
function bootType() {
  if (booted) return;
  if (bootLine >= BOOT.length) { $('title').style.opacity = 1; $('press').style.opacity = 1; return; }
  const line = BOOT[bootLine];
  bootChar = Math.min(line.length, bootChar + 3);
  const done = BOOT.slice(0, bootLine).join('\n');
  $('bootlog').textContent = (done ? done + '\n' : '') + line.slice(0, bootChar) + '_';
  if (bootChar >= line.length) { bootLine++; bootChar = 0; beep(660, .02, 'square', .015); setTimeout(bootType, 120); }
  else setTimeout(bootType, 12);
}
function startApp() {
  if (booted) return;
  booted = true; $('boot').style.display = 'none';
  beep(523, .1); setTimeout(() => beep(784, .15), 100);
  chips(); brief(); comps(); buildCores();
  setMode('final');
  stepReplay(); setInterval(stepReplay, 1600);
  for (let i = 0; i < 8; i++) feedTick(); setInterval(feedTick, 700);
  requestAnimationFrame(loop);
}
$('boot').onclick = startApp;
bootType();
</script></body></html>
"""
