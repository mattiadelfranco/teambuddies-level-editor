# Tools reference

Command-line reference for the toolchain. See the [repository README](../README.md)
for setup and the editor guide, and [docs/FORMATS.md](../docs/FORMATS.md) for the
reverse-engineered file formats.

All tools take paths relative to the repository root and expect the directory
layout produced by `setup.py`.

## setup.py — one-shot bootstrap

```
python3 tools/setup.py /path/to/TeamBuddies.bin
```

Builds mkpsxiso, extracts your disc image, unpacks `BUDDIES.DAT`, renders level
terrain. Idempotent: every step is skipped if its output already exists.

## editor_server.py — the level editor

```
python3 tools/editor_server.py        # then open http://localhost:8787
```

Serves the editor web app from `web/` (plain ES modules, no build step) and
applies edits:

- `GET /api/levels`, `/api/catalogs`, `/api/level/<entry>` — level list, object
  catalogs and full parsed level data (mods-aware; parsing in `tb_level.py`)
- `POST /api/save` — writes the edited level into `teambudd/mods/<entry>/`
  (baseline = the existing mod if present, else a copy of the vanilla files;
  a no-op save is byte-identical — regression-tested on all 45 levels)
- `POST /api/build` — applies the ENG.BIN team patch, repacks every modded level
  into a fresh copy of the vanilla `BUDDIES.DAT` and rebuilds the ISO
  (`teambudd/rebuild.bin` / `rebuild.cue`, ready for an emulator)
- `GET /api/3d/<entry>` — meshes + textures for the editor's 3D view (parsed
  from the level's `MDL.BND`/`TIM.BND` via `tb_lod.py`, cached in memory)
- `GET /ground3d/<entry>.png` — native-res terrain render (64 px/tile,
  4096×4096, cached in `teambudd/grounds3d/`, invalidated by the PND mtime)

The app has synchronized **2D and 3D views** sharing one state store: real
level geometry (heightmap terrain + textured LOD models), orbit camera, exact
world-coordinate picking (click the ground to copy tile coordinates), and the
same editing operations in both views. Layer toggles (ground texture,
heightmap, AI paths, objects, PLD sections) work in 2D and 3D.

## tb_lod.py — parse .LOD models

```
python3 tools/tb_lod.py teambudd/dat_estratto/bind/0512/MDL.BND                   # list models
python3 tools/tb_lod.py teambudd/dat_estratto/bind/0512/MDL.BND BSE_WOODS.LOD out.obj
```

Parser for the reverse-engineered `.LOD` model format (see FORMATS.md): 15-slot
vertex-cache stream, tri/quad primitives with UVs, per-part TIM texture. Can
export Wavefront OBJ for inspection. Also decodes TIMs (`tim_to_png`).

## tb_extract.py — unpack BUDDIES.DAT

```
python3 tools/tb_extract.py teambudd/estratto/BUDDIES.DAT teambudd/dat_estratto
```

Extracts all 1269 entries (`raw/NNNN.bin`) and the contents of every BIND
container (`bind/NNNN/<original names>`), plus `manifest.tsv` used for repacking.

## tb_repack.py — repack one entry

```
python3 tools/tb_repack.py teambudd/estratto/BUDDIES.DAT teambudd/dat_estratto/manifest.tsv 512 teambudd/dat_estratto/bind/0512
```

Rebuilds a BIND from a folder and writes it back. Creates `BUDDIES.DAT.orig` on
first use. Round-trip verified byte-identical.

## tb_rebuild.py — apply all mods

```
python3 tools/tb_rebuild.py teambudd/estratto/BUDDIES.DAT.orig teambudd/mods teambudd/estratto/BUDDIES.DAT teambudd/dat_estratto/manifest.tsv
```

Starts from the vanilla archive and applies every level in `mods/`: in-place when
the rebuilt BIND fits its original slot, otherwise relocated to the end of the
archive with the sector table fixed up (including the off-by-one size-column
quirk, see FORMATS.md). Used by the editor's build step.

## tb_patch_eng.py — team field for placed objects

```
python3 tools/tb_patch_eng.py            # apply (idempotent, backs up ENG.BIN.orig)
python3 tools/tb_patch_eng.py --revert   # restore vanilla ENG.BIN
```

In-place MIPS patch to the engine overlay: repurposes the unused `f8` field of
PND extra-list records as a forced team (0 = vanilla behaviour). Applied
automatically by the editor's build step. Details in FORMATS.md.

## render_ground.py — render a level's terrain

```
python3 tools/render_ground.py teambudd/dat_estratto/bind/0512 out.png 8
```

Decodes the PND tile array against the level's TIM atlas and writes a top-down
PNG (scale = pixels per world unit / 8 per tile at scale 8).

## build_viewer.py / build_editor.py — standalone HTML (legacy)

```
python3 tools/build_viewer.py            # teambudd/viewer.html (read-only viewer)
python3 tools/build_editor.py            # teambudd/editor.html (legacy editor)
```

Self-contained HTML with all levels embedded — useful to browse levels without
running the server. The editing UI now lives in `web/` served by
`editor_server.py`; `build_editor.py` is kept as the legacy single-file editor.

## ghidra/scripts/ — headless Ghidra helpers

`DumpFuncs.java` (decompile functions containing given addresses),
`DumpAsm.java` / `DumpRange.java` (disassembly windows), `Diag.java`.

```
ghidra_12.1.2_PUBLIC/support/analyzeHeadless ghidra/proj TB -process ENG.BIN -noanalysis \
    -scriptPath ghidra/scripts -postScript DumpFuncs.java 0x800a8780
```
