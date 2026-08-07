# Team Buddies (PSX) — reverse-engineered file formats

Reference for *Team Buddies (Europe)* (SCES-02986). All offsets are byte offsets,
all multi-byte values are **little-endian**. "u16/u32/s16" mean unsigned/signed
integers of that width; "8.8" means signed 16-bit fixed-point (8 integer bits,
8 fractional bits).

Coordinates come in two flavours in this game and it is important not to mix them:

- **World units**: 0–512 across the map, origin at a corner. Used by PND object
  instances.
- **Center-relative 8.8**: signed fixed-point relative to the map center
  (world 256). A tile is 8 world units, so `tile = 32 + value_8.8 / 512`
  (equivalently `world = 256 + value_8.8 / 256`). Used by PLD placement sections.

The in-game camera view is the tile grid **mirrored on Y** relative to the raw
data (calibrated against landmarks in the real game).

---

## BUDDIES.DAT — the master archive

Everything the game loads lives here: levels, models, textures, config tables,
text. ~187 MB, 1269 entries.

```
offset  size  field
0       2     "BD"
2       2     entry count (u16)          = 1269
4       4     unknown (u32)
8       ...   table: per entry { size (u32), start_sector (u32) }
```

Sectors are **2048 bytes**. An entry's data starts at `start_sector * 2048`.

⚠️ **Size-column quirk**: for large entries (notably the level BINDs) the `size`
field in the table is unreliable — it is shifted by one row. The real extent is
recovered from the BIND header instead. This quirk is also why a naïve
"append and update sector" repack hangs the game: see `tb_rebuild.py`, which
writes `size[next] = new_extent + 4` in the shifted column.

## BIND — nested container

504 of the DAT entries are BIND containers (levels, config bundles).

```
offset  size  field
0       4     "BIND"
4       4     file count (u32)
8       ...   table: per file { name (32 bytes, zero-terminated, DOS path),
                                offset (u32, from start of BIND), size (u32) }
              then the file data
```

Between consecutive files: 4-byte alignment **plus a 4-byte gap**.

## Levels

DAT entries **512–556** (~45 levels) are BIND containers. Entry 512 = BATTLEHILL
(shown in-game as "Cheeseburger Hill"; internal names ≠ displayed names).

| File | Contents |
|---|---|
| `<NAME>.TIM` | texture atlas (standard PSX TIM, 4bpp 1024×256, 64×64 cells, ~78 CLUTs) |
| `TIM.BND`, `MDL.BND` | additional textures / 3D models |
| `<NAME>.PLD` | placement data (spawns, units, AI paths…) |
| `<NAME>.PND` | terrain + object instances |
| `<NAME>.CL2` | collision |
| `<NAME>.PTH` | AI pathing grid (fixed 16416 bytes) |

Other useful entries: **818+** mission briefing text, **953** config bundle
(unit/weapon/static tables, crate recipes), **958** the 62 unit definition files,
**1263/1264** localized UI text, **15/16** toy names (EN/IT).

---

## PLD — placement data

```
offset  size  field
0       4     unknown (u32; six distinct values across levels, 744…2040)
4       4     unknown (s32; different in all 45 levels)
8       68    17 section offsets (u32 each), relative to byte 8
8+off   ...   section data
```

Sections are physically stored in order (0…16), so inserting/removing records in
a section means rewriting it and adding the delta to every later offset in the
table. Accessor in the engine: `section_base = pld_base + *(pld_base + 4*section)`
(the PLD pointer is advanced by 8 during setup, hence `arg = 4*section`).

All 17 sections, identified (readers found by scanning every `jal` to the
accessor and recovering the `a0` immediate; record shapes cross-checked
against all 45 levels):

