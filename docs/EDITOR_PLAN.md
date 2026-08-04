# Map Editor v2 — Plan

Goal: evolve the current viewer-with-edit-mode into a real map editor:
tile painting, texture picking, height sculpting, and placement of every
game object with graphical previews — with a clean English UI and full
2D/3D parity.

## Where we start from

What already works (all verified in game): PND/PLD parsing and rebuilding,
pads (s0) with painted-tile + animation remap, s6 units, crate zones (s3) and
per-zone crate config (LEVELS.BIN), crate recipes, extra list
(turrets/statics) with forced team (ENG patch), multi-team, instance
add/move/clone, .LOD model rendering, exact coordinate frames and height
scale (decompiled from the engine), ISO rebuild with entry relocation.

Two structural facts make terrain editing easy:

- The heightmap (65×65 s16) and tile array (64×64×28B) have **fixed size and
  position** inside the PND → editing them is size-neutral, in-place.
- `MAXHEIGHTS`/`MINHEIGHTS` are computed **at load time** by the engine
  (`FUN_800aa4b0`) from the heightmap → nothing extra to regenerate.

Main architectural problem: the editor is a 12 MB generated HTML file
(`build_viewer.py` string template + two injected JS blobs in
`build_editor.py`), with all 45 levels' data embedded. Every save regenerates
the whole page; the JS lives inside Python strings; UI is one long stack of
controls in Italian; several edit actions only work from the 2D view.

## Phase 0 — Foundation: real web app, English, 2D/3D parity

1. **Split the editor out of the Python templates** into static files served
   by `editor_server.py`: `web/index.html`, `web/editor.css`, and JS modules
   (`state.js`, `views2d.js`, `views3d.js`, `terrain.js`, `objects.js`,
   `catalog.js`, `api.js`). No build step needed (plain ES modules).
2. **Data via API instead of embedding**: `GET /api/levels` (list),
   `GET /api/level/<entry>` (parsed PLD/PND JSON incl. heightmap, instances,
   extra, s0/s3/s6, mods-aware), existing `/api/3d/<entry>` and
   `/ground3d/<entry>.png`. Page loads in milliseconds; saving no longer
   regenerates HTML. `build_viewer.py` stays for the standalone read-only
   viewer.
3. **Single editor state store** shared by both views (the current
   `edStates`/`ED3` duplication is why some functions only work in 2D).
   Every mutation goes through one `apply(action)` entry point → enables
   undo/redo later.
4. **English UI** throughout (single `strings.js`; keep it translation-ready).
5. **New layout** (see wireframe below) and **3D parity audit**: every
   operation (add unit/object/turret, duplicate, delete, team, defenses,
   zone config...) must work identically in 2D and 3D. Known 3D gaps to fix
   while porting: add/duplicate/delete only refresh the 2D canvas, selection
   is not always in sync, some panel buttons operate on stale state, camera
   default not matching the game view.

```
┌────────────────────────────────────────────────────────────────┐
│ Level ▾   [2D|3D]   Save · Build ISO            Team Buddies   │ top bar
├──────┬────────────────────────────────────┬────────────────────┤
│ ◇ Sel│                                    │ [Inspector]        │
│ ▲ Hgt│                                    │  props of selection│
│ ▦ Til│          viewport (2D/3D)          │ [Catalog]          │
│ ♟ Obj│                                    │  object browser    │
│      │                                    │ [Palette]          │
│ tools│                                    │  tiles / textures  │
│      │                                    │ [Level]            │
│      │                                    │  teams·zones·crates│
├──────┴────────────────────────────────────┴────────────────────┤
│ tile (x,z) · h · hint                                status bar│
└────────────────────────────────────────────────────────────────┘
```

Deliverable: same features as today, new skin/architecture, byte-identical
saves (regression: no-op save == current output).

## Phase 1 — Height sculpting

- Tools: **Raise / Lower** (brush, radius 1–8, strength), **Flatten** (to
  picked height), **Smooth**, **Set level** (numeric, in file units — 4 units
  = half a tile). Works in 3D (raycast the terrain mesh, live mesh update)
  and in 2D (heightmap overlay with hillshade).
- Constraints & helpers: warn when editing under pads/zones (they need flat
  ground), clamp to s16, optional snap to multiples of 4 (all vanilla values
  are ~multiples of 4).
