// LevelForge: Breach 3D - first-person shooter built on the agents' levels.
// Three.js scene: procedural PBR textures, flashlight with shadows, pooled ceiling lights, bloom.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

const GD = JSON.parse(document.getElementById('gamedata').textContent);
const R = GD.rules;
const TS = 4, WH = 3.4, EYE = 1.62, MAG = 12;
const $ = id => document.getElementById(id);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const rnd = (a, b) => a + Math.random() * (b - a);
function hash(a, b) { let n = (a * 374761393 + b * 668265263) | 0; n = (n ^ (n >>> 13)) * 1274126177 | 0; return ((n ^ (n >>> 16)) >>> 0) / 4294967295; }

// =================================================================== audio (synthesised)
const A = { ctx: null, sfx: null, music: null, musicOn: true, next: 0, step: 0, noise: null };
function audioInit() {
  if (A.ctx) { if (A.ctx.state === 'suspended') A.ctx.resume(); return; }
  try {
    A.ctx = new (window.AudioContext || window.webkitAudioContext)();
    const m = A.ctx.createGain(); m.gain.value = .7; m.connect(A.ctx.destination);
    A.sfx = A.ctx.createGain(); A.sfx.gain.value = .85; A.sfx.connect(m);
    A.music = A.ctx.createGain(); A.music.gain.value = .18; A.music.connect(m);
    const len = A.ctx.sampleRate * .8, buf = A.ctx.createBuffer(1, len, A.ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    A.noise = buf; A.next = A.ctx.currentTime + .1;
  } catch (e) { A.ctx = null; }
}
function tone(f, dur, type = 'square', vol = .1, slide = 0, when = 0, dest = null) {
  if (!A.ctx || vol < .002) return;
  const t = A.ctx.currentTime + when, o = A.ctx.createOscillator(), g = A.ctx.createGain();
  o.type = type; o.frequency.setValueAtTime(f, t); if (slide) o.frequency.exponentialRampToValueAtTime(Math.max(20, slide), t + dur);
  g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(.0001, t + dur);
  o.connect(g).connect(dest || A.sfx); o.start(t); o.stop(t + dur + .05);
}
function noise(dur, vol = .3, f0 = 2000, f1 = 200, type = 'lowpass', when = 0) {
  if (!A.ctx || vol < .002) return;
  const t = A.ctx.currentTime + when, s = A.ctx.createBufferSource(), fl = A.ctx.createBiquadFilter(), g = A.ctx.createGain();
  s.buffer = A.noise; fl.type = type; fl.frequency.setValueAtTime(f0, t); fl.frequency.exponentialRampToValueAtTime(Math.max(30, f1), t + dur);
  g.gain.setValueAtTime(vol, t); g.gain.exponentialRampToValueAtTime(.0001, t + dur);
  s.connect(fl).connect(g).connect(A.sfx); s.start(t); s.stop(t + dur + .05);
}
const near = (x, z, base) => base * clamp(1 - Math.hypot(x - P.x, z - P.z) / 45, .05, 1);
const SFX = {
  shoot: () => { noise(.09, .32, 5000, 300); tone(180, .1, 'square', .09, 60); tone(1600, .04, 'square', .03, 500); },
  eshoot: (x, z) => { tone(420, .22, 'sawtooth', near(x, z, .08), 120); noise(.12, near(x, z, .08), 3000, 600, 'bandpass'); },
  hit: () => { tone(1300, .05, 'triangle', .09, 800); },
  ric: () => noise(.06, .07, 4000, 2500, 'highpass'),
  boom: (x, z, big) => { noise(big ? .9 : .5, near(x, z, big ? .7 : .45), 1500, 50); tone(80, big ? .7 : .4, 'sine', near(x, z, .45), 30); },
  hurt: () => { tone(140, .25, 'square', .12, 50); noise(.2, .18, 800, 150); },
  pick: () => { tone(988, .07, 'triangle', .1); tone(1480, .12, 'triangle', .1, 0, .06); },
  heal: () => [523, 784, 1047].forEach((f, i) => tone(f, .14, 'triangle', .1, 0, i * .06)),
  key: () => [659, 988, 1319].forEach((f, i) => tone(f, .16, 'square', .06, 0, i * .07)),
  door: () => { tone(70, 1.1, 'sawtooth', .14, 40); noise(1.1, .14, 300, 60); },
  dash: () => noise(.22, .22, 400, 3500, 'bandpass'),
  alert: (x, z) => { tone(880, .08, 'square', near(x, z, .06)); tone(660, .1, 'square', near(x, z, .06), 0, .09); },
  beep: (x, z) => tone(1760, .05, 'square', near(x, z, .07)),
  reload: () => { tone(260, .05, 'square', .06); noise(.05, .1, 3000, 2000, 'highpass', .45); tone(420, .05, 'square', .06, 0, .8); },
  step: () => noise(.05, .025, 900, 300),
  win: () => [523, 659, 784, 1047, 1319, 1568].forEach((f, i) => tone(f, .28, 'square', .055, 0, i * .09)),
  die: () => [392, 330, 262, 196, 131].forEach((f, i) => tone(f, .32, 'sawtooth', .07, 0, i * .12)),
  ui: () => tone(1200, .04, 'triangle', .05),
};
const BASS = [45, 45, 41, 41, 48, 48, 43, 43], ARP = [0, 7, 12, 15, 12, 7, 3, 7];
const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
function musicTick() {
  if (!A.ctx || !A.musicOn) return;
  const spb = 60 / 96 / 2;
  while (A.next < A.ctx.currentTime + .25) {
    const w = A.next - A.ctx.currentTime, root = BASS[Math.floor(A.step / 8) % BASS.length];
    if (A.step % 2 === 0) tone(mtof(root), spb * 1.9, 'sawtooth', .14, 0, w, A.music);
    tone(mtof(root + 24 + ARP[A.step % 8]), spb * .9, 'triangle', .05, 0, w, A.music);
    A.next += spb; A.step++;
  }
}

// =================================================================== procedural textures
function cnv(w, h = w) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
function valueNoise(g, size, octaves, alpha) {  // smooth noise: random small canvases scaled up
  for (let o = 0; o < octaves; o++) {
    const n = 4 << o, s = cnv(n), sg = s.getContext('2d'), id = sg.createImageData(n, n);
    for (let i = 0; i < n * n; i++) { const v = Math.random() * 255; id.data[i * 4] = id.data[i * 4 + 1] = id.data[i * 4 + 2] = v; id.data[i * 4 + 3] = 255; }
    sg.putImageData(id, 0, 0); g.globalAlpha = alpha / (o + 1); g.imageSmoothingEnabled = true; g.drawImage(s, 0, 0, size, size);
  }
  g.globalAlpha = 1;
}
function normalFromHeight(hc, strength = 2.5) {
  const w = hc.width, h = hc.height, src = hc.getContext('2d').getImageData(0, 0, w, h).data, out = cnv(w, h), og = out.getContext('2d'), od = og.createImageData(w, h);
  const H = (x, y) => src[(((y + h) % h) * w + ((x + w) % w)) * 4] / 255;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const dx = (H(x + 1, y) - H(x - 1, y)) * strength, dy = (H(x, y + 1) - H(x, y - 1)) * strength;
    const l = Math.hypot(dx, dy, 1), i = (y * w + x) * 4;
    od.data[i] = (-dx / l * .5 + .5) * 255; od.data[i + 1] = (dy / l * .5 + .5) * 255; od.data[i + 2] = (1 / l * .5 + .5) * 255; od.data[i + 3] = 255;
  }
  og.putImageData(od, 0, 0); return out;
}
function texPair(color, height, repeat = true) {
  const map = new THREE.CanvasTexture(color); map.colorSpace = THREE.SRGBColorSpace;
  const nm = new THREE.CanvasTexture(normalFromHeight(height));
  for (const t of [map, nm]) { if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; } t.anisotropy = 8; }
  return { map, nm };
}
function makeWall() {
  const S = 512, c = cnv(S), g = c.getContext('2d'), h = cnv(S), hg = h.getContext('2d');
  g.fillStyle = '#4c525d'; g.fillRect(0, 0, S, S); valueNoise(g, S, 6, .35);
  g.globalCompositeOperation = 'multiply'; g.fillStyle = '#9aa4b8'; g.fillRect(0, 0, S, S); g.globalCompositeOperation = 'source-over';
  hg.fillStyle = '#888'; hg.fillRect(0, 0, S, S); valueNoise(hg, S, 6, .25);
  // grime gradient toward the floor
  const gr = g.createLinearGradient(0, S * .62, 0, S); gr.addColorStop(0, 'rgba(10,8,6,0)'); gr.addColorStop(1, 'rgba(10,8,6,.6)'); g.fillStyle = gr; g.fillRect(0, 0, S, S);
  // panel seams + kick plate
  for (const [x, y, w, hh] of [[0, 0, S, 6], [0, S / 2 - 3, S, 6], [S / 2 - 3, 0, 6, S / 2], [0, S * .82, S, 5]]) {
    g.fillStyle = 'rgba(8,10,14,.85)'; g.fillRect(x, y, w, hh); hg.fillStyle = '#222'; hg.fillRect(x, y, w, hh);
    g.fillStyle = 'rgba(200,215,235,.10)'; g.fillRect(x, y + hh, w, 2);
  }
  g.fillStyle = 'rgba(20,24,30,.55)'; g.fillRect(0, S * .82 + 5, S, S); hg.fillStyle = '#9a9a9a'; hg.fillRect(0, S * .82 + 5, S, S);
  // hazard stripe on the kick plate
  g.save(); g.beginPath(); g.rect(0, S * .9, S, 22); g.clip();
  for (let k = -2; k < 40; k++) { g.fillStyle = k % 2 ? 'rgba(180,140,20,.55)' : 'rgba(15,15,18,.6)'; g.beginPath(); g.moveTo(k * 24, S * .9); g.lineTo(k * 24 + 24, S * .9); g.lineTo(k * 24, S * .9 + 22); g.lineTo(k * 24 - 24, S * .9 + 22); g.fill(); }
  g.restore();
  // streaks and bolts
  for (let i = 0; i < 26; i++) { const x = Math.random() * S, y = Math.random() * S * .5; g.fillStyle = `rgba(20,16,12,${rnd(.08, .22)})`; g.fillRect(x, y, rnd(1, 3), rnd(30, 160)); }
  for (const [x, y] of [[18, 18], [S - 22, 18], [18, S / 2 - 18], [S - 22, S / 2 - 18], [S / 2 - 18, 18], [S / 2 + 14, 18]]) {
    g.fillStyle = '#272b33'; g.beginPath(); g.arc(x, y, 5, 0, 7); g.fill(); g.fillStyle = 'rgba(220,230,255,.25)'; g.beginPath(); g.arc(x - 1, y - 1, 2, 0, 7); g.fill();
    hg.fillStyle = '#fff'; hg.beginPath(); hg.arc(x, y, 5, 0, 7); hg.fill();
  }
  return texPair(c, h);
}
function makeFloor() {
  const S = 512, c = cnv(S), g = c.getContext('2d'), h = cnv(S), hg = h.getContext('2d');
  g.fillStyle = '#3a3e45'; g.fillRect(0, 0, S, S); valueNoise(g, S, 6, .3);
  hg.fillStyle = '#777'; hg.fillRect(0, 0, S, S);
  for (let ty = 0; ty < 2; ty++) for (let tx = 0; tx < 2; tx++) {
    const x = tx * S / 2, y = ty * S / 2, s = S / 2;
    g.fillStyle = 'rgba(0,0,0,.55)'; g.fillRect(x, y, s, 4); g.fillRect(x, y, 4, s);
    g.fillStyle = 'rgba(255,255,255,.08)'; g.fillRect(x + 4, y + 4, s - 8, 2);
    hg.fillStyle = '#333'; hg.fillRect(x, y, s, 5); hg.fillRect(x, y, 5, s);
    for (let yy = 14; yy < s - 8; yy += 22) for (let xx = 14 + ((yy / 22) % 2) * 11; xx < s - 8; xx += 22) {  // tread
      hg.save(); hg.translate(x + xx, y + yy); hg.rotate((tx + ty) % 2 ? .7 : -.7); hg.fillStyle = '#bbb'; hg.fillRect(-7, -2, 14, 4); hg.restore();
      g.save(); g.translate(x + xx, y + yy); g.rotate((tx + ty) % 2 ? .7 : -.7); g.fillStyle = 'rgba(190,200,215,.10)'; g.fillRect(-7, -2, 14, 4); g.restore();
    }
  }
  for (let i = 0; i < 40; i++) { g.strokeStyle = `rgba(210,220,235,${rnd(.04, .12)})`; g.lineWidth = rnd(.5, 1.5); g.beginPath(); const x = rnd(0, S), y = rnd(0, S); g.moveTo(x, y); g.lineTo(x + rnd(-60, 60), y + rnd(-20, 20)); g.stroke(); }
  for (let i = 0; i < 8; i++) { const x = rnd(0, S), y = rnd(0, S), r = rnd(10, 40), gr = g.createRadialGradient(x, y, 0, x, y, r); gr.addColorStop(0, 'rgba(90,50,20,.35)'); gr.addColorStop(1, 'rgba(90,50,20,0)'); g.fillStyle = gr; g.fillRect(x - r, y - r, 2 * r, 2 * r); }
  return texPair(c, h);
}
function makeCeil() {
  const S = 256, c = cnv(S), g = c.getContext('2d'), h = cnv(S), hg = h.getContext('2d');
  g.fillStyle = '#23262c'; g.fillRect(0, 0, S, S); valueNoise(g, S, 5, .2); hg.fillStyle = '#888'; hg.fillRect(0, 0, S, S);
  g.fillStyle = 'rgba(0,0,0,.6)'; g.fillRect(0, 0, S, 4); g.fillRect(0, 0, 4, S); hg.fillStyle = '#222'; hg.fillRect(0, 0, S, 4); hg.fillRect(0, 0, 4, S);
  for (let i = 0; i < 6; i++) { g.fillStyle = 'rgba(0,0,0,.45)'; g.fillRect(70, 60 + i * 22, 116, 8); hg.fillStyle = '#333'; hg.fillRect(70, 60 + i * 22, 116, 8); }
  return texPair(c, h);
}
function makeDoorTex() {
  const S = 256, c = cnv(S), g = c.getContext('2d'), h = cnv(S), hg = h.getContext('2d');
  g.fillStyle = '#2b2f37'; g.fillRect(0, 0, S, S); valueNoise(g, S, 5, .25); hg.fillStyle = '#999'; hg.fillRect(0, 0, S, S);
  g.save(); g.beginPath(); g.rect(0, S * .42, S, S * .16); g.clip();
  for (let k = -4; k < 20; k++) { g.fillStyle = k % 2 ? '#c99a1a' : '#15161a'; g.beginPath(); g.moveTo(k * 24, S * .42); g.lineTo(k * 24 + 24, S * .42); g.lineTo(k * 24 - 16, S * .58); g.lineTo(k * 24 - 40, S * .58); g.fill(); }
  g.restore();
  for (const y of [S * .12, S * .88]) { g.fillStyle = 'rgba(0,0,0,.5)'; g.fillRect(0, y, S, 6); hg.fillStyle = '#333'; hg.fillRect(0, y, S, 6); }
  return texPair(c, h, false);
}
function spriteTex(kind) {
  const c = cnv(64), g = c.getContext('2d');
  if (kind === 'dot') { const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32); gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(.3, 'rgba(255,255,255,.8)'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); }
  if (kind === 'flash') { g.translate(32, 32); for (let i = 0; i < 6; i++) { g.rotate(Math.PI / 3); const gr = g.createLinearGradient(0, 0, 30, 0); gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.beginPath(); g.moveTo(0, -3); g.lineTo(30, 0); g.lineTo(0, 3); g.fill(); } const gr = g.createRadialGradient(0, 0, 0, 0, 0, 14); gr.addColorStop(0, '#fff'); gr.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = gr; g.beginPath(); g.arc(0, 0, 14, 0, 7); g.fill(); }
  if (kind === 'scorch') { const gr = g.createRadialGradient(32, 32, 0, 32, 32, 32); gr.addColorStop(0, 'rgba(0,0,0,.85)'); gr.addColorStop(.6, 'rgba(10,6,4,.5)'); gr.addColorStop(1, 'rgba(0,0,0,0)'); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); }
  if (kind === 'ring') { g.strokeStyle = '#fff'; g.lineWidth = 4; g.beginPath(); g.arc(32, 32, 26, 0, 7); g.stroke(); g.lineWidth = 2; g.beginPath(); g.arc(32, 32, 16, 0, 7); g.stroke(); }
  if (kind === 'cross') { g.fillStyle = '#f2fff8'; g.fillRect(0, 0, 64, 64); g.fillStyle = '#18c46c'; g.fillRect(26, 10, 12, 44); g.fillRect(10, 26, 44, 12); }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