| # | arg | what it is | shape | present in |
|---|-----|------------|-------|-----------|
| s0 | 0x00 | **team spawns + capture pads** | `u32 n` + n×8B `{x,z,w,h}` 8.8 | 45/45 (2–11) |
| s1 | 0x04 | **random spawn candidates** — at level start each team draws `rand % n` (`FUN_800717a0`); 7 readers across ENG/GAME | `u32 n` + n×8B | 44/45 |
| s2 | 0x08 | **hidden weapon crates** — `{s16 x, s16 pad, s16 z, s16 which}` (the `pad` word is overwritten with the terrain height before use). See below | `u32 n` + n×8B | 20/45 |
| s3 | 0x0c | **crate-launch zones** — delivery goes to the zone nearest the requester | `u32 n` + per zone `u32 m` + m×u16 half-tile indices | 41/45 |
| s4 | 0x10 | **mission objective points** (`FUN_80072ed8`): marks the object found at each point with flag `0x10000` and counts it in `DAT_800be818`, or spawns resource `0x54` if the spot is empty. Only processed when `d8ce == 1` (mission 1, "That's Rubbish" — its 61 points are the litter) | `u32 n` + n×8B | 3/45 |
| s5 | 0x14 | **unused** — empty in every level, no reader | — | 0/45 |
| s6 | 0x18 | **placed units** — `u16 n` + `u16 extra`, then 8B `{type, team|route, x, z}` | see below | 34/45 |
| s7 | 0x1c | **AI patrol network** — loaded with the level (`FUN_80081ddc`) | `u32 n` + per route `u32 m` + m×12B waypoints | 45/45 |
| s8 | 0x20 | **unused** — empty everywhere, no reader | — | 0/45 |
| s9 | 0x24 | **unused** — empty everywhere, no reader | — | 0/45 |
| s10 | 0x28 | **teleport zones** — `{dest, flags, x0, z0, x1, z1}`: `dest` is the index of the paired zone, `flags` bit 8 = entrance (low nibble = effect variant), and the rect is in **half-tiles** (`tile = value/2`). Entering an entrance launches the buddy on a ballistic arc to the paired zone's centre (`FUN_80076dfc` and friends, with sound + effect). Loading also flags every vertex inside via `FUN_800a79f4(…,1)`, which makes the explosion code (`FUN_800ac1f0`) skip scorch marks (bit 0) and terrain deformation (bit 1) — so teleport pads never get cratered | `u32 n` + n×12B | 17/45 |
| s11 | 0x2c | **unused** — empty everywhere, no reader | — | 0/45 |
| s12 | 0x30 | **delivery/reinforcement drop points** — consumed by `FUN_8008397c`, which pairs them with the 28-byte per-mission config in LEVELS.BIN (timers `param[1..3] × 25`, resources via `FUN_8007409c`) | `u32 n` + n×4B `{x,z}` 8.8 | 10/45 |
| s13 | 0x34 | **scripted drops** — reader in GAME (`0x800e46d0`), never populated in the shipped levels | `u32 n` | 0/45 |
| s14 | 0x38 | **"nearest point" query list** (GAME `FUN_800dfca8` and callers) | `u32 n` + n×8B | 42/45 |
| s15 | 0x3c | **second "nearest point" list**, same shape and users | `u32 n` + n×8B | 41/45 |
| s16 | 0x40 | **unit routes** — indexed 1-based by `FUN_80082054`; the *high byte* of an s6 record's `team|route` field selects the route (0 = none). Same structure as s7 | `u32 n` + per route `u32 m` + m×12B | 33/45 |

Teleport pairing is visible straight in the data: most levels are perfect
involutions (A↔B two-way pads, both `0x0100`), while the bigger ones mix
`0x01xx` entrances with plain `0x00xx` exits — several entrances can share one
exit. WHORA's four zones are two pairs: the large entrance over tiles
x 55–58.5, z 25–29.5 (`0x0103`) sends you to the exit at tile (43, 27)
(`0x0003`). COUNTRYVILE has 41 zones (its tunnel network), SPACECITY 16 in
symmetric two-way pairs.

The s6↔s16 link is unambiguous in the data: across the 33 levels that use
either, the route index never exceeds the number of s16 entries, and usually
matches it exactly — PIGGYINTHEMIDDLE has three pigs with routes 1/2/3 and
three routes; TEMPLETANTRUM four lions with routes 1–4 and four routes; the
capture-vehicle levels give all four teams route 1 (one shared path).

Waypoint record (s7 and s16), 12 bytes:

```
0   u16  x, half-tile encoded
2   u16  z
4   s16  x, center-relative 8.8
6   s16  z
8   u32  facing angle (PSX units, 0x1000 = full turn)
```

Header note: the first u32 is **not** constant across levels (six distinct
values: 744…2040); the second is a per-level value, different in all 45.

### s2 — hidden weapon crates

The reader is `FUN_80071650` (ENG, accessor arg 8), skipped entirely when
`_DAT_8004d8da ∈ {1,2,3}`. For each record it takes the 4th halfword (`which`,
0…9), looks it up in the byte table `DAT_800b57f4` = `[3, 4, 0, 1, 5, 7, 8, 12,
10, 17]`, and uses the result as an index into the **resource slot table** at
`0x8011a328` (slot 0 at that address; slots −2/−1 live just below at
`0x8011a320`). Then `res = slots[slot]`: if `res->type == 1` it spawns directly
through `func_0x800f23f4(res->id, &pos)` (gated by `_DAT_8004d8ca`), if
`type == 3` it skips, otherwise it builds a 0xc0-byte crate object
(`FUN_800734e0/73558/73640`).

