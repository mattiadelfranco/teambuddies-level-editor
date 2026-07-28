# Team Buddies — Mappa dell'engine (progetto Ghidra TB_PSXLDR)

Progetto: `ghidra/proj_psxldr/TB_PSXLDR` — importato col plugin **ghidra_psx_ldr**
(loader PSX, linguaggio `PSX:LE:32` con GTE, firme PSY-Q applicate).
Il vecchio progetto `ghidra/proj/TB` resta per i dump storici.

## Toolchain originale
- Compilatore **SN Systems** (`__SN_ENTRY_POINT`, `__sn_cpp_structors`) — il gioco è **C++**.
- PSY-Q SDK: libreria interamente linkata in SCES (816/999 funzioni riconosciute
  dalle firme: libgpu, libgs, libspu, libcd, libsnd, MDEC/`DecDCT*`, `StCdInterrupt`…).
- Elenchi nomi: `ghidra/psxldr_sces_names.txt` (+ `_SYS/_ENG/_GAME/_MNU`).

## Boot e main loop (SCES)
- `start` → `__SN_ENTRY_POINT` (0x8001acb8): azzera BSS, `InitHeap`, → `FUN_80019d08` = **main**.
- `FUN_80019d08` = macchina a stati di alto livello: apre `\OVERLAY.DAT;1`,
  carica gli overlay e orchestra menu ↔ partita tramite una **jump table di
  entry point a 0x80010184** (`DAT_80010204[0..0x11]`, riempita a runtime).
  Codici di ritorno del menu/gioco decidono lo stato successivo (0xf=ripeti,
  10=reboot, 2=avvia missione, 0xc=tutorial, …).
- **Missioni**: `DAT_8004d8ce` = indice missione; `>= 0x20 → reset` ⇒
  **campagna = missioni 0–31, multiplayer = 32–47** (48 slot totali).
  Livello caricato da `FUN_800a7cec(d8ce + 0x201)` (id loader → entry DAT 512+missione).

## OVERLAY.DAT
Directory nei primi 0x200 byte, record da 0x30: `[nome 0x20][load][size][ctor_start][ctor_end]`:

| slot | file | load | note |
|---|---|---|---|
| 0 | SYS.BIN  | 0x80038f80 | "OS di gioco": resource manager, allocatore |
| 1 | ENG.BIN  | 0x80051954 | engine: oggetti, team, spawn, livelli |
| 2 | LNG.BIN  | 0x800c4240 | lingua |
| 3 | MPLR.BIN | 0x800c4240 | setup multiplayer |
| 4 | MNU.BIN  | 0x800c4240 | menu |
| 5 | ROT.BIN  | 0x800c4240 | (intro/attract?) |
| 6 | GAME.BIN | 0x800c4240 | logica di gameplay |
| 7 | TUTO.BIN | **0x8011a7e4** | tutorial, convive con GAME |

- `FUN_8001a3f4(slot)` = carica overlay: `CdSearchFile` + lettura asincrona
  (`FUN_8001aadc`, attesa su `DAT_80010218&1`) + **esecuzione dei costruttori
  C++ statici dell'overlay** (`__sn_cpp_structors(ctor_start, ctor_end)`).
- I "ctor" degli overlay sono le **inizializzazioni dei sottosistemi**: in GAME
  costruiscono pool statici di oggetti C++ con vtable (es. 16×0x3a4, 9×0x388,
  16×0x3c0 in FUN_800e4230) e li registrano nelle liste di ENG. Pattern comune:
  `FUN_xxx(1,0xffff)` = costruisci, `(0,0xffff)` = distruggi.
  ENG ctors: 0x8006e8fc 0x80073498 0x80075740 0x80082180 0x80085e60 0x80096754
  0x80096d00 0x800a0c18 0x800a730c 0x800adbf4 0x800ae0c4.
  GAME ctors: 0x800cedc0 0x800e4454(zone casse) 0x800e53a8(pedane) 0x800e6678
  0x800eb878 0x800ebb78 0x800ec17c 0x800edc9c 0x800f0650 0x800f2aa4 0x80103d50 0x801071cc.
- `FUN_8001abdc(size)` = ridimensiona l'arena heap dopo il load (heap inizia
  dopo l'overlay caricato).

## Resource manager (SYS.BIN)
- Tabella del BUDDIES.DAT **copiata in RAM** a `0x800450e4` (size,sector per id).
- `FUN_8003d234(id, lato)` = carica entry per **id = indice DAT** (id*8 nella
  tabella): alloca `FUN_8003d44c`, lettura CD asincrona con la stessa primitiva
  degli overlay (`FUN_8001aadc`).
