"""
Builds a self-contained HTML report (no internet needed to open it):

  1. player feedback -> design-problem taxonomy and design brief
  2. agent loop: score per round, candidates, accept/reject decisions, agent log
  3. initial vs optimised level side by side with metrics
  4. animated bot replays (rusher / cautious / explorer) on both levels
  5. the final level as a playable prototype (arrow keys / WASD)
"""
from __future__ import annotations

import html
import json

TITLE = "LevelForge: Agentic Digital Twin for Game-Level Optimisation"


def build_report(data: dict) -> str:
    payload = json.dumps(data).replace("</", "<\\/")
    return TEMPLATE.replace("__TITLE__", html.escape(TITLE)).replace("__DATA__", payload)


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#272b35;--ink:#e7e9ee;--muted:#9aa1ad;--acc:#7cc4ff;--good:#6fd39b;--bad:#ff7b7b;--warn:#ffc46b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:0 0 12px}h3{font-size:15px;margin:14px 0 8px;color:var(--muted);font-weight:600}
.sub{color:var(--muted);margin-bottom:22px}
section{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px;margin:18px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.kpi{background:#11141a;border:1px solid var(--line);border-radius:10px;padding:12px}
.kpi b{display:block;font-size:22px}.kpi span{color:var(--muted);font-size:12.5px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:820px){.grid2{grid-template-columns:1fr}}
.bar{display:flex;align-items:center;gap:10px;margin:6px 0}.bar .lab{width:230px;color:var(--muted);font-size:13.5px}
.bar .track{flex:1;background:#11141a;border-radius:6px;height:16px;overflow:hidden}.bar .fill{height:100%;background:var(--acc)}
.bar .val{width:52px;text-align:right;font-variant-numeric:tabular-nums}
#comp .bar .lab{width:96px}#comp .bar .val{width:86px;font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13.5px}th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{color:var(--muted);font-weight:600}td.num{text-align:right;font-variant-numeric:tabular-nums}
.up{color:var(--good)}.down{color:var(--bad)}
.tag{display:inline-block;padding:1px 7px;border-radius:99px;font-size:12px;border:1px solid var(--line)}
.tag.ok{color:var(--good);border-color:#2f5a43}.tag.no{color:var(--muted)}
pre{background:#0b0d11;border:1px solid var(--line);border-radius:8px;padding:12px;max-height:360px;overflow:auto;font-size:12.5px}
canvas{background:#0b0d11;border-radius:8px;max-width:100%;image-rendering:pixelated}
button,select{background:#1f2430;color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:6px 11px;font:inherit;font-size:13.5px;cursor:pointer}
button.on{border-color:var(--acc);color:var(--acc)}.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12.5px;color:var(--muted)}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;vertical-align:-1px}
.notes{border-left:3px solid var(--acc);padding:4px 14px;color:#cfd5df}
details summary{cursor:pointer;color:var(--muted)}
.status{font-variant-numeric:tabular-nums;color:var(--muted)}
</style></head><body><main>
<h1>__TITLE__</h1>
<div class="sub" id="sub"></div>
<div class="kpis" id="kpis"></div>

<section><h2>1. Player feedback &rarr; design problems</h2>
<div class="grid2"><div><h3>Problem share across reviews</h3><div id="tax"></div></div>
<div><h3>Design brief derived from reviews</h3><div id="brief"></div></div></div>
<h3>Actionable design goals</h3><table id="goals"></table></section>

<section><h2>2. Agent optimisation loop</h2>
<div class="grid2"><div><h3>Best quality score per round</h3><svg id="chart" viewBox="0 0 520 240" width="100%"></svg></div>
<div><h3>Quality components: initial vs final</h3><div id="comp"></div></div></div>
<h3>Rounds</h3><table id="rounds"></table>
<details><summary>Full agent trace</summary><pre id="log"></pre></details></section>

<section><h2>3. Before and after</h2>
<div class="legend" id="legend"></div>
<div class="grid2"><div><h3 id="lt0">Initial level</h3><canvas id="lvl0"></canvas></div>
<div><h3 id="lt1">Optimised level</h3><canvas id="lvl1"></canvas></div></div>
<h3>Metrics</h3><table id="mt"></table></section>

<section><h2>4. Simulated playthroughs</h2>
<div class="row"><select id="rl"><option value="initial">Initial level</option><option value="final" selected>Optimised level</option></select>
<span id="rp"></span><button id="rplay">Play</button><span class="status" id="rstat"></span></div>
<canvas id="rc"></canvas></section>

<section><h2>5. Playable prototype (optimised level)</h2>
<div class="row"><button id="restart">Restart</button><span class="status" id="pstat">Click the map, then use arrow keys or WASD.</span></div>
<canvas id="pc" tabindex="0"></canvas></section>

<section><h2>Designer notes</h2><p class="notes" id="notes"></p></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const pct = x => (x*100).toFixed(0)+'%';
const f3 = x => (+x).toFixed(3);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

$('sub').textContent = `LLM: ${D.llm} | ${D.workers} parallel worker processes | ${D.timestamp}`;
const H = D.history, first = H[0], last = H[H.length-1];
const kp = [[f3(first.best_score)+' → '+f3(last.best_score),'quality score (initial → final)'],
  [D.total_sims.toLocaleString(),'simulated playthroughs'],[D.workers,'worker processes'],
  [(D.total_sims/D.sim_seconds).toFixed(0),'simulations per second'],[H.length-1,'optimisation rounds'],
  [D.brief.reviews_analyzed,'reviews analysed']];
$('kpis').innerHTML = kp.map(([b,s])=>`<div class="kpi"><b>${b}</b><span>${s}</span></div>`).join('');

// 1. taxonomy
const ps = Object.entries(D.brief.problem_share).sort((a,b)=>b[1]-a[1]);
const names = D.problem_names;
$('tax').innerHTML = ps.map(([k,v])=>`<div class="bar"><div class="lab">${esc(names[k]||k)}</div><div class="track"><div class="fill" style="width:${v*100}%"></div></div><div class="val">${pct(v)}</div></div>`).join('');
const b = D.brief;
$('brief').innerHTML = `<table><tr><th>Target completion rate</th><td class="num">${pct(b.target_completion)}</td></tr>
<tr><th>Target HP lost by finishers</th><td class="num">${pct(b.target_tension)}</td></tr>`+
Object.entries(b.weights).map(([k,v])=>`<tr><th>Weight: ${k}</th><td class="num">${(+v).toFixed(2)}</td></tr>`).join('')+'</table>';
$('goals').innerHTML = '<tr><th>Problem</th><th>Share</th><th>Component</th><th>Cause</th><th>Modification</th><th>Test</th></tr>'+
 b.design_goals.map(g=>`<tr><td>${esc(g.description)}</td><td class="num">${pct(g.share)}</td><td>${esc(g.affected_component)}</td><td>${esc(g.possible_cause)}</td><td>${esc(g.design_modification)}</td><td>${esc(g.test)}</td></tr>`).join('');

// 2. chart
(function(){
  const svg=$('chart'), W=520, Ht=240, L=44, R=12, T=12, B=30;
  const ys=H.map(h=>h.best_score), allc=H.flatMap(h=>h.candidates.map(c=>c.quality.total));
  const lo=Math.min(...allc,...ys)-0.03, hi=Math.max(...allc,...ys)+0.03;
  const x=i=>L+(H.length===1?0:i*(W-L-R)/(H.length-1)), y=v=>T+(hi-v)*(Ht-T-B)/(hi-lo);
  let s='';
  for(let k=0;k<=4;k++){const v=lo+(hi-lo)*k/4;s+=`<line x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}" stroke="#272b35"/><text x="${L-6}" y="${y(v)+4}" fill="#9aa1ad" font-size="11" text-anchor="end">${v.toFixed(2)}</text>`;}
  H.forEach((h,i)=>{s+=`<text x="${x(i)}" y="${Ht-10}" fill="#9aa1ad" font-size="11" text-anchor="middle">R${i}</text>`;
    h.candidates.forEach(c=>{s+=`<circle cx="${x(i)}" cy="${y(c.quality.total)}" r="3.5" fill="#9aa1ad" opacity=".45"><title>${esc(c.plan)}: ${f3(c.quality.total)}</title></circle>`;});});
  s+=`<polyline fill="none" stroke="#7cc4ff" stroke-width="2.5" points="${ys.map((v,i)=>x(i)+','+y(v)).join(' ')}"/>`;
  ys.forEach((v,i)=>{s+=`<circle cx="${x(i)}" cy="${y(v)}" r="4.5" fill="#7cc4ff"><title>best ${f3(v)}</title></circle>`;});
  svg.innerHTML=s;
})();
$('comp').innerHTML = ['balance','engagement','flow','skill','tension'].map(k=>{
  const a=first.best_quality[k], z=last.best_quality[k];
  return `<div class="bar"><div class="lab">${k}</div><div class="track" style="position:relative"><div class="fill" style="width:${a*100}%;background:#59606e"></div></div><div class="track"><div class="fill" style="width:${z*100}%"></div></div><div class="val">${a.toFixed(2)}→${z.toFixed(2)}</div></div>`}).join('')+
  '<div class="legend"><span><i style="background:#59606e"></i>initial</span><span><i style="background:#7cc4ff"></i>final</span></div>';
$('rounds').innerHTML = '<tr><th>Round</th><th>Candidates (plan &rarr; score)</th><th>Decision</th><th class="num">Best</th><th class="num">Sim time</th></tr>'+
 H.map(h=>`<tr><td>R${h.round}</td><td>${h.candidates.map(c=>`${esc(c.plan)} &rarr; <b>${f3(c.quality.total)}</b>`).join('<br>')}</td>
 <td><span class="tag ${h.decision==='accepted'?'ok':'no'}">${esc(h.decision)}</span></td><td class="num">${f3(h.best_score)}</td><td class="num">${(+h.sweep_seconds).toFixed(2)}s</td></tr>`).join('');
$('log').textContent = D.log.join('\n');

// 3. level drawing
const COL={'#':'#2a2f3a','.':'#151922','S':'#3b82f6','E':'#22c55e','K':'#facc15','D':'#a16207','M':'#ef4444','T':'#c084fc','H':'#f472b6','C':'#fbbf24'};
const NAME={'S':'start','E':'exit','K':'key','D':'door','M':'monster','T':'trap','H':'potion','C':'coin'};
$('legend').innerHTML = Object.entries(NAME).map(([k,v])=>`<span><i style="background:${COL[k]}"></i>${v}</span>`).join('');
function cellSize(g){return Math.max(14,Math.min(30,Math.floor(540/g[0].length)));}
function drawGrid(cv, g, extra){
  const s=cellSize(g); cv.width=g[0].length*s; cv.height=g.length*s; const c=cv.getContext('2d');
  for(let r=0;r<g.length;r++)for(let q=0;q<g[r].length;q++){
    const t=g[r][q]; c.fillStyle=t==='#'?COL['#']:COL['.']; c.fillRect(q*s,r*s,s,s);
    if(t!=='#'&&t!=='.'){c.fillStyle=COL[t];
      if(t==='M'||t==='C'||t==='H'){c.beginPath();c.arc(q*s+s/2,r*s+s/2,s*(t==='C'?0.22:0.34),0,7);c.fill();}
      else if(t==='T'){c.beginPath();c.moveTo(q*s+s/2,r*s+s*.2);c.lineTo(q*s+s*.82,r*s+s*.8);c.lineTo(q*s+s*.18,r*s+s*.8);c.fill();}
      else c.fillRect(q*s+s*.15,r*s+s*.15,s*.7,s*.7);
      if(t==='S'||t==='E'||t==='K'||t==='D'){c.fillStyle='#0b0d11';c.font=`bold ${s*.5}px system-ui`;c.textAlign='center';c.textBaseline='middle';c.fillText(t,q*s+s/2,r*s+s/2+1);}}
  }
  if(extra) extra(c,s); return s;
}
drawGrid($('lvl0'), D.initial_level.grid); drawGrid($('lvl1'), D.final_level.grid);
$('lt0').textContent=`Initial level (score ${f3(first.best_score)})`; $('lt1').textContent=`Optimised level (score ${f3(last.best_score)})`;
const MK=[['completion_rate','Completion rate',1],['death_rate','Death rate',1],['avg_damage','Avg damage taken',0],['backtrack_ratio','Backtracking',1],['exploration','Exploration',1],['coin_collection','Coins collected (explorer)',1],['hp_lost_by_finishers','HP lost by finishers',1]];
const m0=first.best_metrics, m1=last.best_metrics;
$('mt').innerHTML='<tr><th>Metric</th><th style="text-align:right">Initial</th><th style="text-align:right">Optimised</th></tr>'+
 MK.map(([k,n,p])=>`<tr><td>${n}</td><td class="num">${p?pct(m0[k]):(+m0[k]).toFixed(2)}</td><td class="num">${p?pct(m1[k]):(+m1[k]).toFixed(2)}</td></tr>`).join('')+
 ['rusher','cautious','explorer'].map(p=>`<tr><td>Completion: ${p}</td><td class="num">${pct(m0.per_persona_completion[p]||0)}</td><td class="num">${pct(m1.per_persona_completion[p]||0)}</td></tr>`).join('');

// 4. replays
let persona='cautious', timer=null;
$('rp').innerHTML=['rusher','cautious','explorer'].map(p=>`<button data-p="${p}" class="${p===persona?'on':''}">${p}</button>`).join('');
$('rp').onclick=e=>{const p=e.target.dataset.p;if(!p)return;persona=p;[...$('rp').children].forEach(b=>b.classList.toggle('on',b.dataset.p===p));startReplay();};
$('rl').onchange=startReplay; $('rplay').onclick=startReplay;
function startReplay(){
  clearInterval(timer); const which=$('rl').value; const lvl=which==='final'?D.final_level:D.initial_level;
  const tr=D.traces[which][persona]; let i=0; const g=lvl.grid.map(r=>r.split(''));
  const outcome=tr.result;
  function frame(){
    const [r,c,hp,ev]=tr.trace[i];
    if(['coin','potion','key','door'].includes(ev)) g[r][c]='.';
    if(ev==='fight') g[r][c]='.';
    drawGrid($('rc'), g.map(x=>x.join('')), (ctx,s)=>{
      ctx.strokeStyle='#7cc4ff';ctx.lineWidth=2;ctx.beginPath();
      for(let k=0;k<=i;k++){const [rr,cc]=tr.trace[k];const X=cc*s+s/2,Y=rr*s+s/2;k?ctx.lineTo(X,Y):ctx.moveTo(X,Y);}ctx.stroke();
      ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(c*s+s/2,r*s+s/2,s*.32,0,7);ctx.fill();});
    $('rstat').textContent=`step ${i}/${tr.trace.length-1}  HP ${hp}  ${ev||''}`+(i===tr.trace.length-1?`  — ${outcome}`:'');
    if(++i>=tr.trace.length) clearInterval(timer);
  }
  frame(); timer=setInterval(frame,90);
}
startReplay();

// 5. playable prototype (same rules as the Python simulator)
const P={}; const R=D.rules;
function rnd(){return Math.random();}
function reset(){
  P.g=D.final_level.grid.map(r=>r.split('')); P.hp=R.START_HP; P.keys=0; P.coins=0; P.steps=0; P.over=false; P.msg='';
  P.mhp={}; P.g.forEach((row,r)=>row.forEach((t,c)=>{if(t==='S'){P.r=r;P.c=c;row[c]='.';} if(t==='M')P.mhp[r+','+c]=R.MONSTER_HP;}));
  P.total=D.final_level.grid.join('').split('C').length-1; drawPlay();
}
function near(r,c){return [[0,1],[1,0],[0,-1],[-1,0]].some(([a,b])=>P.g[r+a]&&P.g[r+a][c+b]==='M');}
function move(dr,dc){
  if(P.over)return; const r=P.r+dr,c=P.c+dc,t=P.g[r][c]; if(t==='#')return;
  if(t==='D'&&!P.keys){P.msg='The door is locked. Find the key.';drawPlay();return;}
  P.steps++; P.msg='';
  if(t==='M'){const k=r+','+c; while(P.mhp[k]>0&&P.hp>0){P.mhp[k]-=rnd()<.5?1:2; if(P.mhp[k]>0&&rnd()<R.MONSTER_HIT_CHANCE)P.hp-=rnd()<.5?1:2;}
    if(P.hp<=0){P.over=true;P.msg='You were defeated by a monster.';drawPlay();return;} P.g[r][c]='.'; P.msg='You defeated a monster.';}
  P.r=r;P.c=c;
  if(t==='T'&&rnd()<R.TRAP_TRIGGER_CHANCE){P.hp-=R.TRAP_DAMAGE;P.msg='A trap hurt you!';}
  else if(t==='H'){P.hp=Math.min(R.MAX_HP,P.hp+R.POTION_HEAL);P.g[r][c]='.';P.msg='Healed.';}
  else if(t==='C'){P.coins++;P.g[r][c]='.';P.msg='Coin!';}
  else if(t==='K'){P.keys++;P.g[r][c]='.';P.msg='Picked up the key.';}
  else if(t==='D'){P.g[r][c]='.';P.msg='Door opened.';}
  if(t!=='M'&&near(r,c)&&rnd()<R.LUNGE_CHANCE){P.hp-=1;P.msg+=' A monster lunges at you.';}
  if(P.hp<=0){P.over=true;P.msg='You died.';}
  else if(t==='E'){P.over=true;P.msg=`You escaped in ${P.steps} steps with ${P.coins}/${P.total} coins!`;}
  drawPlay();
}
function drawPlay(){
  drawGrid($('pc'), P.g.map(x=>x.join('')), (ctx,s)=>{ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(P.c*s+s/2,P.r*s+s/2,s*.34,0,7);ctx.fill();});
  $('pstat').textContent=`HP ${Math.max(P.hp,0)}/${R.MAX_HP}   coins ${P.coins}/${P.total}   key ${P.keys?'yes':'no'}   steps ${P.steps}   ${P.msg}`;
}
$('pc').addEventListener('keydown',e=>{const k={ArrowUp:[-1,0],ArrowDown:[1,0],ArrowLeft:[0,-1],ArrowRight:[0,1],w:[-1,0],s:[1,0],a:[0,-1],d:[0,1]}[e.key];if(k){e.preventDefault();move(...k);}});
$('pc').addEventListener('click',()=>$('pc').focus());
$('restart').onclick=()=>{reset();$('pc').focus();};
reset();
$('notes').textContent=D.designer_notes;
</script></body></html>
"""