- Save path: write the 65×65 block in place (`_tiles_layout` offsets), then
  invalidate ground PNG caches. Nothing else changes in the file.
- Risks to document in-UI: PTH (AI walkability) is not regenerated — AI may
  not path over sculpted areas; steep cliffs read fine by the engine (it
  interpolates heights at runtime, no collision file involved for terrain).

## Phase 2 — Tile painting (tilemap + textures)

- **Palette panel**: the level's TIM atlas rendered as a grid of 64×64 cells
  (we already decode TIM+CLUTs); for each cell offer its CLUT variants
  (recolors) and the 8 orientations (rot/mirror via the corner-delta
  encoding). "Pick" tool (eyedropper) reads an existing tile's
  cell+clut+orientation.
- **Tools**: paint single tile, rectangle fill, clone-stamp (copy a region,
  stamp elsewhere — same mechanism `_clone_pad` uses), orientation rotate on
  selection.
- **Vertex colors**: expose as an optional "shade" sub-tool (vanilla is all
  neutral 128; the engine supports per-vertex tinting — nice for custom
  shading).
- **Animated tiles guard**: tiles referenced by the animation queue
  (pads' arrows, water) get a badge; painting over one removes/remaps its
  descriptors exactly like `_repaint_pad` already does (shared helper).
- Rendering: client-side patching of the ground canvas for instant feedback;
  server re-renders the PNG on save (existing pipeline, mtime-invalidated).
- Save path: 28-byte records in place; queue edits only when animated tiles
  are touched (size-changing, handled like `_clone_pad` today).

## Phase 3 — Object placement with previews

One **Catalog panel** with search + categories, thumbnails, drag-to-place
into either view:

| category | source | preview | notes |
|---|---|---|---|
| Level models (instances) | level `MDL.BND` | WebGL thumbnail (offscreen render of the meshes we already load) | e-param cloned from a template instance as today; `alt` auto-snapped to ground (same unit as heightmap) |
| Turrets & statics (extra list) | `STATICS.BIN` (188) | real model: resolve the record's resource pair → DAT entry → `.LOD` (research task; formulas partially known from `FUN_80093a44`/`FUN_8007409c`) — fallback icon | team selector (ENG patch field f8); vanilla-safe badge for the 12 types seen in shipped levels |
| Units (s6) | BIND 958 catalog (62 slots) | buddy/animal model via `BUDDIES.BIN` resource ids (`id+0x3ed/0x3e5` → DAT model, research task) — fallback icon set | type 0–61 enforced; team picker |
| Pads, crate zones, spawn helpers | PLD s0/s3 | schematic icons | existing logic (painted tiles, anim remap, claiming preview) unchanged |

- **Rotation widget** for instances/turrets (yaw in PSX 0x1000 units, shown
  in degrees; the ±90° display sign still needs one in-game check).
- **Validations surfaced in the Inspector**: pad↔base claiming preview
  (already computed), "base too close to large tree", "pad not flat",
  "zone far from pad", s6 type range.
- Stretch: place models **not present in the level** by importing the .LOD
  (+ its TIM) into `MDL.BND`/`TIM.BND` — `tb_rebuild` already relocates grown
  entries (verified in game). Kept last because it needs TIM page/CLUT
  management.

## Phase 4 — Polish

- **Undo/redo** (action log through the single `apply()` from Phase 0).
- Copy/paste of terrain+tiles regions across levels.
- Minimap, keyboard shortcuts (tool hotkeys, brush size, Ctrl+Z), autosave
  drafts (localStorage) with "restore unsaved changes".
- Optional: per-level light direction in 3D, water animation preview.

## Testing strategy (every phase)

1. **Byte-level round-trip**: open → no-op save → file identical to input;
   scripted for all 45 levels.
2. **Golden mods**: the existing verified mods (4-team BATTLE, 5-team, zones)
   must re-save unchanged through the new pipeline.
3. **In-game smoke test** per phase (DuckStation savestate at level select):
   sculpted hill walkable, painted tiles visible, placed objects spawn.

## Known limitations to state in the UI

- PTH (AI paths) and s7 patrols are not regenerated for new layouts.
- CL2 semantics still unknown (never needed so far).
- Editing the animation queue beyond pad/water remapping is out of scope.
- The residual "green smears" on steep slopes are the engine's own art
  stretching (same in the real game); revisit only if a real divergence from
  in-game rendering is found.