The slot table is filled from two independent places:

| slots | filled by | contents |
|-------|-----------|----------|
| 0, 1, 2, 5, 6, 10 | `FUN_800ea2dc` (GAME), from `M_CRATECONTENTS.BIN` | recipes R1…R6, **normal** |
| 7, 8, 9, 12, 13, 17 | same | recipes R1…R6, **MEGA** (`FUN_800ea46c` maps normal slot → mega slot) |
| −2, −1 | same, hardcoded | SUGAR (62), AMMO (63) |
| **3, 4** | **`FUN_800713b4` (ENG), from the mission's LEVELS.BIN record `+0x7c` / `+0x7e`** | two per-mission toy ids, `0xffff` = none |
| 11, 14, 15, 16 | nobody | always null |

So `which` resolves like this:

| which | slot | weapon |
|-------|------|--------|
| 0 | 3 | LEVELS.BIN `+0x7c` (per mission) |
| 1 | 4 | LEVELS.BIN `+0x7e` (per mission) |
| 2 / 3 / 4 | 0 / 1 / 5 | recipe R1 / R2 / R4, normal |
| 5 / 6 / 7 | 7 / 8 / 12 | recipe R1 / R2 / R4, MEGA |
| 8 / 9 | 10 / 17 | recipe R6, normal / MEGA |

Confirmed on the running game: with INFORAPOUND loaded (`_DAT_8004d8ce = 0x1a`)
the live table held toy 49 in slot 0 — the R1 of *the mod's* set 26, not
vanilla's 42 — and slots 3/4 held 61 (ARMAGEDDON BARREL) and 57 (4-PACK
MISSILE), exactly the two u16 at `+0x7c`/`+0x7e` of mission 26's record.

Campaign levels use `which = 0` or `1`, i.e. the two per-mission ids — that is
what "hidden weapon" means in practice: **a level-specific weapon, usually one
from a later world**. The multiplayer maps instead use `which = 3…7`
(symmetric pairs), so they pull from the crate recipes and their `+0x7c`/`+0x7e`
are `0xffff`.

---

## PND — terrain and objects

```
offset  size  field
0       4     "PSM0"
4       8     n_models (u16), n_instances (u16), 65, 65
12      n_models*32   model name list (32 bytes each)
        n_instances*20 object instances (see below)
        <extra list>  static objects: u16 count + count*20-byte records
        65*65*2       heightmap (s16 per vertex)
        <intermediate section> multiple of 20 bytes (secondary instance list)
        64*64*28      tile records
        <animation queue> (see below)
```

### Object instances (20 bytes)

```
0   u32   model index (into the name list)
4   s16   x (world 0–512)
6   s16   altitude
8   s16   z (world 0–512)
10  s16   type/param (e-param: bases 134/138/141, trees 162–169, benches 30, flags 0/29)
12  s32   rotation field 1
16  s32   rotation field 2
```

The engine's level parser (`FUN_800a7fbc`, ENG) converts instances to world
coordinates as `wx = 64*x - 0x4000`, `wy = -64*alt`, `wz = 0x4000 - 64*z`
(world Y is down, so positive `alt` = up), and world maps to the tile grid as
`tile = (w + 0x4000)/512` (`FUN_800a79f4`). Hence
**`tile = (x/8, 64 - z/8)` — the z axis is mirrored, x is not** (same
transform as the extra list below). Instance `alt` equals the terrain height
under the object in vanilla data (mean |alt − h| ≈ 0 across all 45 levels —
a strong self-check for the frame).
`BSE_*` instances are the base buildings; moving one moves the base.

### Static-objects "extra list" (20 bytes)

Turrets and other static props. `u16 count` then records of ten u16:

```
0,1  (unused, 0 in vanilla)
2    x (world)
3    altitude (16)
4    z (world)   — mirrored vs tile grid: visual z = 512 - z
5    type        — indexes STATICS.BIN (see catalog)
6    (0)
7    rotation
8    (unused in vanilla) — repurposed as TEAM by the ENG patch
9    (0)
```

World transform: identical to object instances (`wx = 64*x - 0x4000`,
`wz = 0x4000 - 64*z` → `tile = (x/8, 64 - z/8)`). Spawn yaw =
`(-rotation) ^ 0x800` (`FUN_800a8780`). An old `(x + 18, ...)` empirical
calibration predated the exact tile-array offset fix and is obsolete.

### Heightmap, tiles, animation queue

