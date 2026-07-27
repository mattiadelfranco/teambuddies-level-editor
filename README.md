# Team Buddies Level Editor

A browser-based level editor and modding toolchain for **Team Buddies**
(PSX, Psygnosis 2000, SCES-02986), built on a from-scratch reverse engineering
of the game's data formats.

Everything the campaign does turned out to be data-driven — no scripting engine,
no code injection needed for level edits. You edit, the toolchain repacks the
game archive and rebuilds the ISO, and the result runs in any PSX emulator.

## Features

- **Drag & drop editing** of every placeable element, on top of a rendered
  top-down view of the real level terrain:
  - spawn points + capture pads (the engine draws pads at runtime; the editor
    moves logic, painted tiles and tile animations together)
  - units and creatures (the full 62-entry catalog with real names: buddies,
    animals, mission objectives, mech bosses, capture animals)
  - decorative objects (trees, benches, buildings — cloned with correct
    per-model parameters)
  - turrets and static objects (the full 188-entry STATICS catalog by name:
    every turret type, power-up trees/buildings, world bases…)
- **Team-owned turrets** via a tiny optional engine patch: place an auto turret,
  pick its team, and it defends that team's base (vanilla format has no team
  field — see below)
- **One-click ISO build**: repacks all modded levels into the archive (in-place
  when they fit, relocated with table fixups when they don't) and rebuilds a
  runnable ISO with mkpsxiso
- **Insertion, deletion and duplication** of records everywhere — the tools
  handle the section shifting and offset-table fixups the formats require
- "🛡 base defenses" helper: two turrets around every base, teams auto-assigned

## Requirements

- Python 3 (no third-party packages needed)
- `git`, `cmake` and a C++ compiler (to build [mkpsxiso])
- **your own dump** of Team Buddies (Europe) (SCES-02986) as a `.bin` disc image

> **No game data is included in this repository** — you must dump the disc you
> own. Other regional versions are untested.

## Quickstart

```bash
git clone https://github.com/mattiadelfranco/teambuddies-level-editor.git
cd teambuddies-level-editor
python3 tools/setup.py /path/to/TeamBuddies.bin   # extracts + builds everything
python3 tools/editor_server.py                     # then open http://localhost:8787
```

`setup.py` is idempotent — every step is skipped if its output already exists.
It clones and builds mkpsxiso, extracts the disc, unpacks `BUDDIES.DAT`,
backs up the originals and renders the terrain of all 45 levels.

### Using the editor

1. Pick a level, tick **"Modalità modifica"** (edit mode) and drag the markers:
   red = spawn/pad, yellow = units, cyan = turrets/statics, purple = objects.
2. Add things with **+ unità** (units), **+ oggetto** (level objects),
   **+ torretta/speciale** (turrets/statics by name). Select something to
   duplicate, delete, or assign a **team** to a turret.
3. **💾 salva livello** writes your edits to `teambudd/mods/<level>/`
   (vanilla files are never modified).
4. **🔨 compila ISO** produces `teambudd/rebuild.bin`/`.cue` — load it in
   DuckStation or any emulator. After a build that relocates levels, restart
   the emulated game fully (don't just load a savestate).

### The team patch

The on-disc format has no team field for placed turrets, and the engine's
proximity-based assignment effectively always hands them to an AI team. The
optional patch (`tools/tb_patch_eng.py`, applied automatically at build time)
repurposes an unused field of the placement record as a forced team — ~38
instructions rewritten in place inside the engine overlay, no code cave needed.
`python3 tools/tb_patch_eng.py --revert` restores the vanilla binary.
Verified on real gameplay: a team-1 auto turret ignores you and fires at enemies.

## Repository layout

```
tools/          the toolchain (setup, extract/repack/rebuild, renderer,
                editor server + UI generator, engine patch) — see tools/README.md
docs/FORMATS.md the reverse-engineered formats: BUDDIES.DAT, BIND, PLD, PND,
                object catalogs, engine notes, the team patch
ghidra/scripts/ headless Ghidra helper scripts used during the reversing
ghidra/*.txt    decompiled excerpts of the functions that consume each format,
                kept for research/documentation purposes
teambudd/       (created by setup.py, not in the repo) your extracted game data,
                mods and build output
mkpsxiso/       (created by setup.py, not in the repo) ISO build tool
```

## How it works, briefly

`BUDDIES.DAT` is a sector-indexed archive of 1269 entries; levels are nested
"BIND" containers holding textures, models, placement data (PLD), terrain +
objects (PND), collision and AI paths. The PLD is a 17-section table (spawns,
placed units, patrol routes…); the PND holds object instances, a static-objects
list, a heightmap and the textured tile grid with its animation queue. Catalogs
for everything live in config BINs inside the same archive (units, statics,
crate build recipes, localized names). Full details with struct layouts and the
engine functions that read them: **[docs/FORMATS.md](docs/FORMATS.md)**.

## Credits
This project borns as a stress-test to check the new Anthropic Fable5 LLM model skills about security analysis and reverse engineering.

Reverse engineering and tools by Mattia Del Franco, with AI assistance
(Claude). Built with [mkpsxiso] by Lameguy64 and [Ghidra].

Team Buddies is © Psygnosis/Sony. This project contains no game assets and is
not affiliated with or endorsed by the rights holders. Research material is
provided for interoperability and preservation purposes.

[mkpsxiso]: https://github.com/Lameguy64/mkpsxiso
[Ghidra]: https://ghidra-sre.org/