// =================================================================== renderer, scene, post
const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.15;
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x05070c); scene.fog = new THREE.FogExp2(0x05070c, .042);
const camera = new THREE.PerspectiveCamera(74, innerWidth / innerHeight, .03, 140);
camera.rotation.order = 'YXZ'; scene.add(camera);
const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
const bloom = new UnrealBloomPass(new THREE.Vector2(innerWidth, innerHeight), .75, .5, .82);
composer.addPass(bloom); composer.addPass(new OutputPass());
addEventListener('resize', () => {
  camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix();
  renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight);
});

// lights: ambient, flashlight (shadows), pooled ceiling lights, effect lights
scene.add(new THREE.HemisphereLight(0x8090b8, 0x101114, .55));
const torch = new THREE.SpotLight(0xe8eeff, 34, 42, .5, .6, 1.25);
torch.castShadow = true; torch.shadow.mapSize.set(1024, 1024); torch.shadow.bias = -.0004; torch.shadow.camera.near = .3; torch.shadow.camera.far = 40;
camera.add(torch); torch.position.set(.05, -.05, -.75); camera.add(torch.target); torch.target.position.set(0, -.08, -2);
const pool = [0, 1, 2, 3].map(() => { const l = new THREE.PointLight(0xc4d6ff, 0, 14, 1.7); scene.add(l); return l; });
const muzzleL = new THREE.PointLight(0x9ff8ff, 0, 10, 2); camera.add(muzzleL); muzzleL.position.set(.2, -.1, -.9);
const boomL = [0, 1].map(() => { const l = new THREE.PointLight(0xffa040, 0, 22, 1.6); scene.add(l); return l; });
const portalL = new THREE.PointLight(0x3df2ff, 0, 16, 1.6); scene.add(portalL);
const alarmL = new THREE.PointLight(0xff2a4a, 0, 9, 1.8); scene.add(alarmL);

// shared materials / textures
const TX = { wall: makeWall(), floor: makeFloor(), ceil: makeCeil(), door: makeDoorTex(),
             dot: spriteTex('dot'), flash: spriteTex('flash'), scorch: spriteTex('scorch'), ring: spriteTex('ring'), cross: spriteTex('cross') };
