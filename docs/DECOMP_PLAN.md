# Team Buddies — Decompilation Work Plan

Working plan for a full source-level reimplementation of Team Buddies (PSX, SCES-02986).
The decompilation work itself lives in `decomp/` (a separate git repository, excluded from
this repo); this document is the roadmap and the method contract.

## Goals

Two staged targets, in order:

- **Target A — Rebuildable PS1 source.** Every decompiled system recompiles to MIPS and is
  re-injected into the real game (reusing the existing `tools/` pipeline: expanded slots,
  `tb_fastiso` in-place ISO patching, `tb_patch_eng`-style overlay patches). Payoff is
  incremental: each finished system is immediately moddable in the game running on
  console/emulator — no need to wait for 100%.
- **Target B — Native PC port via [PsyCross](https://github.com/OpenDriver2/PsyCross).**
  The same source compiled natively, with PsyCross providing the PSY-Q SDK surface
  (libgpu/libgte/libspu/libetc/libpad) and `libcd` replaced by direct file I/O — all the
  container formats (BUDDIES.DAT, BIND, PLD, PND, LOD, CL2, PTH, mission scripts) are
  already reversed in [FORMATS.md](FORMATS.md).

## Scale (measured, Aug 2026)

| Binary | Size | Functions | Notes |
|---|---|---|---|
| SCES_029.86 | 148 KB | 999, of which **816 are PSY-Q library** (signature-matched) | ~183 own functions; the 816 are provided by PsyCross in Target B |
| SYS.BIN | 98 KB | 186 | "game OS": resource manager, allocator, overlay loader |
| ENG.BIN | 458 KB | 635 | engine: objects, teams, spawn, level/mission loading |
| GAME.BIN | 345 KB | 365 | gameplay logic |
| MNU + ROT + TUTO + MPLR + LNG | ~127 KB | ~350 | menus and peripheral modes |

**≈ 1,700 own functions total**, ~300 already named/understood
(see `ghidra/ENGINE_MAP.md` and the `ghidra/decompiled_*.txt` dumps).

## Method

**Functional equivalence, not byte-matching.** The game is C++ built with the SN Systems
toolchain (`__SN_ENTRY_POINT`, per-overlay static constructors via `__sn_cpp_structors`);
matching C++ on PS1 is impractical. The model is OpenDriver2/REDRIVER2: a non-matching,
behaviorally verified reimplementation transcribed from Ghidra output.

**Language: restrained C++17** — "C with classes", fixed-width types (`tb_types.h`),
no STL / exceptions / RTTI in game code, `-G0`, MIPS I, o32 ABI for the PS1 target.
Original classes/vtables/this-pointers transcribe 1:1. Tooling stays Python.

**Per-function lifecycle** (tracked in `decomp/PROGRESS.md`):

```
RAW  →  TRANSCRIBED  →  COMPILED  →  VERIFIED
```

- RAW: Ghidra decompiler dump exported (`decomp/ref/`).
- TRANSCRIBED: clean C++ written in `decomp/src/`.
- COMPILED: builds at the function's original address (linker script).
- VERIFIED: differential test clean (see below). **A function that is not VERIFIED is
  treated as wrong**, no matter how obvious the transcription looks — the killer failure
  mode of this method is a subtle sign/fixed-point slip that only shows up minutes into
  gameplay.

**Fast verification loop (RAM injection — seconds per iteration).** DuckStation runs the
game with its MCP server exposed; per function:

1. load a savestate at a suitable scenario;
2. write the recompiled bytes over the original function in RAM (`write_memory` /
   `inject_executable` — no ISO rebuild involved);
3. run a scripted scenario (`input_sequence`, `frame_step`);
4. `diff_memory` of the relevant state regions against the same scenario on vanilla.

**Persistence (file level)** is a separate step from verification: patch the overlay file
in place when the recompiled function fits the original footprint; otherwise route through
a boot-shim + high-RAM cave (see constraints). File-level patches require a clean emulator
restart — savestates embed the old overlay code.

## Hard constraints (from the existing reverse work)

- **Overlays are packed back-to-back in RAM**: SYS.BIN ends exactly at the ENG.BIN base
  (0x80051954) and ENG.BIN ends exactly at the GAME.BIN base (0x800c4240). No natural
  slack: grown functions cannot spill in place.
- **The only free-RAM "cave"** is the arena-steal region `0x801E6114–0x801EB714` (~22 KB,
  created by the pool-24 relocation patch; extendable by raising `ARENA_STEAL` in
  `tools/tb_patch_eng.py`). It is *data* RAM, not file-backed — hosting code there needs a
  small copy-shim at boot.
- **R3000 load-delay slots** are real and emulated by DuckStation: never read a register
  in the instruction after its load. (Already cost one debugging session.)
- Overlay bases: SYS 0x80038f80, ENG 0x80051954, GAME 0x800c4240, TUTO 0x8011a7e4,
  SCES body 0x80014dec. `OVERLAY.DAT` is a 512-byte directory; the `.BIN` files are
  standalone files on the ISO, patched via `tb_fastiso` on the same inode.

## Phases

### Phase 0 — The factory
Build the per-function pipeline, then prove it end-to-end on one function.

- `export_funcs.py`: wrapper around `analyzeHeadless` + the existing
  `ghidra/scripts/DumpFuncs.java` (already exports decompiled C); batch addresses,
  normalize output (strip the `INFO DumpFuncs.java>` prefix of headless stdout).
- `build_mips.py`: `mipsel-none-elf-g++` at the original address via linker-script
  template; emit raw `.text` bytes + a symbol map.
- `inject.py`: RAM mode (DuckStation MCP, for verification) and file mode (in-place
  overlay patch, for persistence).
- `verify.py`: savestate → inject → scripted scenario → RAM diff vs vanilla.

**Exit criterion:** one well-understood function (candidate: the generic freelist
allocator `FUN_800749c4` in ENG, already fully mapped and rewritten once by patch H)
recompiled from C++ and VERIFIED.

### Phase 1 — SYS.BIN (186 fn)
Resource manager, allocator arena, overlay loader — the foundation everything calls into,
and the smallest overlay. **Exit:** the game runs with a fully recompiled SYS.BIN.

### Phase 2 — ENG.BIN (635 fn)
By subsystem, following the existing map: resource/level loader (`FUN_800a7cec`…),
object system, team structures, spawner, mission-script interpreter, config loaders.
**Exit:** fully recompiled ENG.BIN.

### Phase 3 — GAME.BIN (365 fn) + SCES own code (~183 fn)
Gameplay logic, AI, crate/zone mechanics, then the hard tail: renderer command lists and
GTE-heavy code last, when the codebase around them is already trusted.

### Phase 4 — PC port (PsyCross)
CMake project; overlays become static modules; the runtime entry-point jump table at
0x80010184 becomes plain function pointers; SN static constructors become explicit init
calls; `libcd` → direct file I/O through the known formats; expect real adaptation work on
SPU/XA audio (REDRIVER2 precedent). **Exit:** campaign playable natively.

### Phase 5 — Periphery
MNU/ROT/TUTO/MPLR/LNG, multiplayer polish, quality-of-life (resolution, controls).

## Estimates

Transcription throughput observed on this codebase: 20–50 functions per working session
(AI-assisted, with verification). Realistic calendar, working steadily:

| Milestone | Estimate |
|---|---|
| Phase 0 end-to-end | days |
| SYS.BIN fully recompiled | weeks |
| PS1-rebuildable game systems (Phases 1–3) | 2–4 months |
| Playable PC port | 3–6 months |

## Working rules

- Update `decomp/PROGRESS.md` every session (per-overlay counters + per-function rows).
- Shared reversed structures live once, in `decomp/src/include/`, and mirror what
  FORMATS.md / ENGINE_MAP.md document — divergences must be fixed in both places.
- Functions keep their `FUN_xxxxxxxx` identity (in comments) even after naming, so
  everything stays greppable against the Ghidra projects and the existing dumps.
- Verification scenarios are scripted and repeatable, never "it looks fine in game".

## Legal posture

The `decomp/` repository contains **no game assets and no bytes of the original
binaries** — only original transcribed source, tooling, and documentation. Building or
running anything requires the user's own original copy of the game (same posture as this
repo's `teambudd/` exclusion, and as REDRIVER2).