- **Heightmap**: 65×65 grid of s16 vertex heights, row = z, col = x
  (`FUN_800ab6b0` samples vertex `(wx+0x4000)>>9 + ((wz+0x4000)>>9)*65` and
  bilinearly interpolates, picking the diagonal from the tile's flag bits 1–2).
  Runtime scale (`FUN_800a9744`): `h_world = -64 * h_file` — with 512 world
  units per tile that is **h_file/8 tiles, positive = up** (values are −20…56
  in vanilla, steps of 4 ≈ half a tile). Instance `alt` uses the same unit.
- **Tiles**: 64×64 records of 28 bytes:
  `[u16 atlas U (0–1023)][u8 V][4× s8 corner deltas in {0,±63} = 8 orientations]
  [u8 clut] + 16 bytes vertex colors (RGBA×4) + u32 flag`.
  ⚠️ The UV base corner is the **south** vertex of the quad, not the north one:
  after applying the delta-derived affine you must flip the sampled cell
  vertically or every sprite renders mirrored (absolute proof: the pads'
  painted arrows must all point toward the pad center).
  ⚠️ The engine reserves **32 bytes per tile** in memory (28 used → 16 KB of
  padding), so the animation queue starts at `tiles_start + 64*64*32 = +131072`,
  not right after the file records.
- **Animation queue** (`tiles_start + 131072`):
  `s16 n_tex` + `n_tex * 12-byte` animated-texture records, then
  `u16 n_desc` + `n_desc * 16-byte` descriptors whose field 0 is a **tile index**
  (`z*64 + x`). The animated pad arrows are 4 descriptors over the pad's center;
  moving a pad remaps them (`editor_server._repaint_pad`).

The tile array starts at an **exact, fully sequential offset** — there is no
mystery gap:

```
off_extra = 12 + n_names*32 + n_inst*20
tiles     = off_extra + 2 + extra_cnt*20 + 65*65*2
```

(Historical note: an earlier heuristic located the array by scanning for a run
of valid-looking records; the tail of the heightmap usually passes that test,
so it locked on ~2 records early — shifting the whole map by 2 tiles and
wrapping the rightmost columns to the left edge one row down. Don't do that.)
Note the clut index goes well past 120 on the biggest levels (COUNTRYVILE uses
138 CLUTs).

---

## Crate recipes (BIND 0953)

Member layout: ten config files (TOYS, POWERUP, PROJECTILES, WEAPONS, VEHICLES,
ACTION, PERCEPT, ATTITUDE, BUDDIES, STATICS), then 41 `N_CRATECONTENTS.BIN`
(28 bytes: `u32 6` + six `u16` pairs normal/mega in the 180-toy space), then
25 `N_BT_*.BIN` label files.

Recipes are **per mission**, not per world: `FUN_80083304` (ENG) is called with
`a0 = _DAT_8004d8ce` (the mission index) and picks BIND member `mission + 10`
— and the CRATECONTENTS files start exactly at member 10, so **mission M uses
`M_CRATECONTENTS.BIN`**. `_DAT_8004d8d4` overrides the index when it is not -1
(written by ENG `0x800a5368` and GAME `0x800f14b0`). The `N_BT_*.BIN` names
(PARK_AREA, JUNGLE_AREA, ALL_FLAME_WEAPONS…) are just labels on some of the
indices — they do **not** group missions.

---

## LOD — 3D models (MDL.BND)

Each level's `MDL.BND` is a BIND of `*.LOD` model files (validated on all 121
unique models across the 45 levels; parser in `tools/tb_lod.py`):

```
file:   char name[32]   u32 (0x80000000 | n_lod)   lod_block × n_lod
lod:    u32 0x28   u16 959 (version)   u16 n_parts   char name[32]   part × n_parts
part:   u32 0x48   header[72]   geometry[gsz]
header: u32 0x7fc0   u32 ?   u32 RGB base color (0x7f7f7f = neutral)
        bbox min/max as 2×(3×s16 + pad)   char tex_name[8] ("no_tex!" = none)
        char bound_name[28]   u32 0   u32 gsz
```

Bytes after the first NUL of every name field are exporter garbage (stale heap),
not zeroes. `tex_name` refers to a TIM inside the level's `TIM.BND` (matched
case-insensitively, `.TIM` appended). A `.LOD` may hold up to 3 levels of
detail; the richest one (most vertices) is the display model.

**Geometry** is a stream of `u32` tags `[u16 code][u16 aux]`, `0x00000000`
terminated, driving a **15-slot vertex register file** (a GTE-friendly
vertex cache):

- `code` packs three fields: `f0 = (code>>10)/4 − 1`, `f1 = ((code>>5)&31)/2 − 1`,
  `f2 = (code&31) − 1`.