const MAT = {
  wall: new THREE.MeshStandardMaterial({ map: TX.wall.map, normalMap: TX.wall.nm, normalScale: new THREE.Vector2(1.2, 1.2), roughness: .82, metalness: .15 }),
  floor: new THREE.MeshStandardMaterial({ map: TX.floor.map, normalMap: TX.floor.nm, roughness: .55, metalness: .55 }),
  ceil: new THREE.MeshStandardMaterial({ map: TX.ceil.map, normalMap: TX.ceil.nm, roughness: .9, metalness: .2 }),
  door: new THREE.MeshStandardMaterial({ map: TX.door.map, normalMap: TX.door.nm, roughness: .5, metalness: .6 }),
  metal: new THREE.MeshStandardMaterial({ color: 0x1b1f28, roughness: .35, metalness: .9 }),
  metal2: new THREE.MeshStandardMaterial({ color: 0x3a4152, roughness: .4, metalness: .85 }),
  panel: new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0xd8e6ff, emissiveIntensity: 2.2 }),
  red: new THREE.MeshStandardMaterial({ color: 0x220008, emissive: 0xff2a4a, emissiveIntensity: 4 }),
  amber: new THREE.MeshStandardMaterial({ color: 0x221400, emissive: 0xff9a2a, emissiveIntensity: 3 }),
  cyan: new THREE.MeshStandardMaterial({ color: 0x002226, emissive: 0x3df2ff, emissiveIntensity: 3 }),
  magenta: new THREE.MeshStandardMaterial({ color: 0x220022, emissive: 0xff3df0, emissiveIntensity: 2.6 }),
  gold: new THREE.MeshStandardMaterial({ color: 0x332200, emissive: 0xffc23d, emissiveIntensity: 1.4, metalness: .8, roughness: .3 }),
  green: new THREE.MeshStandardMaterial({ color: 0x002210, emissive: 0x3dff9a, emissiveIntensity: 3 }),
  med: new THREE.MeshStandardMaterial({ map: TX.cross, roughness: .5, emissive: 0x0a4a28, emissiveIntensity: .6 }),
  bolt: new THREE.MeshBasicMaterial({ color: 0xff6a3d }),
};
const GEO = {
  wall: new THREE.BoxGeometry(TS, WH, TS), panel: new THREE.BoxGeometry(1.5, .06, .5),
  droneBody: new THREE.SphereGeometry(.42, 24, 16), droneRing: new THREE.TorusGeometry(.62, .05, 8, 32), droneEye: new THREE.SphereGeometry(.13, 16, 12),
  rotor: new THREE.BoxGeometry(.32, .05, .1), mine: new THREE.CylinderGeometry(.36, .42, .14, 16), mineTop: new THREE.SphereGeometry(.09, 12, 8),
  med: new THREE.BoxGeometry(.55, .36, .36), core: new THREE.OctahedronGeometry(.26), key: new THREE.BoxGeometry(.5, .03, .32),
  bolt: new THREE.SphereGeometry(.11, 10, 8), portalRing: new THREE.TorusGeometry(1.0, .06, 10, 48), portalRing2: new THREE.TorusGeometry(.72, .04, 8, 40),
};

// particles: additive points pool
class Particles {
  constructor(n, size) {
    this.n = n; this.i = 0;
    this.pos = new Float32Array(n * 3).fill(-999); this.col = new Float32Array(n * 3); this.base = new Float32Array(n * 3);
    this.vel = new Float32Array(n * 3); this.life = new Float32Array(n); this.max = new Float32Array(n); this.grav = new Float32Array(n);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3)); g.setAttribute('color', new THREE.BufferAttribute(this.col, 3));
    this.mesh = new THREE.Points(g, new THREE.PointsMaterial({ size, map: TX.dot, vertexColors: true, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, sizeAttenuation: true }));
    this.mesh.frustumCulled = false; scene.add(this.mesh);
  }
  spawn(x, y, z, vx, vy, vz, color, life, grav = 9) {
    const i = this.i = (this.i + 1) % this.n, c = new THREE.Color(color);
    this.pos.set([x, y, z], i * 3); this.vel.set([vx, vy, vz], i * 3); this.base.set([c.r, c.g, c.b], i * 3);
    this.life[i] = this.max[i] = life; this.grav[i] = grav;
  }
  burst(x, y, z, color, n, speed, life, grav = 9) {
    for (let k = 0; k < n; k++) {
      const u = Math.random() * 2 - 1, a = Math.random() * 6.283, s = Math.sqrt(1 - u * u), sp = rnd(.3, 1) * speed;
      this.spawn(x, y, z, Math.cos(a) * s * sp, u * sp + speed * .2, Math.sin(a) * s * sp, color, rnd(.5, 1) * life, grav);
    }
  }
  update(dt) {
    for (let i = 0; i < this.n; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt; const j = i * 3;
      if (this.life[i] <= 0) { this.pos[j + 1] = -999; continue; }
      this.vel[j + 1] -= this.grav[i] * dt;
      const dr = Math.exp(-2 * dt); this.vel[j] *= dr; this.vel[j + 2] *= dr;
      this.pos[j] += this.vel[j] * dt; this.pos[j + 1] += this.vel[j + 1] * dt; this.pos[j + 2] += this.vel[j + 2] * dt;
      if (this.pos[j + 1] < .02) { this.pos[j + 1] = .02; this.vel[j + 1] *= -.35; }
      const f = this.life[i] / this.max[i];
      this.col[j] = this.base[j] * f; this.col[j + 1] = this.base[j + 1] * f; this.col[j + 2] = this.base[j + 2] * f;
    }
    this.mesh.geometry.attributes.position.needsUpdate = true; this.mesh.geometry.attributes.color.needsUpdate = true;
  }
}
const sparks = new Particles(1400, .09), embers = new Particles(500, .3);

// weapon viewmodel (attached to the camera, never casts shadows)
const gun = new THREE.Group(); camera.add(gun);
(() => {
  const add = (geo, mat, x, y, z, rx = 0) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.rotation.x = rx; m.castShadow = false; gun.add(m); return m; };
  add(new THREE.BoxGeometry(.085, .1, .38), MAT.metal, 0, 0, 0);
  add(new THREE.BoxGeometry(.06, .05, .2), MAT.metal2, 0, .07, -.02);
  add(new THREE.CylinderGeometry(.022, .026, .26, 12), MAT.metal2, 0, .01, -.3, Math.PI / 2);
  add(new THREE.BoxGeometry(.088, .012, .26), new THREE.MeshStandardMaterial({ color: 0x002226, emissive: 0x3df2ff, emissiveIntensity: .7 }), 0, -.02, -.02);
  add(new THREE.BoxGeometry(.05, .14, .07), MAT.metal, 0, -.1, .07, .25);
  add(new THREE.BoxGeometry(.012, .012, .03), new THREE.MeshStandardMaterial({ color: 0x220008, emissive: 0xff2a4a, emissiveIntensity: .5 }), 0, .1, -.06);
})();
gun.position.set(.22, -.22, -.42); gun.scale.setScalar(.8);
const flashSprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: TX.flash, color: 0xbff9ff, blending: THREE.AdditiveBlending, depthWrite: false, transparent: true }));
flashSprite.scale.set(.2, .2, 1); flashSprite.material.opacity = .85; flashSprite.position.set(0, .01, -.47); flashSprite.visible = false; gun.add(flashSprite);