- `FUN_8003d0cc(id, modo)` = carica con **retry di robustezza**: se il buffer non
  inizia con `"BIND"` (0x444e4942) libera l'allocazione (`FUN_8003d5c4` = free
  dell'ultimo alloc) e RIPROVA la lettura CD. Niente compressione ✓.
- **Allocatore a doppio stack** (lato 0 = basso, 1 = alto) con mark stack:
  `FUN_8003d754(lato)` = push mark, `FUN_8003d7b4(lato)` = pop (libera tutto
  dal mark). Ogni fase di load è incorniciata da push/pop. `DAT_8004949c` = spazio libero.
- `PTR_DAT_80043d10[id]` = tabella nomi entry (solo ~189 popolate: font/splash/menu
  → estratte in `teambudd/dat_names.txt`).

## Sistema oggetti/risorse (ENG.BIN)
- `FUN_800ad934(pool, slot, "NOME")` = registra risorsa per nome nel pool
  (9 pool in `DAT_800c0a60`); `FUN_800ad894(nome)` = risolve nome→id risorsa.
- `DAT_800c05d8[id]` = **cache globale dei caricati** (0x122 = 290 slot, puntatori).
- `FUN_800adad8(out, pool, slot)` = puntatore alla risorsa caricata.
- `FUN_800ada68()` = alloca handle entità da free-list (`FUN_800749c4(&DAT_800bd974)`,
  record da 0xc in `PTR_DAT_800be724`).
- Liste/registrazione oggetti runtime: `FUN_80074834/FUN_80074848` (usate dai
  ctor di GAME per i pool).

## Level-setup (ENG, già noto + conferme)
`FUN_800a4568` = setup missione: crea team (loop su `_DAT_8004d8c8`),
`FUN_800a7cec(d8ce+0x201)` carica il BIND livello (entry per indice: TIM,
TIM.BND, MDL.BND, PLD, PND, CL2, PTH), `FUN_800702f4(mode, LEVELS.BIN)` applica
la config di gameplay per-missione, `FUN_8007075c` decide i team effettivi
(min(config, count s0)), poi spawn s6/istanze/statici.
`0x800209dc` = `rand` ✓, `0x800205ac` = `VSync` ✓, `0x8003b19c(n)` = attesa n frame.

## File di riferimento
- `ghidra/psxldr_overlay_loader.txt` — loader overlay decompilato
- `ghidra/psxldr_sys_resmgr.txt` — resource manager decompilato
- `ghidra/psxldr_eng_objsys.txt` — sistema oggetti ENG decompilato
- `ghidra/psxldr_*_names.txt` — funzioni riconosciute dalle firme PSY-Q
- `teambudd/dat_names.txt` — nomi reali delle entry DAT (dove presenti)

## Jump table e game loop (RISOLTI)
- La jump table NON viene scritta dagli overlay: **sta negli ultimi 0x80 byte
  di OVERLAY.DAT** (file offset 0x180, caricati a 0x80010184 insieme alla
  directory). Tutte le 18 entry puntano a **SYS.BIN** (kernel residente che
  smista agli overlay):
  - `entry[2]` = 0x8003a7e4 **loop menu**: chiama il tick MNU (0x800cd508) ogni
    frame; ~25s di inattività → ritorna 2 = avvia demo.
  - `entry[3]` = 0x8003a918 **demo/attract**: gira la stessa macchina a stati
    del gioco ma cambia buddy seguito ogni 375 frame e randomizza l'azione
    (+0x3c) ogni 250 — il CPU "gioca da solo".
  - `entry[4]` = 0x8003a89c **esegui missione**: `while (statetab[stato]() == 0)`.
  - `entry[8]` = 0x8003c9cc init arena con size (0x28a0 menu / 0x238c0 gioco).
- **Macchina a stati della missione**: tabella `0x800bd8ac` (dati ENG):
  - stato 0 = `FUN_800a4568` **setup missione** (crea team, carica livello…)
  - stato 1 = `FUN_800a512c` **tick per-frame** (pausa, quit col Select per
    team, vittoria/sconfitta → stato 2, percorsi speciali demo e missioni
    0x1d–0x20, poi update del mondo)
  - stato 2 = 0x800a5800 fine/risultati; stati 3/4 = 0x800a4f88 abort.

## Prossimi scavi suggeriti
1. Dentro `FUN_800a512c`: la catena di update del mondo (oggetti→collisioni→
   camera→render OTag) e il punto di VSync/DrawSync.
2. I pool GAME (0x3a4/0x388/0x3c0): identificarli (casse? chute? effetti?).
3. Il tick menu MNU 0x800cd508 (per moddare il menu / sbloccare livelli).
4. Vtable delle classi C++ (metodo +0xc visto nei pool) → gerarchia oggetti.