- `aux` bit15 = 0 → **vertex load**: 36 bytes follow = 3 vertices + 3 normals,
  stored into slots `f2, f1, f0` (in that order). The 18 s16 payload layout is
  scrambled: `[a0 b0 a1 b1 a2 b2 c1 c2][n1c n2c][n0a n0b n1a n1b n2a n2b][c0 n0c]`
  where vertex k = `(ak, bk, ck)` with normal `(nka, nkb, nkc)`, |n| ≈ 4096.
  A load tag is *not* a face.
- `aux` bit15 = 1 → **primitive**: `v0 = f0`, `v2 = f1`, `v3 = f2` (slot
  indices); `v1 = ((aux&0xff)>>2) − 1`, negative → triangle `(v0,v2,v3)`,
  else quad `(v0,v1,v2,v3)` in **perimeter order** (triangulate as a fan
  `(v0,v1,v2)+(v0,v2,v3)`, *not* as a PSX strip).
- `aux` bit14 = 1 → 8 bytes of UVs follow (4 × u8 pairs in vertex order,
  pixel coordinates into the part's TIM; triangles use 3 + padding).

Model axes: `a` = vertical (positive up), `b`/`c` horizontal; 1 tile = 512
model units (= 64 × the 0–512 world-data unit). Untextured parts use the header
RGB as flat color; TIM color 0 is transparent (alpha-tested foliage).

**Coordinate frames** — all derived from the engine code (`FUN_800a7fbc`
world conversion + `FUN_800a79f4`/`FUN_800ab6b0` world→tile indexing), and
cross-checked in data (instance `alt` ≡ terrain height; pad↔base claiming
distances):

| entity                | tile-frame position                  |
|-----------------------|--------------------------------------|
| PLD s0 / s6 / s3      | direct (`tile = 32 + s16(raw)/512`; raw s0/s6 values are world units) |
| tile array, heightmap | row = z, col = x (not mirrored vs world) |
| PND instances         | `(x/8, 64 − z/8)` — z mirrored       |
| PND extra list        | `(x/8, 64 − z/8)` — same transform   |

World Y points down (`h_world = -64*h_file`, `wy = -64*alt`), so a rotation
by `+θ` about world Y appears as `−θ` in a Y-up viewer. Instance yaw comes
from `r1`: angle = `(r1>>16) & 0xfff` (`0x1000` = full turn), flipped to
`0x800 − angle` when `|s16(r1 & 0xffff)| > 500`; the runtime stores the
negated angle. Extra-list spawn yaw = `(-rotation) ^ 0x800`.

---

## Object catalogs

### Units — the 62 space (PLD s6 `type`)

DAT entry **958** is a BIND of **62 `ST*.BIN` files, one per table slot, in
order** — this is the authoritative catalog of s6 types (the engine walks the
BIND entries and the runtime table `DAT_80119b00` in parallel, `FUN_800834bc`).
Verified in game: 15=`STLION`, 22=`STPIG`, 32=`STSHEEP`.

```
0–7   buddies: COMMANDO, ST, KUNGFU, MEDIC, STEALTH, SUPER, ESKIMO, LEGION
8–29  humans/animals: FARMER, SHEPHERD, YETI, BAYWATCH, TARZAN, PENGUIN,
      POLARBEAR, LION, HIKER, RAM, MONKEY, CAMEL, BULL, HORSE, PIG, LIZARD,
      SEAL, GRIZZLY, DOG, CAT, PUFFIN, DOG
30    PRETTY (per-team objective)   31 CYBORG   32 SHEEP   33 NINJA   34 GHOST
35    HOSTAGE (objective)           36–43 DUMMY1–8 (empty)
44    FROZENSCIENTIST (objective)   45 CAMELSUPPLY
46–48 MECHLASER, MECHBOSS, MECHGATLING
49    BOMBDOG (objective)           50 TARGETDOG   51 SCIENTIST2   52 BADDIE
53    ALIEN   54 HOOLEYALIEN   55 WOLF   56 SCIENTISTCP   57 EWEBOSS
58–61 CAPTURE PIG / PENGUIN / SHEEP / DOG
```

Types 30/35/44/49 take a special path in the spawner (added to a per-team
objective list via `+0xa6` on the type struct). Preload is self-feeding from s6,
so a placed unit brings its own resources (a placed lion spawns anywhere).

#### Hard limit: 20 preload entries (a level with too many units won't load)

The preload pass is `FUN_800e2bb8` (GAME). It builds the list of unit types to
register in a **20-entry `u16` array on the stack** (`sp+16`, frame
`addiu sp, sp, -80`, saved regs at `s0@56 s1@60 s2@64 s3@68 s4@72 ra@76`) and
there is **no bounds check anywhere**. The list gets:

* 1 fixed entry (type 1);
* +1 type 0x22 when `_DAT_8004d8da == 1`, +1 type 0x32 when `iRam8004d8dc != 0`;
* +3 (0x30/0x2e/0x2f) on mission 0x16, +1 (0x39) on mission 0xe;
* +1 for every crate-recipe slot whose resource has class 3 (i.e. a recipe that
  yields a *unit*), scanning slots 17→0;
* **+1 per s6 record — not per distinct type.** Ten legionnaires cost ten
  entries; `DAT_80119b00[type]` is indexed by type, so the duplicates just
  overwrite each other and leak 0xc4 bytes each (`FUN_800e2ebc` →
  `FUN_80074584(3, type)` is a lookup, not a load, so no model is duplicated).

Consequences of overflowing, byte-exact:

| entries | write lands on | effect |
|---------|----------------|--------|
| 21…30 | saved `s0`…`s4` (`sp+56`…`sp+75`) | the caller resumes with corrupted registers → bad access → freeze on a **black screen right after loading** |
| 31+ | saved `ra` (`sp+76`) | `jr ra` jumps into garbage |

Vanilla never gets close: the busiest level is INFORAPOUND with 13 records (2
distinct types), then INFLAMMABLECANNIBALS with 10. **Keep the total s6 record
count ≤ 16** and there is headroom for the system entries in every mission.

The limit is liftable: patch E in `tools/tb_patch_eng.py` grows the frame to 168
(`-80 → -168`, the 12 saved-register offsets shifted by +88) so the buffer at
`sp+16` holds `PRELOAD_SLOTS = 64` entries. Nothing else depends on the count —
`uRam8010e6c0` is written and never read, and `DAT_80119b00` is indexed by type
(62 slots), not by entry. What still scales per record is the preload
allocation `FUN_8003d44c(entries * 0xc4)`: 64 entries ≈ 12.5 KB against
vanilla's ≈ 2.5 KB, and that allocator returns **0** when the arena is short,
which would leave `DAT_80119b00[type]` pointing near address 0 — the next
suspect if a level with very many units still fails to load.

#### The REAL hard limit: the unit pools (9 buddy-class slots)

The preload buffer was only the first ceiling. The engine keeps four
fixed-capacity unit pools, initialised in GAME (`0x800e3400`) by
`FUN_8007490c(desc, cap)` and allocated from with `FUN_800749c4` (a free-index
list). Their entry arrays are **packed back-to-back in BSS with zero slack**:

| pool | desc (GAME) | cap | array | stride | what |
|------|-------------|-----|-------|--------|------|
| 1 | 0x8010e6c4 | 16 | 0x801124ec | 0x3a4 | vehicles / big objects (`FUN_80070e48`) |
| 2 | 0x8010e6dc | **9** | 0x80110524 | 0x388 | **buddies, humans, mechs** (`FUN_80071440`: types 7, 8, 10, 13, 18, 35, 46-48, 51-53, 56-57 + class 2/4) |
| 3 | 0x8010e6f4 | 8 | 0x8010e724 | 0x3c0 | animals (types 15, 20, 55 + class 1) |
| 4 | 0x8010e70c | 17 | 0x80115f2c | 0x10 | small per-unit records |

**The bug (vanilla)**: when a pool is exhausted, `FUN_800749c4` returns the
sentinel index **0x8000**; no caller checks it. The alloc helper then writes to
`array + (-32768) * stride` — for pool 2 that is `0x80110524 - 0x1C40000 =
0x7E4D0524`: a bus error, or (via the pointers derived from it) wild memory
corruption → the black screen the 10th buddy-class s6 unit causes. Measured
live: cap=9, count=10, cur=0x8000. Vanilla data never exceeds 8 same-class
units (WHORA's 8 legionnaires), so the game never hits it.

**The fix (patch F in `tools/tb_patch_eng.py`)**: the s6 spawner block in ENG
(`FUN_8006f5e4`, 0x8006f8f0-0x8006fa1c) is rewritten to check pool 2
(`count < 9`) and pool 1 (`count < 16`) before `FUN_80071440` and **skip the
record** (reusing the existing skip path at 0x8006f8e4) when full: the level
loads, the extra units simply don't spawn. The space for the guards comes from
caching `team*228` in s7 (dead in the block — reassigned at 0x8006fa24 before
any use) and absorbing the load-delay nops. Same window also caps the per-type
spawn-point array at 8 (see above). NB the menus' 3D world scene and the
attract demos run through this same spawner (MNU mirrors the pool layout), and
the R3000 load-delay slot is real: an early version of this patch that used a
loaded register in the next instruction corrupted every unit's team pointer.

**Patch G (tb_patch_eng.py) lifts the pool to 24 slots** by relocating the
array to `0x801E6114` — the top 0x5600 bytes of RAM made permanently
allocator-free by shrinking the heap-arena size in its init (SYS `0x8003d41c`:
the alignment `and` becomes `addiu size, size, -0x5600`; every mode's arena
ended ≤ 0x801EB714, so every mode now ends ≤ the new base). Rebased refs: 3 in
ENG, 7 lui/addiu pairs + 2 loop counts (8→23) + the walk bound (9·904→24·904)
+ the init cap in GAME. Crucially the entries also need **global IDs**:
`FUN_800e3458` reserves a block of `16+8+9 = 33` ids (`FUN_80040a98(33)`) for
pool1+pool3+pool2 — grown to `16+8+POOL2_CAP`; without this the extra entries
get ids the allocator hands out again later (handle-table aliasing → circular
lists). MNU/MPLR never touch the pools (zero references) so only ENG+GAME+SYS
are involved.

**Patch H fixes the root allocator**: `FUN_800749c4` (the generic fixed-cap
free-list allocator used by pools, team rosters, everything) has NO exhaustion
check in vanilla — on a full list it reads `free[count]` past its own carved
array (the arena packs them back-to-back, so that's the neighbour list's data)
and links garbage indices: circular lists, wild writes. Rewritten in-place
(28 words) to return a clean `0xffff` when `count >= cap`. Callers that check
-1 (e.g. the roster attach `FUN_80078d34`) now fail gracefully: a unit beyond
the **6-per-team roster** still spawns, it just isn't registered as a team
member (the 6-slot member array at team+0x38 is inline in the 0xe4-stride
struct — growing it would need another relocation).

Remaining practical limits with all patches applied: 24 pool slots for
buddy/human/mech units (shared with runtime crate-spawned units), 6 roster
members per team (extras spawn unregistered — spread units over two teams like
vanilla WHORA's 4+4 to stay native), 8 spawn-points per type (9th+ of the same
type spawn without a respawn slot).

### Static objects (PND extra list `type`)

DAT entry **953** → `STATICS.BIN`: `u32 version + u32 count(=188)` then 64-byte
records with a **name in the first 32 bytes** followed by 8 u32 fields; the extra
list's `type` indexes it 1:1 (built into the runtime table by `FUN_80093a44`,
stride 0x48, read from `DAT_800bffb0`).

Highlights: 0 Bases; 1–13 trees/cacti; 16–21 rocks; 30–35 buildings;
**113 Turret Cannon** (enterable; shows "Torretta 1" in game), 115 Cannon(Auto),
116 Turret Gatling, 117 Gatling(Auto), 121 Homing(Auto), 122/123 Flame,
124/125 Ice, 126/127 Laser, 128/129 FourPack, 130 Lightening, 131/132 DeathRay,
133 Turret_Homing(enterable); 134/138/141–146 per-world bases;
149–175 power-up trees/buildings (Tree Jetpack, Building Shield…);
185 Ewe Fiend Teleporter Node; 186 Frozen Scientist.

> An earlier hypothesis mapped `type = toy_id + 26` against the 180-name toy
> table (entries 15/16). That was a coincidence of names and is **wrong**:
> 117 is "Gatling (Auto)", not the toy-table "Ankh". Always use STATICS.BIN.

### Crate build recipes

DAT entry **953** per-area `N_CRATECONTENTS.BIN` / `BT_*_AREA.BIN`: `count` +
u16 pairs `(normal_toy, upgraded_toy)`, one pair per crate. Toy IDs index the
180-name table (`toy_names_it.txt`, `id = string_index - 1`). Verified in game
(a flame-tank recipe built the expected toy).

### Other config (entry 953)

`TOYS.BIN` (180 × 12-byte records: class, index-in-class, f2),
`VEHICLES.BIN` (84 × 176-byte, model at +72), `WEAPONS.BIN`, `POWERUP.BIN`,
`PROJECTILES.BIN`, `PERCEPT.BIN`, `ATTITUDE.BIN`, `ACTION.BIN`. Turret models are
DAT entries 1150–1165.

---

## Engine notes

- **Level loader** `FUN_800a7cec` (ENG.BIN): accesses BIND entries by index
  (0=TIM, 1=TIM.BND, 2=MDL.BND, 3=PLD, 4=PND, 5=CL2, 6=PTH), copies the PLD to
  RAM at `0x800c04f8`.
- **Base ownership → team.** A base takes the team of the nearest s0 spawn; a
  spawn's team owns the nearest base. This is dynamic, so spawning next to an
  enemy base can flip it. Pads are recolored at runtime (blue = unowned).
- **Placed-object team** `FUN_800a8780`: at load each extra-list object is given
  the team of the nearest **owned base** instance (scan of `DAT_800bd900`,
  stride 0xf4, flag&1, owner ≠ dummy). In practice only AI bases are owned at
  that moment, so a placed turret is always hostile to the player — which is why
  the team patch (below) exists.
- **MIPS load bases** (for Ghidra headless, import one binary at a time):
  SCES `0x80014dec`, ENG.BIN `0x80051954`, GAME.BIN `0x800c4240`,
  SYS.BIN `0x80038f80` (from OVERLAY.DAT).

---

## The ENG.BIN team patch

`tools/tb_patch_eng.py` gives placed extra-list objects a real team field, since
the on-disc format has none.

- **Field**: `f8` (record offset +0x10, always 0 in vanilla) becomes the forced
  team. `0` = vanilla behaviour (nearest-base scan preserved), `1–4` = team.
- **How**: two in-place rewrites, no code cave (the compiler's load-delay `nop`s
  are absorbed; ~38 instructions total):
  - **Parser** (`0x800a835c–0x800a83bc`): the runtime rotation word becomes
    `(-rot & 0xfff) | (f8 << 12)` — team smuggled in the high bits of rotation.
  - **Assignment** (`0x800a8780`, `0x800a8830–0x800a8908`): extract the team from
    the high bits, mask rotation back to `0xfff`; if team ≠ 0 write it to
    `+0x238` and skip the scan, else run the original (recompacted) scan.
- **Safety**: vanilla bytes are verified before patching, the patch is
  idempotent, `ENG.BIN.orig` is created as backup, and `--revert` restores it.
- **Caveat**: in the game mode that already forces team 1 (`_DAT_8004d8ce==0x1e`)
  the field is ignored (the branch precedes the read). ENG.BIN ends exactly where
  GAME.BIN begins in RAM, so there is no slack for a code cave — hence the
  in-place approach.

Verified on real gameplay: a team-1 auto turret ignores the player and fires at
enemies.

---

## PAD0 — skeletal animation data (.PAD)

Every animated global model folder (buddies, animals, weapons) pairs its
`.LOD` with an `AGENTn.PAD` / `WEAP_n.PAD` file:

```
0    "PAD0"
4    u16 n_frames
6    u16 n_bones            (== part count of the paired .LOD)
8    per bone: char name[32] + n_frames * 8-byte frame records
```

Bone names are meaningful: `bone_back`, `bone_heel_l/r`, `bone_toes_l/r`,
`bone_palm_l/r`, `bone_fing_l/r`, `eyes` (Commando); `backbone`,
`l_front_hoof_bone`, `tail_bone`, `exit_1_lion` (Lion).

### The 8-byte frame record

Recovered from the running game with a read watchpoint on a PAD buffer in
RAM: the evaluator is `FUN_800ADDA0` (ENG) and the unpacker it calls is at
`0x800B1778`. Reader: `tools/tb_pad.py`.

```
w0, w1 = u32 LE pair
rot_x = ((w0 >> 16) & 0xff) << 4        PSX angle units, 0x1000 = full turn
rot_y = ((w0 >>  8) & 0xff) << 4
rot_z = ( w0        & 0xff) << 4
tx    = s16( (sra(w0 << 1, 19) & 0xffc0) | (w1 >> 26) )    14 bits
ty    = s16(  sra(w1 << 6, 19) )                           13 bits
tz    = s16(  sra(w1 << 19, 19) )                          13 bits
```

So each frame packs 3 rotations at 8-bit precision (scaled ×16) plus a
signed translation, in the model's y-down space (a Lion's legs come out at
±x, front/rear at ±z, the tail behind — an unambiguous sanity check).

The evaluator negates the three angles (`subu` + `andi 0xfff`) before
building the matrix (`0x800b0e84`) and writes 32-byte PSX `MATRIX` entries;
the animation table itself is `R_ANIMATIONS.BIN` (member 5 of the 0955 BIND,
parser `FUN_800958a4`, 0x8c runtime structs at `DAT_800bcae4`, channel
bookkeeping in `FUN_80095d64`).

**Still open — posing a model:** applying `v' = R·v + T` per part scatters
the parts, because `.LOD` vertices are already in a rest pose in model
space: the bone transform must be applied as a *delta* against a bind pose
that has not been identified yet. Until then the editor previews models
statically (turrets get a data-driven rest-pose approximation).

Turret models have **no PAD**: their assembly comes from elsewhere
(VEHICLES.BIN records or code).