// =================================================================== level construction
let L = null, P = null, world = null;
function solidAt(c, r) {
  if (!L || r < 0 || c < 0 || r >= L.rows || c >= L.cols) return true;
  if (L.grid[r][c] === '#') return true;
  const d = L.doors[r * L.cols + c]; return d ? d.y < WH - .6 : false;
}
const center = (r, c) => ({ x: (c + .5) * TS, z: (r + .5) * TS });
function disposeWorld() {
  if (!world) return;
  world.traverse(o => { if (o.geometry && !Object.values(GEO).includes(o.geometry)) o.geometry.dispose(); });
  scene.remove(world); world = null;
}
function buildLevel(i) {
  disposeWorld(); world = new THREE.Group(); scene.add(world);
  const def = GD.levels[i], grid = def.grid.map(r => r.split('')), rows = grid.length, cols = grid[0].length;
  L = { i, def, grid, rows, cols, drones: [], mines: [], items: [], doors: {}, exit: null, start: null, bolts: [], tracers: [], fixtures: [], decals: [],
        explored: new Uint8Array(rows * cols), time: 0, kills: 0, dmg: 0, cores: 0, coresTotal: 0, keyNeeded: false, hasKey: false,
        flow: null, flowTile: -1, toastT: 0, doorHint: 0, done: false, deadT: 0, clearT: 0, t: 0, poolT: 0 };
  const isWall = (r, c) => r < 0 || c < 0 || r >= rows || c >= cols || grid[r][c] === '#';
  // floor and ceiling
  const fl = new THREE.Mesh(new THREE.PlaneGeometry(cols * TS, rows * TS), MAT.floor);
  fl.rotation.x = -Math.PI / 2; fl.position.set(cols * TS / 2, 0, rows * TS / 2); fl.receiveShadow = true; world.add(fl);
  TX.floor.map.repeat.set(cols, rows); TX.floor.nm.repeat.set(cols, rows);
  const ce = new THREE.Mesh(new THREE.PlaneGeometry(cols * TS, rows * TS), MAT.ceil);
  ce.rotation.x = Math.PI / 2; ce.position.set(cols * TS / 2, WH, rows * TS / 2); world.add(ce);
  TX.ceil.map.repeat.set(cols, rows); TX.ceil.nm.repeat.set(cols, rows);
  // walls: one instanced mesh for every wall tile that touches open space
  const wallTiles = [];
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++)
    if (isWall(r, c) && (!isWall(r - 1, c) || !isWall(r + 1, c) || !isWall(r, c - 1) || !isWall(r, c + 1) || !isWall(r - 1, c - 1) || !isWall(r + 1, c + 1) || !isWall(r - 1, c + 1) || !isWall(r + 1, c - 1))) wallTiles.push([r, c]);
  const walls = new THREE.InstancedMesh(GEO.wall, MAT.wall, wallTiles.length), m4 = new THREE.Matrix4();
  wallTiles.forEach(([r, c], k) => { m4.makeTranslation((c + .5) * TS, WH / 2, (r + .5) * TS); walls.setMatrixAt(k, m4); });
  walls.castShadow = walls.receiveShadow = true; world.add(walls);
  // entities
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    const ch = grid[r][c], p = center(r, c);
    if (ch === 'S') L.start = p;
    else if (ch === 'E') L.exit = makePortal(p);
    else if (ch === 'M') L.drones.push(makeDrone(p));
    else if (ch === 'T') L.mines.push(makeMine(p));
    else if (ch === 'H') L.items.push(makeItem(p, 'med'));
    else if (ch === 'C') { L.items.push(makeItem(p, 'core')); L.coresTotal++; }
    else if (ch === 'K') { L.items.push(makeItem(p, 'key')); L.keyNeeded = true; }
    if (ch === 'D') L.doors[r * cols + c] = makeDoor(r, c, isWall(r, c - 1) && isWall(r, c + 1));
    else if (ch !== '#') grid[r][c] = '.';
  }
  // ceiling light fixtures (emissive panels; four real lights follow the player)
  for (let r = 1; r < rows - 1; r++) for (let c = 1; c < cols - 1; c++) {
    if (isWall(r, c) || hash(r * 7, c * 3) > .2) continue;
    if (L.fixtures.some(f => Math.abs(f.r - r) + Math.abs(f.c - c) < 3)) continue;
    const p = center(r, c), m = new THREE.Mesh(GEO.panel, MAT.panel); m.position.set(p.x, WH - .03, p.z); world.add(m);
    L.fixtures.push({ r, c, x: p.x, z: p.z, flicker: hash(r, c) > .7 });
  }
  L.start = L.start || center(1, 1);
  // spawn ring decal
  const ring = new THREE.Mesh(new THREE.PlaneGeometry(2.2, 2.2), new THREE.MeshBasicMaterial({ map: TX.ring, color: 0xff3df0, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
  ring.rotation.x = -Math.PI / 2; ring.position.set(L.start.x, .02, L.start.z); world.add(ring);
  // player
  P = { x: L.start.x, z: L.start.z, vx: 0, vz: 0, r: .55, yaw: 0, pitch: 0, hp: R.START_HP, max: R.MAX_HP, ammo: MAG, reload: 0, fire: 0,
        dashCd: 0, dashT: 0, dx: 0, dz: 0, inv: 0, bob: 0, kick: 0, dead: false, stepT: 0, shake: 0 };
  // face the most open direction from the start
  let best = 0, bestYaw = 0;
  for (const [dr, dc, yaw] of [[-1, 0, 0], [1, 0, Math.PI], [0, -1, Math.PI / 2], [0, 1, -Math.PI / 2]]) {
    let n = 0; const sr = Math.floor(P.z / TS), sc = Math.floor(P.x / TS);
    while (!isWall(sr + dr * (n + 1), sc + dc * (n + 1)) && n < 20) n++;
    if (n > best) { best = n; bestYaw = yaw; }
  }
  P.yaw = bestYaw;
  $('minic').width = cols * 7; $('minic').height = rows * 7;
  if (L.exit) { portalL.position.set(L.exit.x, 1.6, L.exit.z); portalL.intensity = 30; } else portalL.intensity = 0;
}
function makeDrone(p) {
  const g = new THREE.Group(), body = new THREE.Mesh(GEO.droneBody, MAT.metal.clone()), ring = new THREE.Mesh(GEO.droneRing, MAT.metal2),
    eye = new THREE.Mesh(GEO.droneEye, MAT.amber.clone());
  body.castShadow = true; ring.castShadow = true; ring.rotation.x = Math.PI / 2; eye.position.set(0, 0, -.36);
  g.add(body, ring, eye);
  for (let k = 0; k < 4; k++) { const rt = new THREE.Mesh(GEO.rotor, MAT.metal2); const a = k * Math.PI / 2; rt.position.set(Math.cos(a) * .62, .06, Math.sin(a) * .62); ring.add(rt); }
  g.position.set(p.x, 1.7, p.z); world.add(g);
  return { ...p, hx: p.x, hz: p.z, vx: 0, vz: 0, r: .55, hp: R.MONSTER_HP, max: R.MONSTER_HP, alert: false, lost: 0, fire: rnd(.8, 1.6),
           strafe: Math.random() < .5 ? 1 : -1, touch: 0, flash: 0, t: Math.random() * 6, g, body, ring, eye, y: 1.7 };
}
function makeMine(p) {
  const g = new THREE.Group(), base = new THREE.Mesh(GEO.mine, MAT.metal), top = new THREE.Mesh(GEO.mineTop, MAT.red.clone());
  base.position.y = .07; top.position.y = .16; base.castShadow = true; g.add(base, top); g.position.set(p.x, 0, p.z); world.add(g);
  return { ...p, trig: -1, beep: 0, t: Math.random() * 6, g, top, gone: false };
}
function makeItem(p, kind) {
  const geo = kind === 'med' ? GEO.med : kind === 'core' ? GEO.core : GEO.key, mat = kind === 'med' ? MAT.med : kind === 'core' ? MAT.gold : MAT.magenta;
  const m = new THREE.Mesh(geo, mat); m.position.set(p.x, .6, p.z); m.castShadow = true; world.add(m);
  return { ...p, kind, m, t: Math.random() * 6, taken: false };
}
function makeDoor(r, c, horiz) {
  const p = center(r, c), m = new THREE.Mesh(new THREE.BoxGeometry(horiz ? TS : .45, WH, horiz ? .45 : TS), MAT.door);
  m.position.set(p.x, WH / 2, p.z); m.castShadow = m.receiveShadow = true; world.add(m);
  const lamp = new THREE.Mesh(new THREE.BoxGeometry(horiz ? .3 : .5, .12, horiz ? .5 : .3), MAT.red.clone()); lamp.position.set(p.x, WH - .3, p.z); world.add(lamp);
  return { r, c, ...p, m, lamp, y: 0, open: false };
}
function makePortal(p) {
  const g = new THREE.Group(), r1 = new THREE.Mesh(GEO.portalRing, MAT.cyan), r2 = new THREE.Mesh(GEO.portalRing2, MAT.magenta), r3 = new THREE.Mesh(GEO.portalRing2, MAT.cyan);
  r3.scale.setScalar(.6); g.add(r1, r2, r3); g.position.set(p.x, 1.5, p.z); world.add(g);
  const pad = new THREE.Mesh(new THREE.PlaneGeometry(3, 3), new THREE.MeshBasicMaterial({ map: TX.ring, color: 0x3df2ff, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
  pad.rotation.x = -Math.PI / 2; pad.position.set(p.x, .02, p.z); world.add(pad);
  return { ...p, g, r1, r2, r3 };
}

// =================================================================== physics helpers
function collide(e) {
  for (let pass = 0; pass < 2; pass++) {
    const c0 = Math.floor((e.x - e.r) / TS), c1 = Math.floor((e.x + e.r) / TS), r0 = Math.floor((e.z - e.r) / TS), r1 = Math.floor((e.z + e.r) / TS);
    for (let r = r0; r <= r1; r++) for (let c = c0; c <= c1; c++) {
      if (!solidAt(c, r)) continue;
      const nx = clamp(e.x, c * TS, (c + 1) * TS), nz = clamp(e.z, r * TS, (r + 1) * TS);
      let dx = e.x - nx, dz = e.z - nz; const d = Math.hypot(dx, dz);
      if (d === 0) { const cx = (c + .5) * TS, cz = (r + .5) * TS; dx = e.x - cx; dz = e.z - cz;
        if (Math.abs(dx) > Math.abs(dz)) e.x = dx > 0 ? (c + 1) * TS + e.r : c * TS - e.r; else e.z = dz > 0 ? (r + 1) * TS + e.r : r * TS - e.r; continue; }
      if (d < e.r) { e.x += dx / d * (e.r - d); e.z += dz / d * (e.r - d); }
    }
  }
}
function los(x0, z0, x1, z1) {
  const d = Math.hypot(x1 - x0, z1 - z0), n = Math.ceil(d / .4);
  for (let i = 1; i < n; i++) if (solidAt(Math.floor((x0 + (x1 - x0) * i / n) / TS), Math.floor((z0 + (z1 - z0) * i / n) / TS))) return false;
  return true;
}
function rayWall(o, d, maxT = 70) {  // first wall / floor / ceiling hit along a ray
  for (let t = .1; t < maxT; t += .06) {
    const x = o.x + d.x * t, y = o.y + d.y * t, z = o.z + d.z * t;
    if (y <= 0 || y >= WH || solidAt(Math.floor(x / TS), Math.floor(z / TS))) return t;
  }
  return maxT;
}
function raySphere(o, d, cx, cy, cz, rad) {
  const ox = o.x - cx, oy = o.y - cy, oz = o.z - cz, b = ox * d.x + oy * d.y + oz * d.z, c = ox * ox + oy * oy + oz * oz - rad * rad, h = b * b - c;
  if (h < 0) return Infinity; const t = -b - Math.sqrt(h); return t > 0 ? t : Infinity;
}
function updateFlow() {
  const pc = Math.floor(P.x / TS), pr = Math.floor(P.z / TS), id = pr * L.cols + pc;
  if (id === L.flowTile && L.flow) return; L.flowTile = id;
  const dist = new Int16Array(L.rows * L.cols).fill(-1), q = [id]; dist[id] = 0;
  for (let h = 0; h < q.length; h++) {
    const cur = q[h], r = Math.floor(cur / L.cols), c = cur % L.cols;
    for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const nr = r + dr, nc = c + dc; if (solidAt(nc, nr)) continue; const ni = nr * L.cols + nc; if (dist[ni] >= 0) continue; dist[ni] = dist[cur] + 1; q.push(ni); }
  }
  L.flow = dist;
}
function flowTarget(e) {
  const c = Math.floor(e.x / TS), r = Math.floor(e.z / TS), d0 = L.flow[r * L.cols + c]; let best = null, bd = d0 < 0 ? 1e9 : d0;
  for (const [dr, dc] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) { const nr = r + dr, nc = c + dc; if (solidAt(nc, nr)) continue; const v = L.flow[nr * L.cols + nc]; if (v >= 0 && v < bd) { bd = v; best = center(nr, nc); } }
  return best;
}

// =================================================================== effects
let boomIdx = 0;
function flashLight(x, y, z, intensity, color = 0xffa040) { const l = boomL[boomIdx = (boomIdx + 1) % boomL.length]; l.position.set(x, y, z); l.color.set(color); l.intensity = intensity; }
function toast(t) { $('toast').textContent = t; $('toast').style.opacity = 1; L.toastT = 2.2; }
function scorch(x, z, s) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(s, s), new THREE.MeshBasicMaterial({ map: TX.scorch, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 }));
  m.rotation.x = -Math.PI / 2; m.rotation.z = Math.random() * 6; m.position.set(x, .015, z); world.add(m);
}
function explode(x, y, z, dmg, rad, big) {
  SFX.boom(x, z, big); P.shake = Math.min(1, P.shake + (big ? .8 : .5) * clamp(1 - Math.hypot(P.x - x, P.z - z) / 25, 0, 1));
  sparks.burst(x, y, z, 0xffb040, big ? 140 : 90, big ? 11 : 8, .9); sparks.burst(x, y, z, 0xff3d3d, 40, 7, .6);
  embers.burst(x, y, z, 0xff7a20, 26, 3, 1.4, 1.5); flashLight(x, y + .5, z, big ? 160 : 90);
  scorch(x, z, rad * 1.1);
  if (dmg) {
    if (!P.dead && Math.hypot(P.x - x, P.z - z) < rad) hurtPlayer(dmg, x, z);
    for (const d of L.drones) if (d.hp > 0 && Math.hypot(d.x - x, d.z - z) < rad) damageDrone(d, dmg);
  }
}
function hurtPlayer(n, sx, sz) {
  if (P.inv > 0 || P.dead || L.done) return;
  P.hp -= n; L.dmg += n; P.inv = .5; P.shake = Math.min(1, P.shake + .45); SFX.hurt();
  $('hurt').style.opacity = 1; setTimeout(() => $('hurt').style.opacity = 0, 200);
  if (sx !== undefined) {
    const rel = Math.atan2(-(sx - P.x), -(sz - P.z)) - P.yaw;
    $('dmgdir').style.transform = `rotate(${-rel}rad)`; $('dmgdir').style.opacity = 1; clearTimeout(hurtPlayer.t); hurtPlayer.t = setTimeout(() => $('dmgdir').style.opacity = 0, 600);
  }
  if (P.hp <= 0) { P.hp = 0; P.dead = true; L.deadT = 1.6; SFX.die(); }
}
function damageDrone(d, n) {
  d.hp -= n; d.flash = .1; d.alert = true; d.lost = 0; SFX.hit();
  $('hm').style.opacity = 1; setTimeout(() => $('hm').style.opacity = 0, 90);
  if (d.hp <= 0) {
    L.kills++; explode(d.x, d.y, d.z, 0, 3, false); sparks.burst(d.x, d.y, d.z, 0x3df2ff, 30, 6, .6);
    d.g.visible = false; hitstop = .05; toast('DRONE DOWN');
  }
}
function fire() {
  const dir = new THREE.Vector3(rnd(-.008, .008), rnd(-.008, .008), -1).normalize().applyQuaternion(camera.quaternion);
  const o = camera.position.clone();
  let best = rayWall(o, dir), hit = null, hitMine = null;
  for (const d of L.drones) if (d.hp > 0) { const t = raySphere(o, dir, d.x, d.y, d.z, .6); if (t < best) { best = t; hit = d; hitMine = null; } }
  for (const m of L.mines) if (!m.gone) { const t = raySphere(o, dir, m.x, .12, m.z, .45); if (t < best) { best = t; hitMine = m; hit = null; } }
  const hp = o.clone().addScaledVector(dir, best);
  // tracer from the muzzle
  const muzzle = new THREE.Vector3(); flashSprite.getWorldPosition(muzzle);
  const tg = new THREE.BufferGeometry().setFromPoints([muzzle, hp]);
  const tr = new THREE.Line(tg, new THREE.LineBasicMaterial({ color: 0x9ff8ff, transparent: true, opacity: .9, blending: THREE.AdditiveBlending }));
  world.add(tr); L.tracers.push({ m: tr, life: .05 });
  if (hit) { sparks.burst(hp.x, hp.y, hp.z, 0xffd23d, 14, 4, .35); damageDrone(hit, Math.random() < .5 ? 1 : 2); }
  else if (hitMine) { hitMine.gone = true; hitMine.g.visible = false; explode(hitMine.x, .2, hitMine.z, R.TRAP_DAMAGE, 4, true); toast('MINE CLEARED'); }
  else { sparks.burst(hp.x - dir.x * .05, hp.y - dir.y * .05, hp.z - dir.z * .05, 0x9ff8ff, 10, 3.5, .3); SFX.ric(); }
  P.ammo--; P.fire = .12; P.kick = 1; SFX.shoot(); muzzleL.intensity = 6; flashSprite.visible = true; flashSprite.material.rotation = Math.random() * 6;
  P.pitch += .006; $('xh').classList.add('fire'); setTimeout(() => $('xh').classList.remove('fire'), 80);
  if (P.ammo <= 0) startReload();
}
function startReload() { if (P.reload > 0 || P.ammo === MAG) return; P.reload = 1.0; SFX.reload(); }

// =================================================================== input
const keys = {}; let dashPressed = false, locked = false;
addEventListener('keydown', e => {
  const k = e.key.toLowerCase(); audioInit();
  if (k === ' ' && !keys[' ']) dashPressed = true;
  keys[k] = true; if ([' ', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright'].includes(k)) e.preventDefault();
  onKey(k);
});
addEventListener('keyup', e => { keys[e.key.toLowerCase()] = false; });
let mouseDown = false;
canvas.addEventListener('mousedown', e => {
  audioInit();
  if (S === 'play' && !locked) { canvas.requestPointerLock && canvas.requestPointerLock(); return; }
  if (e.button === 0) mouseDown = true;
});
addEventListener('mouseup', () => { mouseDown = false; });
addEventListener('mousemove', e => {
  if (!locked || S !== 'play') return;
  P.yaw -= e.movementX * .0022; P.pitch = clamp(P.pitch - e.movementY * .0022, -1.35, 1.35);
});
document.addEventListener('pointerlockchange', () => {
  locked = document.pointerLockElement === canvas;
  if (!locked && S === 'play') setState('pause');
});
addEventListener('blur', () => { mouseDown = false; for (const k in keys) keys[k] = false; });

// =================================================================== state machine
let S = 'menu', levelIdx = 0, campaign = false, results = [], deaths = GD.levels.map(() => 0), hitstop = 0, slowmo = 0;
function setState(s) {
  S = s;
  for (const id of ['menu', 'select', 'how', 'intro', 'pause', 'dead', 'clear', 'summary', 'lab']) $(id).classList.toggle('on', id === s);
  $('hud').classList.toggle('on', s === 'play' || s === 'intro');
  $('xh').classList.toggle('on', s === 'play');
  if (s !== 'play' && document.pointerLockElement) document.exitPointerLock();
}

// =================================================================== update
const fwd = new THREE.Vector3();
function update(dt) {
  L.t += dt; if (!P.dead && !L.done) L.time += dt;
  if (L.toastT > 0 && (L.toastT -= dt) <= 0) $('toast').style.opacity = 0;
  // ---- player
  if (!P.dead) {
    if (keys['arrowleft']) P.yaw += dt * 2.2; if (keys['arrowright']) P.yaw -= dt * 2.2;
    if (keys['arrowup']) P.pitch = clamp(P.pitch + dt * 1.2, -1.3, 1.3); if (keys['arrowdown']) P.pitch = clamp(P.pitch - dt * 1.2, -1.3, 1.3);
    const f = (keys['w'] ? 1 : 0) - (keys['s'] ? 1 : 0), st = (keys['d'] ? 1 : 0) - (keys['a'] ? 1 : 0);
    let mx = -Math.sin(P.yaw) * f + Math.cos(P.yaw) * st, mz = -Math.cos(P.yaw) * f - Math.sin(P.yaw) * st;
    const ml = Math.hypot(mx, mz); if (ml) { mx /= ml; mz /= ml; }
    P.dashCd -= dt; P.inv -= dt; P.fire -= dt;
    if (dashPressed && P.dashCd <= 0) { P.dashT = .18; P.dashCd = 1.2; P.dx = ml ? mx : -Math.sin(P.yaw); P.dz = ml ? mz : -Math.cos(P.yaw); P.inv = Math.max(P.inv, .25); SFX.dash(); }
    dashPressed = false;
    const speed = keys['shift'] ? 8.2 : 5.4;
    if (P.dashT > 0) { P.dashT -= dt; P.vx = P.dx * 18; P.vz = P.dz * 18; }
    else { const k = Math.min(1, dt * 10); P.vx += (mx * speed - P.vx) * k; P.vz += (mz * speed - P.vz) * k; }
    P.x += P.vx * dt; P.z += P.vz * dt; collide(P);
    const sp = Math.hypot(P.vx, P.vz); P.bob += dt * sp * 1.6;
    if (sp > 1) { P.stepT -= dt * sp / 5.4; if (P.stepT <= 0) { SFX.step(); P.stepT = .42; } }
    if (P.reload > 0) { P.reload -= dt; if (P.reload <= 0) { P.reload = 0; P.ammo = MAG; } }
    if (keys['r']) startReload();
    if ((mouseDown || keys['f']) && P.fire <= 0 && P.reload <= 0 && P.ammo > 0) fire();
    // explored cells for the minimap
    const pc = Math.floor(P.x / TS), pr = Math.floor(P.z / TS);
    for (let r = pr - 3; r <= pr + 3; r++) for (let c = pc - 3; c <= pc + 3; c++) if (r >= 0 && c >= 0 && r < L.rows && c < L.cols && (Math.abs(r - pr) + Math.abs(c - pc) <= 4)) L.explored[r * L.cols + c] = 1;
    // pickups
    for (const it of L.items) {
      if (it.taken) continue;
      it.t += dt; it.m.rotation.y += dt * 1.5; it.m.position.y = .6 + Math.sin(it.t * 2.5) * .08;
      if (Math.hypot(P.x - it.x, P.z - it.z) > 1.25) continue;
      it.taken = true; it.m.visible = false; sparks.burst(it.x, .6, it.z, it.kind === 'med' ? 0x3dff9a : it.kind === 'key' ? 0xff3df0 : 0xffd23d, 30, 3, .6, 2);
      if (it.kind === 'med') { const b = P.hp; P.hp = Math.min(P.max, P.hp + R.POTION_HEAL); SFX.heal(); toast(`+${P.hp - b} INTEGRITY`); }
      else if (it.kind === 'core') { L.cores++; SFX.pick(); toast(`DATA CORE ${L.cores}/${L.coresTotal}`); }
      else { L.hasKey = true; SFX.key(); toast('KEYCARD ACQUIRED'); }
    }
    // doors
    L.doorHint -= dt;
    for (const k in L.doors) {
      const d = L.doors[k];
      if (!d.open && Math.hypot(P.x - d.x, P.z - d.z) < 5) {
        if (L.hasKey) { d.open = true; SFX.door(); toast('BLAST DOOR OPENING'); d.lamp.material.emissive.set(0x3dff9a); P.shake = Math.min(1, P.shake + .3); }
        else if (L.doorHint <= 0) { toast('KEYCARD REQUIRED'); SFX.ui(); L.doorHint = 3; }
      }
      if (d.open && d.y < WH - .1) { d.y = Math.min(WH - .1, d.y + dt * 1.6); d.m.position.y = WH / 2 + d.y; if (d.y >= WH - .6) L.flowTile = -1; }
    }
    if (L.exit && !L.done && Math.hypot(P.x - L.exit.x, P.z - L.exit.z) < 1.4) {
      L.done = true; L.clearT = 1.4; slowmo = 1.4; SFX.win(); sparks.burst(L.exit.x, 1.5, L.exit.z, 0x3df2ff, 160, 7, 1.2, 1); flashLight(L.exit.x, 1.5, L.exit.z, 200, 0x3df2ff);
    }
  }
  updateFlow();
  // ---- drones
  for (const d of L.drones) {
    if (d.hp <= 0) continue;
    d.t += dt; d.flash -= dt; d.touch -= dt;
    const dx = P.x - d.x, dz = P.z - d.z, dist = Math.hypot(dx, dz) || 1;
    const sees = !P.dead && dist < TS * 7 && los(d.x, d.z, P.x, P.z);
    if (sees) { if (!d.alert) { d.alert = true; SFX.alert(d.x, d.z); d.eye.material.emissive.set(0xff2a4a); } d.lost = 0; } else d.lost += dt;
    let mx = 0, mz = 0;
    if (d.alert && !P.dead) {
      if (sees) {
        const want = TS * 2.6, k = dist > want + 2.5 ? 1 : dist < want - 2.5 ? -1 : 0;
        mx = dx / dist * k - dz / dist * .7 * d.strafe; mz = dz / dist * k + dx / dist * .7 * d.strafe;
        if (Math.random() < dt * .5) d.strafe *= -1;
        d.fire -= dt;
        if (d.fire <= 0 && !L.done) {
          const tx = P.x + rnd(-.5, .5), ty = EYE - .25 + rnd(-.2, .2), tz = P.z + rnd(-.5, .5);
          const v = new THREE.Vector3(tx - d.x, ty - d.y, tz - d.z).normalize().multiplyScalar(11);
          const m = new THREE.Mesh(GEO.bolt, MAT.bolt); m.position.set(d.x, d.y, d.z); world.add(m);
          L.bolts.push({ x: d.x, y: d.y, z: d.z, v, m, life: 3, dmg: Math.random() < .5 ? 1 : 2 });
          d.fire = rnd(1.1, 1.7); SFX.eshoot(d.x, d.z); alarmL.position.set(d.x, d.y, d.z); alarmL.intensity = 12;
        }
      } else {
        const t = flowTarget(d); if (t) { const l = Math.hypot(t.x - d.x, t.z - d.z) || 1; mx = (t.x - d.x) / l; mz = (t.z - d.z) / l; }
        if (d.lost > 10) { d.alert = false; d.eye.material.emissive.set(0xff9a2a); }
      }
    } else { mx = Math.cos(d.t * .6) * .3 + (d.hx - d.x) * .15; mz = Math.sin(d.t * .8) * .3 + (d.hz - d.z) * .15; }
    const spd = d.alert ? 3.6 : 1.2, k = Math.min(1, dt * 4);
    d.vx += (mx * spd - d.vx) * k; d.vz += (mz * spd - d.vz) * k;
    for (const o of L.drones) { if (o === d || o.hp <= 0) continue; const ox = d.x - o.x, oz = d.z - o.z, od = Math.hypot(ox, oz); if (od < 1.6 && od > 0) { d.vx += ox / od * 3 * dt * 10; d.vz += oz / od * 3 * dt * 10; } }
    d.x += d.vx * dt; d.z += d.vz * dt; collide(d);
    d.y = 1.75 + Math.sin(d.t * 2.2) * .12;
    d.g.position.set(d.x, d.y, d.z);
    d.g.rotation.y = Math.atan2(-(P.x - d.x), -(P.z - d.z)) * (d.alert ? 1 : 0) + (d.alert ? 0 : d.t * .4);
    d.ring.rotation.z += dt * (d.alert ? 9 : 3);
    d.body.material.emissive.set(d.flash > 0 ? 0xffffff : 0x000000); d.body.material.emissiveIntensity = d.flash > 0 ? 1.5 : 0;
    if (!P.dead && dist < 1.3 && d.touch <= 0) { d.touch = .8; if (Math.random() < R.LUNGE_CHANCE * 2.4) hurtPlayer(1, d.x, d.z); }
  }
  // ---- plasma bolts
  for (const b of L.bolts) {
    b.life -= dt; b.x += b.v.x * dt; b.y += b.v.y * dt; b.z += b.v.z * dt; b.m.position.set(b.x, b.y, b.z);
    if (Math.random() < .6) sparks.spawn(b.x, b.y, b.z, rnd(-.3, .3), rnd(-.3, .3), rnd(-.3, .3), 0xff5a2a, .25, 0);
    if (b.y < 0 || b.y > WH || solidAt(Math.floor(b.x / TS), Math.floor(b.z / TS))) { b.life = 0; sparks.burst(b.x, b.y, b.z, 0xff6a3d, 12, 3, .3); continue; }
    if (!P.dead && Math.hypot(P.x - b.x, P.z - b.z) < .55 && Math.abs(b.y - (EYE - .4)) < .9) { b.life = 0; hurtPlayer(b.dmg, b.x - b.v.x, b.z - b.v.z); }
  }
  for (const b of L.bolts) if (b.life <= 0) world.remove(b.m);
  L.bolts = L.bolts.filter(b => b.life > 0);
  // ---- mines
  for (const m of L.mines) {
    if (m.gone) continue; m.t += dt;
    if (m.trig < 0 && !P.dead && Math.hypot(P.x - m.x, P.z - m.z) < 2.2) { m.trig = .6; SFX.beep(m.x, m.z); }
    const blink = m.trig >= 0 ? Math.floor(m.t * 18) % 2 : Math.floor(m.t * 2) % 2;
    m.top.material.emissiveIntensity = blink ? 6 : .6;
    if (m.trig >= 0) { m.trig -= dt; m.beep -= dt; if (m.beep <= 0) { SFX.beep(m.x, m.z); m.beep = .1; } if (m.trig <= 0) { m.gone = true; m.g.visible = false; explode(m.x, .3, m.z, R.TRAP_DAMAGE, 4, true); } }
  }
  // ---- portal, tracers, lights, particles
  if (L.exit) { L.exit.r1.rotation.y += dt * 1.2; L.exit.r2.rotation.x += dt * 1.8; L.exit.r3.rotation.y -= dt * 2.4; L.exit.g.position.y = 1.5 + Math.sin(L.t * 2) * .08;
    portalL.intensity = 26 + Math.sin(L.t * 5) * 6; if (Math.random() < dt * 30) sparks.spawn(L.exit.x + rnd(-1, 1), .1, L.exit.z + rnd(-1, 1), 0, rnd(1, 2.5), 0, 0x3df2ff, 1.2, -.5); }
  for (const t of L.tracers) { t.life -= dt; if (t.life <= 0) { world.remove(t.m); t.m.geometry.dispose(); } }
  L.tracers = L.tracers.filter(t => t.life > 0);
  muzzleL.intensity *= .6; if (P.fire < .08) flashSprite.visible = false;
  for (const l of boomL) l.intensity *= Math.exp(-dt * 7);
  alarmL.intensity *= Math.exp(-dt * 10);
  // pooled ceiling lights: the four fixtures nearest the player get real lights
  L.poolT -= dt;
  if (L.poolT <= 0) {
    L.poolT = .25;
    const near4 = L.fixtures.map(f => [Math.hypot(f.x - P.x, f.z - P.z), f]).sort((a, b) => a[0] - b[0]).slice(0, 4);
    pool.forEach((l, k) => { const f = near4[k] && near4[k][1]; l.userData.f = f; if (f) l.position.set(f.x, WH - .25, f.z); });
  }
  pool.forEach(l => { const f = l.userData.f; l.intensity = f ? (f.flicker ? (Math.random() < .08 ? 2 : 16) : 16) : 0; });
  sparks.update(dt); embers.update(dt);
  if (P.dead && (L.deadT -= dt) <= 0 && S === 'play') onDeath();
  if (L.done && (L.clearT -= dt) <= 0 && S === 'play') onClear();
}

// camera + weapon pose
function placeCamera(dt) {
  P.shake *= Math.exp(-dt * 6);
  const sh = P.shake * .06, sp = Math.hypot(P.vx, P.vz);
  const bobY = sp > .5 ? Math.sin(P.bob) * .045 : 0, bobX = sp > .5 ? Math.cos(P.bob * .5) * .03 : 0;
  const deadDrop = P.dead ? clamp(1 - L.deadT / 1.6, 0, 1) : 0;
  camera.position.set(P.x, EYE + bobY - deadDrop * 1.2, P.z);
  camera.rotation.set(P.pitch + rnd(-sh, sh) + P.kick * .02, P.yaw + rnd(-sh, sh), deadDrop * .6);
  P.kick *= Math.exp(-dt * 18);
  gun.position.set(.24 + bobX, -.24 + bobY * .6 - (P.reload > 0 ? Math.sin(Math.PI * (1 - P.reload)) * .18 : 0), -.42 + P.kick * .06);
  gun.rotation.set(P.kick * .12 + (P.reload > 0 ? Math.sin(Math.PI * (1 - P.reload)) * .6 : 0), 0, P.dashT > 0 ? .25 : 0);
  gun.visible = !P.dead;
}

// =================================================================== HUD + minimap
function hud() {
  let s = ''; for (let i = 0; i < P.max; i++) s += `<i class="${i < P.hp ? (P.hp <= 3 ? 'on low' : 'on') : ''}"></i>`;
  $('hpbar').innerHTML = s; $('ammoN').textContent = P.reload > 0 ? '--' : P.ammo; $('ammoM').textContent = MAG;
  $('reloadI').style.width = P.reload > 0 ? (100 * (1 - P.reload)) + '%' : '0%';
  $('dashS').textContent = P.dashCd > 0 ? P.dashCd.toFixed(1) + 's' : 'READY';
  $('lvname').textContent = `LEVEL ${L.i + 1} · ${L.def.title}`;
  const doors = Object.values(L.doors), allOpen = doors.every(d => d.open);
  $('obj').textContent = L.keyNeeded && !L.hasKey ? 'Find the keycard' : doors.length && !allOpen ? 'Open the blast door' : 'Reach the extraction portal';
  $('tm').textContent = L.time.toFixed(1); $('cr').textContent = `${L.cores}/${L.coresTotal}`; $('kl').textContent = `${L.kills}/${L.drones.length}`;
  $('engage').style.display = S === 'play' && !locked && !P.dead && !L.done ? 'block' : 'none';
}
function minimap() {
  const m = $('minic'), g = m.getContext('2d'), s = 7; g.fillStyle = '#04060e'; g.fillRect(0, 0, m.width, m.height);
  for (let r = 0; r < L.rows; r++) for (let c = 0; c < L.cols; c++) { if (!L.explored[r * L.cols + c]) continue; g.fillStyle = L.grid[r][c] === '#' ? '#26345e' : '#0f1830'; g.fillRect(c * s, r * s, s, s); }
  const dot = (x, z, col, rr = 2.4) => { g.fillStyle = col; g.beginPath(); g.arc(x / TS * s, z / TS * s, rr, 0, 7); g.fill(); };
  for (const k in L.doors) { const d = L.doors[k]; if (L.explored[d.r * L.cols + d.c]) { g.fillStyle = d.open ? '#3dff9a' : '#ffd23d'; g.fillRect(d.c * s + 1, d.r * s + 1, s - 2, s - 2); } }
  for (const it of L.items) if (!it.taken && L.explored[Math.floor(it.z / TS) * L.cols + Math.floor(it.x / TS)]) dot(it.x, it.z, it.kind === 'key' ? '#ff3df0' : it.kind === 'med' ? '#3dff9a' : '#ffd23d', 1.8);
  for (const d of L.drones) if (d.hp > 0 && d.alert) dot(d.x, d.z, '#ff3d6e', 2.4);
  if (L.exit) dot(L.exit.x, L.exit.z, '#3df2ff', 3 + Math.sin(L.t * 4));
  const px = P.x / TS * s, pz = P.z / TS * s; g.save(); g.translate(px, pz); g.rotate(-P.yaw); g.fillStyle = '#fff';
  g.beginPath(); g.moveTo(0, -6); g.lineTo(4, 4); g.lineTo(-4, 4); g.closePath(); g.fill(); g.restore();
}

// =================================================================== screens
function startLevel(i, inCampaign) {
  levelIdx = i; campaign = inCampaign; buildLevel(i); setState('intro');
  const def = GD.levels[i];
  $('inLvl').textContent = `LEVEL ${i + 1} / ${GD.levels.length}`; $('inTitle').textContent = def.title;
  $('inMeta').innerHTML = `${def.source}<br>AI quality score <b style="color:var(--gd)">${def.quality.toFixed(3)}</b> · simulated players finish ${Math.round(def.completion * 100)}% of the time`;
  placeCamera(0); hud(); setTimeout(() => { if (S === 'intro') setState('play'); }, 2800);
}
function onDeath() { deaths[levelIdx]++; setState('dead'); $('deadMsg').textContent = `Drones destroyed: ${L.kills}/${L.drones.length} · time ${L.time.toFixed(1)}s · failed attempts on this level: ${deaths[levelIdx]}`; }
function onClear() {
  const def = GD.levels[levelIdx], r = results[levelIdx] = { time: L.time, dmg: L.dmg, kills: L.kills, drones: L.drones.length, cores: L.cores, coresTotal: L.coresTotal, deaths: deaths[levelIdx] };
  $('clStats').innerHTML = [['TIME', r.time.toFixed(1) + 's'], ['DAMAGE TAKEN', r.dmg], ['DRONES', `${r.kills}/${r.drones}`], ['DATA CORES', `${r.cores}/${r.coresTotal}`]]
    .map(([k, v]) => `<div class="stat glass"><div class="v">${v}</div><div class="k">${k}</div></div>`).join('');
  const pc = def.persona || {};
  $('clAI').innerHTML = `<b>What the AI predicted for this level:</b> simulated players finished ${Math.round(def.completion * 100)}% of runs ` +
    `(reckless ${Math.round((pc.rusher || 0) * 100)}%, careful ${Math.round((pc.cautious || 0) * 100)}%, explorer ${Math.round((pc.explorer || 0) * 100)}%), ` +
    `losing about ${(def.damage || 0).toFixed(1)} health on average. You took ${r.dmg} damage${r.deaths ? ` after ${r.deaths} failed attempt(s)` : ' on your first clear'}.`;
  $('bNext').textContent = levelIdx + 1 < GD.levels.length ? 'NEXT LEVEL' : 'FINISH';
  setState('clear');
}
function showSummary() {
  const rows = GD.levels.map((d, i) => { const r = results[i];
    return `<tr><td>${i + 1}. ${d.title}</td><td>${d.quality.toFixed(3)}</td><td>${Math.round(d.completion * 100)}%</td><td>${r ? r.time.toFixed(1) + 's' : '-'}</td><td>${r ? r.dmg : '-'}</td><td>${r ? r.deaths : '-'}</td></tr>`; }).join('');
  $('sumT').innerHTML = `<tr><th>LEVEL</th><th>AI QUALITY</th><th>SIM. COMPLETION</th><th>YOUR TIME</th><th>DAMAGE</th><th>FAILED TRIES</th></tr>${rows}`;
  $('sumAI').innerHTML = `The AI scored these levels with ${GD.totalSims.toLocaleString()} simulated playthroughs before you ever saw them. Level 1 is the raw generated level; level 2 is the same level after the agents fixed it; level 3 was designed by an LLM and then optimised. Compare the AI's numbers with how the levels felt to you.`;
  setState('summary');
}
function miniLevel(cvs, grid, scale = 6) {
  cvs.width = grid[0].length * scale; cvs.height = grid.length * scale;
  const g = cvs.getContext('2d'), col = { '#': '#1e2a4d', '.': '#0b1020', S: '#ff3df0', E: '#3df2ff', M: '#ff3d6e', T: '#ff8a3d', H: '#3dff9a', C: '#ffd23d', K: '#ff3df0', D: '#c99a1a' };
  grid.forEach((row, r) => [...row].forEach((ch, c) => { g.fillStyle = col[ch] || '#0b1020'; g.fillRect(c * scale, r * scale, scale, scale); }));
  return g;
}
function buildSelect() {
  $('cards').innerHTML = '';
  GD.levels.forEach((d, i) => {
    const el = document.createElement('div'); el.className = 'card glass';
    el.innerHTML = `<h3>LEVEL ${i + 1} · ${d.title}</h3><div class="q">${d.quality.toFixed(3)}</div><p>${d.source}</p><canvas></canvas>`;
    miniLevel(el.querySelector('canvas'), d.grid); el.onclick = () => { SFX.ui(); startLevel(i, false); }; $('cards').appendChild(el);
  });
}
const BOTC = { rusher: '#ff3d6e', cautious: '#3df2ff', explorer: '#ffd23d' };
let labAnims = [], labT = 0;
function buildLab() {
  labAnims = []; const wrap = $('labwrap'); wrap.innerHTML = '';
  GD.runs.forEach(run => {
    const h0 = run.history[0], h1 = run.history[run.history.length - 1];
    const box = document.createElement('div'); box.className = 'glass';
    box.innerHTML = `<h3>${run.label}</h3><div style="color:var(--mut)">Reasoning: ${run.llm} · ${run.workers} parallel workers · ${run.total_sims.toLocaleString()} simulated playthroughs</div>
      <canvas class="ch" style="width:100%;height:150px;margin:8px 0"></canvas>
      <div>Quality <b style="color:var(--gd)">${h0.best_score.toFixed(3)} → ${h1.best_score.toFixed(3)}</b> · completion ${Math.round(h0.best_metrics.completion_rate * 100)}% → ${Math.round(h1.best_metrics.completion_rate * 100)}%</div>`;
    wrap.appendChild(box); const c = box.querySelector('canvas.ch'); c.width = 520; c.height = 150; drawRunChart(c, run.history);
    const box2 = document.createElement('div'); box2.className = 'glass';
    box2.innerHTML = `<h3>SIMULATED PLAYERS · FINAL LEVEL</h3><canvas class="bot" style="width:100%"></canvas><div class="legend"><span><i style="background:${BOTC.rusher}"></i>reckless</span><span><i style="background:${BOTC.cautious}"></i>careful</span><span><i style="background:${BOTC.explorer}"></i>explorer</span></div>`;
    wrap.appendChild(box2); const bc = box2.querySelector('canvas.bot'); miniLevel(bc, run.final_grid, 14); labAnims.push({ cvs: bc, grid: run.final_grid, traces: run.traces, i: 0 });
    const box3 = document.createElement('div'); box3.className = 'glass'; box3.style.gridColumn = '1 / -1';
    box3.innerHTML = `<h3>AGENT LOG · ${run.label}</h3><pre></pre>`; box3.querySelector('pre').textContent = run.log.join('\n'); wrap.appendChild(box3);
  });
}
function drawRunChart(c, H) {
  const g = c.getContext('2d'), all = H.flatMap(h => h.candidates.map(x => x.quality.total)), lo = Math.min(...all) - .03, hi = Math.max(...all) + .03;
  const X = i => 30 + i * (c.width - 50) / Math.max(1, H.length - 1), Y = v => 10 + (hi - v) * (c.height - 30) / (hi - lo);
  g.fillStyle = '#05070f'; g.fillRect(0, 0, c.width, c.height); g.strokeStyle = '#16203a'; g.fillStyle = '#8a97b8'; g.font = '12px Rajdhani, sans-serif';
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; g.beginPath(); g.moveTo(30, Y(v)); g.lineTo(c.width - 10, Y(v)); g.stroke(); g.fillText(v.toFixed(2), 0, Y(v) + 4); }
  H.forEach((h, i) => { g.fillStyle = '#8a97b8'; g.fillText('R' + h.round, X(i) - 6, c.height - 4); h.candidates.forEach(x => { g.fillStyle = 'rgba(138,151,184,.6)'; g.beginPath(); g.arc(X(i), Y(x.quality.total), 3, 0, 7); g.fill(); }); });
  g.strokeStyle = '#3df2ff'; g.lineWidth = 2.5; g.beginPath(); H.forEach((h, i) => i ? g.lineTo(X(i), Y(h.best_score)) : g.moveTo(X(i), Y(h.best_score))); g.stroke();
}
function labTick(dt) {
  labT += dt; if (labT < .09) return; labT = 0;
  for (const a of labAnims) {
    const g = miniLevel(a.cvs, a.grid, 14); a.i++; let maxLen = 0;
    for (const p of ['rusher', 'cautious', 'explorer']) {
      const tr = a.traces[p].trace; maxLen = Math.max(maxLen, tr.length); const k = Math.min(a.i, tr.length - 1);
      g.fillStyle = BOTC[p] + '66'; for (let j = 0; j <= k; j++) g.fillRect(tr[j][1] * 14 + 5, tr[j][0] * 14 + 5, 4, 4);
      g.fillStyle = BOTC[p]; g.beginPath(); g.arc(tr[k][1] * 14 + 7, tr[k][0] * 14 + 7, 5, 0, 7); g.fill();
    }
    if (a.i > maxLen + 15) a.i = 0;
  }
}

// =================================================================== buttons + keys
const go = (id, f) => $(id).onclick = () => { audioInit(); SFX.ui(); f(); };
let labFrom = 'menu';
go('bStart', () => { results = []; deaths = deaths.map(() => 0); startLevel(0, true); });
go('bSelect', () => { buildSelect(); setState('select'); });
go('bLab', () => { labFrom = 'menu'; buildLab(); setState('lab'); });
go('bLab2', () => { labFrom = 'pause'; buildLab(); setState('lab'); });
go('bLab3', () => { labFrom = 'menu'; buildLab(); setState('lab'); });
go('bHow', () => setState('how'));
['bBack1', 'bBack2', 'bMenu', 'bMenu2', 'bMenu3', 'bMenu4'].forEach(id => go(id, () => { menuScene(); setState('menu'); }));
go('bBack3', () => { if (labFrom === 'pause' && L && !L.done && !P.dead) setState('pause'); else { menuScene(); setState('menu'); } });
go('bResume', () => { setState('play'); canvas.requestPointerLock && canvas.requestPointerLock(); });
go('bRestart', () => startLevel(levelIdx, campaign)); go('bRetry', () => startLevel(levelIdx, campaign)); go('bRetry2', () => startLevel(levelIdx, campaign));
go('bNext', () => levelIdx + 1 < GD.levels.length ? startLevel(levelIdx + 1, campaign) : showSummary());
function onKey(k) {
  if (k === 'g') setQuality(quality === 'high' ? 'low' : 'high');
  if (k === 'm') { A.musicOn = !A.musicOn; if (A.music) A.music.gain.value = A.musicOn ? .18 : 0; }
  if (S === 'menu' && k === 'enter') $('bStart').click();
  else if (S === 'pause' && k === 'escape') $('bResume').click();
  else if (S === 'dead' && (k === 'enter' || k === 'r')) $('bRetry').click();
  else if (S === 'clear' && k === 'enter') $('bNext').click();
  else if (['select', 'how', 'lab', 'summary'].includes(S) && k === 'escape') { menuScene(); setState('menu'); }
}

// menu: slow camera drift through the optimised level behind the title
let menuMode = false;
function menuScene() { buildLevel(Math.min(1, GD.levels.length - 1)); menuMode = true; for (const d of L.drones) d.g.visible = true; }

// =================================================================== graphics quality (auto-detect + G to toggle)
let quality = 'high', fpsT = 0, fpsN = 0, autoChecked = false;
function setQuality(q, why) {
  quality = q; const hi = q === 'high';
  bloom.enabled = hi; torch.castShadow = hi; renderer.shadowMap.enabled = hi;
  renderer.setPixelRatio(hi ? Math.min(window.devicePixelRatio || 1, 1.5) : 1);
  renderer.setSize(innerWidth, innerHeight); composer.setSize(innerWidth, innerHeight);
  scene.traverse(o => { if (o.material) o.material.needsUpdate = true; });
  if (L) toast(`GRAPHICS: ${q.toUpperCase()}${why ? ' (' + why + ')' : ''} · G to change`);
}
function autoQuality(dt) {
  if (autoChecked || S !== 'play') return;
  fpsT += dt; fpsN++;
  if (fpsT >= 4) { autoChecked = true; const fps = fpsN / fpsT; if (fps < 32 && quality === 'high') setQuality('low', Math.round(fps) + ' fps detected'); }
}

// =================================================================== main loop
let last = performance.now(), hudT = 0;
function frame(now) {
  requestAnimationFrame(frame);  // schedule first so one bad frame can never freeze the game
  let dt = Math.min(.05, (now - last) / 1000); last = now;
  try { step(dt); } catch (e) { console.error(e); }
}
function step(dt) {
  musicTick();
  if (hitstop > 0) { hitstop -= dt; dt = 0; }
  if (slowmo > 0) { slowmo -= dt; dt *= .35; }
  if (L && S === 'play') { menuMode = false; autoQuality(dt); update(dt); placeCamera(dt); hudT -= dt; if (hudT <= 0) { hud(); minimap(); hudT = .05; } }
  else if (L && S === 'intro') { placeCamera(dt); L.t += dt; sparks.update(dt); }
  else if (L && menuMode) {  // attract mode
    L.t += dt; P.yaw += dt * .12; P.pitch = Math.sin(L.t * .3) * .08; camera.position.set(P.x, EYE, P.z); camera.rotation.set(P.pitch, P.yaw, 0); gun.visible = false;
    pool.forEach((l, k) => { const f = L.fixtures[k]; if (f) { l.position.set(f.x, WH - .25, f.z); l.intensity = 16; } });
    for (const d of L.drones) { d.t += dt; d.g.position.y = 1.75 + Math.sin(d.t * 2.2) * .12; d.ring.rotation.z += dt * 3; }
    if (L.exit) { L.exit.r1.rotation.y += dt; L.exit.r2.rotation.x += dt * 1.5; }
    if (S === 'lab') labTick(dt);
  } else if (S === 'lab') labTick(dt);
  composer.render();
}
window.__dbg = { get L() { return L; }, get P() { return P; }, get S() { return S; }, startLevel, setState, keys, bloom, renderer, scene, torch, setQuality, get quality() { return quality; } };
menuScene();
$('loading').classList.remove('on');
requestAnimationFrame(frame);
