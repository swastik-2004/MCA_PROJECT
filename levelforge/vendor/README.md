# 3D game bundle

`breach3d.bundle.js` is the prebuilt first-person game: Three.js r186 plus the game code in
`breach3d_src.js`, bundled into one file so the game opens offline with no install.
`levelforge/shooter.py` inlines it into `breach.html` together with the run data.

To rebuild after editing `breach3d_src.js` (needs Node.js; not needed just to play):

```bat
npm install three@0.186 esbuild
npx esbuild breach3d_src.js --bundle --minify --format=iife --target=es2020 --outfile=breach3d.bundle.js
```

Rendering: procedural PBR textures (concrete, tread plate, ceiling) with generated normal maps,
a shadow-casting flashlight, four pooled ceiling lights that follow the player, fog, and bloom.
Gameplay: hitscan weapon, drones with line-of-sight and flow-field pathfinding, proximity mines,
keycard and blast door, extraction portal. Values (health, damage, healing) come from the run data.
