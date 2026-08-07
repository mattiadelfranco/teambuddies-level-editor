#!/usr/bin/env python3
"""
Team Buddies - Patch ENG.BIN: campo TEAM per gli oggetti della lista extra PND.

Il record file da 20B della lista extra non ha un campo team: al load
FUN_800a8780 assegna il team della base più vicina con proprietario, che in
pratica è sempre nemica (o nessuna). Questa patch usa il campo f8 (offset +0x10
del record, sempre 0 nei livelli vanilla) come TEAM FORZATO:

  f8 = 0     -> comportamento vanilla identico (scansione base più vicina)
  f8 = 1..4  -> il gioco scrive team = f8-1 in +0x238 della struct toy

Due riscritture in-place (niente code cave, si assorbono i nop di load-delay):
  A) parser PND (0x800a835c-0x800a83bc): rot runtime = (-rot & 0xfff) | (f8<<12)
  B) FUN_800a8780 (0x800a8830-0x800a8908): se rot>>12 != 0 -> team forzato,
     altrimenti scansione originale; rot sempre mascherata a 0xfff.
  D) Limite buddies per team 4 -> MAX_BUDDIES (default 5, max 6: il pool
     membri del team struct ha 6 slot nativi, +0x38..+0x4f, init a capienza 6
     in FUN_80078a94). Si alzano le 8 guardie "count > 3" (slti r,count,4):
     3 in ENG (0x800738f0 = costruzione alla pedana, 0x800924b8/0x800927ec =
     AI raccolta casse) e 5 in GAME.BIN (0x800ecbcc gate pedana,
     0x800eebd4/eec18/eed48/eed8c spawner missione) -> patch anche GAME.BIN
     (backup GAME.BIN.orig). NB HUD mostra 4 icone: il 5o buddy non ha icona.
  C) FUN_8007075c (0x8007082c): rimozione del tetto d8cc sul numero di team
     (bne del min() -> nop): le squadre = SEMPRE il count della config 0956
     (clampato al count s0 della mappa). Serve per >4 team; effetto collaterale
     possibile in multiplayer (il numero squadre scelto dal menu non limita
     piu'). Revert con --revert.
  E) Buffer del preload unita' in GAME.BIN (FUN_800e2bb8): 20 -> PRELOAD_SLOTS.
     La lista dei tipi da registrare sta in un array u16 a sp+16 con frame
     addiu sp,sp,-80 e registri salvati a s0@56 s1@60 s2@64 s3@68 s4@72 ra@76,
     quindi 20 voci; il loop dei record s6 ci appende UNA VOCE PER RECORD (non
     per tipo) senza alcun bound check, cosi' dalla 21a si corrompono s0..s4 e
     dalla 31a ra -> schermo nero appena finito il caricamento. La patch
     allarga il frame di DELTA = (PRELOAD_SLOTS-20)*2 byte e sposta i 12
     sw/lw dei registri salvati: il buffer resta a sp+16 e cresce nello spazio
     liberato. Costo: DELTA byte di stack (irrilevante) e 0xc4 byte di heap per
     record al preload (i duplicati sprecano, non ricaricano: FUN_800e2ebc usa
     FUN_80074584 che e' una ricerca).

Uso:  python3 tools/tb_patch_eng.py [--revert]
Backup automatico in ENG.BIN.orig. Idempotente.
"""
import struct, sys, os, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENG = os.path.join(ROOT, "teambudd/estratto/ENG.BIN")
BASE = 0x80051954
GAME = os.path.join(ROOT, "teambudd/estratto/GAME.BIN")
GAME_BASE = 0x800c4240
MAX_BUDDIES = 5   # 1-6 (limite fisico: 6 slot nel team struct)
BUDDY_CAP_ENG = [0x800738f0, 0x800924b8, 0x800927ec]
BUDDY_CAP_GAME = [0x800ecbcc, 0x800eebd4, 0x800eec18, 0x800eed48, 0x800eed8c]

# --- G: capienza del POOL UNITA' classe-buddy (vanilla 9) ---
# L'array vanilla (0x80110524, stride 0x388, 9 slot) sta in BSS incollato agli
# altri pool: per ingrandirlo va RILOCATO. Nuova casa: la cima dell'arena heap
# [0x801E6114..0x801EB714), resa irraggiungibile all'allocatore riducendo la
# size dell'arena di ARENA_STEAL nell'init (SYS 0x8003d41c: l'and di
# allineamento diventa addiu size,-0x5600; ogni modalita' finiva <= 0x801EB714,
# quindi ora finisce <= della nuova base: mai collisioni).
POOL2_CAP = 24
POOL2_STRIDE = 0x388
ARENA_STEAL = 0x5600
P2_NEWBASE = 0x801EB714 - ARENA_STEAL          # 0x801E6114
assert POOL2_CAP * POOL2_STRIDE <= ARENA_STEAL
P2_OLDBASE = 0x80110524

# --- E: capienza del buffer di preload unita' (vanilla 20) ---
PRELOAD_SLOTS = 64
PRELOAD_FN = 0x800e2bb8          # addiu sp,sp,-80
PRELOAD_EPI = 0x800e2eb8         # addiu sp,sp,80
PRELOAD_FRAME = 80
# indirizzo -> offset(sp) vanilla dei 12 salvataggi/ripristini
PRELOAD_SAVES = {0x800e2bbc: 72, 0x800e2bc4: 60, 0x800e2bcc: 64, 0x800e2bd4: 56,
                 0x800e2be4: 76, 0x800e2be8: 68,
                 0x800e2e9c: 76, 0x800e2ea0: 72, 0x800e2ea4: 68,
                 0x800e2ea8: 64, 0x800e2eac: 60, 0x800e2eb0: 56}
PRELOAD_DELTA = (PRELOAD_SLOTS - 20) * 2
assert PRELOAD_DELTA >= 0 and PRELOAD_DELTA % 8 == 0, \
    "PRELOAD_SLOTS deve essere >= 20 e (slots-20)*2 multiplo di 8 (sp allineato a 8)"

# --- mini assembler MIPS (solo il necessario) ---
R = {"zero": 0, "at": 1, "v0": 2, "v1": 3, "a0": 4, "a1": 5, "a2": 6, "a3": 7,
     "t0": 8, "t1": 9, "t2": 10, "t3": 11, "t4": 12, "t5": 13, "t6": 14, "t7": 15,
     "s0": 16, "s1": 17, "s2": 18, "s3": 19, "s4": 20, "s5": 21, "s6": 22,
     "s7": 23, "sp": 29, "ra": 31}

def I(op, rs, rt, imm):  # I-type
    return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xffff)

def SLL(rd, rt, sa):
    return (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | 0x00

def SRL(rd, rt, sa):
    return (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | 0x02

def RT(rs, rt, rd, funct):  # R-type aritmetica
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | funct

def LHU(rt, off, base): return I(0x25, base, rt, off)
def LBU(rt, off, base): return I(0x24, base, rt, off)
def LH(rt, off, base):  return I(0x21, base, rt, off)
def SH(rt, off, base):  return I(0x29, base, rt, off)
def LW(rt, off, base):  return I(0x23, base, rt, off)
def SW(rt, off, base):  return I(0x2b, base, rt, off)
def ANDI(rt, rs, imm):  return I(0x0c, rs, rt, imm)
def ADDIU(rt, rs, imm): return I(0x09, rs, rt, imm)
def SLTI(rt, rs, imm):  return I(0x0a, rs, rt, imm)
def SLTIU(rt, rs, imm): return I(0x0b, rs, rt, imm)
def LUI(rt, imm):       return I(0x0f, "zero", rt, imm)
def OR(rd, rs, rt):     return RT(rs, rt, rd, 0x25)
def ADDU(rd, rs, rt):   return RT(rs, rt, rd, 0x21)
def SUBU(rd, rs, rt):   return RT(rs, rt, rd, 0x23)
def JAL(target):        return (3 << 26) | ((target >> 2) & 0x03ffffff)
def JALR(rd, rs):       return (R[rs] << 21) | (R[rd] << 11) | 0x09
def BEQ(rs, rt, pc, target): return I(0x04, rs, rt, (target - pc - 4) >> 2)
def BNE(rs, rt, pc, target): return I(0x05, rs, rt, (target - pc - 4) >> 2)
def J(target):          return (2 << 26) | ((target >> 2) & 0x03ffffff)
NOP = 0


def words(d, ram, n):
    off = ram - BASE
    return list(struct.unpack_from(f"<{n}I", d, off))


def orig(d_orig, ram):
    """word originale a un indirizzo RAM (dal file .orig)"""
    return struct.unpack_from("<I", d_orig, ram - BASE)[0]


def build_patches(d_orig):
    o = lambda ram: orig(d_orig, ram)

    # --- finestra A: parser PND, 0x800a835c-0x800a83bc (25 word) ---
    A = 0x800a835c
    wA = [
        o(0x800a835c),            # lh   v0,0x8(s2)        (z)
        LHU("at", 0x10, "s2"),    # lhu  at,0x10(s2)       f8 (ex nop)
        o(0x800a8364),            # sll  v0,v0,0x6
        o(0x800a8368),            # subu v0,zero,v0
        o(0x800a836c),            # addiu v0,v0,0x4000
        o(0x800a8370),            # sh   v0,0x2(a1)
        o(0x800a8374),            # lhu  v1,0xe(s2)        rot
        SLL("at", "at", 12),      # sll  at,at,12          (ex nop)
        o(0x800a837c),            # subu v1,zero,v1
        o(0x800a8380),            # andi v1,v1,0xfff
        OR("v1", "v1", "at"),     # or   v1,v1,at          team nei bit alti
        o(0x800a8388),            # lhu  a0,0xa(s2)        tipo
        o(0x800a8384),            # sh   v1,0x4(a1)        (spostata: colma delay a0)
        o(0x800a8390),            # sll  v0,a0,0x3
        o(0x800a8394),            # addu v0,v0,a0
        o(0x800a8398),            # sll  v0,v0,0x3
        o(0x800a839c),            # addu v0,a2,v0
        o(0x800a83a0),            # lw   v1,0x18(v0)
        o(0x800a83a4),            # addiu s3,s3,0x1
        o(0x800a83a8),            # lw   v0,0x8(v1)
        o(0x800a83ac),            # addiu s2,s2,0x14
        o(0x800a83b0),            # sh   v0,0x6(a1)
        o(0x800a83b4),            # sltu v0,s3,a3
        o(0x800a83b8),            # bne  v0,zero,0x800a8348
        o(0x800a83bc),            # addiu a1,a1,0x8
    ]

    # --- finestra B: FUN_800a8780, 0x800a8830-0x800a8908 (55 word) ---
    B = 0x800a8830
    wB = [
        o(0x800a8830),                       # 8830 lhu v0,0x4(s0)     rot+team
        o(0x800a8834),                       # 8834 lh  v1,0x4f4(v1)   n istanze
        SRL("t3", "v0", 12),                 # 8838 team nei bit alti
        ANDI("v0", "v0", 0xfff),             # 883c rot pulita
        o(0x800a8838),                       # 8840 xori v0,v0,0x800
        BEQ("t3", "zero", 0x800a8844, 0x800a8858),  # 8844 f8==0 -> scan vanilla
        o(0x800a8840),                       # 8848 sh v0,0x3e(a3)  (delay: entrambi i path)
        ADDIU("t3", "t3", -1),               # 884c team-1
        J(0x800a8928),                       # 8850 salta scan e assegnazione
        SH("t3", 0x238, "a3"),               # 8854 (delay) +0x238 = team forzato
        BEQ("v1", "zero", 0x800a8858, 0x800a8928),  # 8858 count==0 -> niente
        NOP,                                 # 885c
        o(0x800a8844),                       # 8860 lui v0,0x800c
        o(0x800a8848),                       # 8864 addiu t5,v0,-0x2eb4
        o(0x800a884c),                       # 8868 move t3,v1
        # loop scan (compattato assorbendo i nop di load-delay)
        o(0x800a8850),                       # 886c lw  v0,0xb8(a2)
        o(0x800a889c),                       # 8870 lhu a1,0xc(a2)   (anticipata)
        o(0x800a8858),                       # 8874 andi v0,v0,0x1
        BEQ("v0", "zero", 0x800a8878, 0x800a88d8),  # 8878
        LHU("at", 0x8, "a3"),                # 887c (delay) x del toy
        o(0x800a8864),                       # 8880 lw  v0,0xbc(a2)
        LHU("t6", 0x8, "a2"),                # 8884 x dell'istanza
        o(0x800a886c),                       # 8888 lw  v1,0x144(v0)
        LHU("t7", 0xc, "a3"),                # 888c z del toy
        BEQ("v1", "t5", 0x800a8890, 0x800a88d8),    # 8890 owner dummy -> skip
        SUBU("v1", "t6", "at"),              # 8894 (delay) dx
        o(0x800a888c),                       # 8898 sll a0,v1,0x10
        o(0x800a8890),                       # 889c sra a0,a0,0x10
        o(0x800a8894),                       # 88a0 mult a0,a0
        o(0x800a8898),                       # 88a4 sh  v1,0x18(sp)
        SUBU("a1", "a1", "t7"),              # 88a8 dz (z istanza - z toy)
        o(0x800a88ac),                       # 88ac mflo a0
        o(0x800a88b0),                       # 88b0 sll v0,a1,0x10
        o(0x800a88b4),                       # 88b4 sra v0,v0,0x10
        o(0x800a88b8),                       # 88b8 mult v0,v0
        o(0x800a88bc),                       # 88bc mflo v0
        o(0x800a88c0),                       # 88c0 addu a0,a0,v0
        o(0x800a88c4),                       # 88c4 sltu v1,a0,t4
        o(0x800a88c8),                       # 88c8 beq v1,zero,0x800a88d8 (stesso target)
        o(0x800a88cc),                       # 88cc sh a1,0x1c(sp)
        o(0x800a88d0),                       # 88d0 move t4,a0
        o(0x800a88d4),                       # 88d4 move t0,a2
        o(0x800a88d8),                       # 88d8 addiu t2,t2,0x1   (stesso indirizzo!)
        o(0x800a88dc),                       # 88dc sltu v0,t2,t3
        BNE("v0", "zero", 0x800a88e0, 0x800a886c),  # 88e0 loop (nuovo start)
        o(0x800a88e4),                       # 88e4 addiu a2,a2,0xf4
        # coda: identica all'originale (stessi indirizzi)
        o(0x800a88e8), o(0x800a88ec), o(0x800a88f0), o(0x800a88f4),
        o(0x800a88f8), o(0x800a88fc), o(0x800a8900), o(0x800a8904),
        o(0x800a8908),
    ]
    assert len(wA) == 25 and len(wB) == 55, (len(wA), len(wB))

    # --- finestra C: FUN_8007075c, min(d8cc, count956) -> count956 ---
    # 0x8007082c: bne a0,zero,+4 (se d8cc<count salta il ricarico del count)
    C = 0x8007082c
    assert o(C) == 0x14800004, f"layout inatteso al cap team: {o(C):#x}"
    wC = [NOP]

    # --- finestra F: spawner s6 (FUN_8006f5e4), riscrittura completa del
    # blocco spawn (0x8006f8f0-0x8006fa1c, 76 word). Tre bug del gioco:
    #  1) POOL UNITA' (GAME 0x8010e6dc, array 0x80110524, stride 0x388,
    #     capienza 9): l'allocatore FUN_800749c4 a pool esaurito ritorna
    #     l'indice sentinella 0x8000, il chiamante lo usa senza controlli:
    #     entry -32768 = 0x7E4D0524 -> bus error / puntatori marci ->
    #     SCHERMO NERO dopo il caricamento col 10o buddy (misurato live:
    #     cap=9, count=10, cur=0x8000). Guardia: count>=9 -> salta il
    #     record (l'unita' non spawna, il livello carica).
    #  2) POOL OGGETTI-UNITA' (0x8010e6c4, cap 16): stessa struttura senza
    #     controlli. Guardia: count>=16 -> salta il record.
    #  3) array spawn-point per TIPO (DAT_80119b00[tipo]+0x64, 8 slot,
    #     contatore +0x62): il 9o record dello stesso tipo scrive coordinate
    #     su +0xa4.. (lista obiettivi). Guardia: n>=8 -> niente store.
    # Lo spazio per le guardie viene dal cache di team*228 in s7 (morto nel
    # blocco: viene riassegnato a 0x8006fa24 prima di ogni uso) che elimina
    # due ricomputazioni, piu' i nop di load-delay. Il percorso di skip
    # riusa quello esistente a 0x8006f8e4 (s7=s3-1; j 0x8006fa8c; s1+=8).
    F = 0x8006f8f0
    assert o(F) == JAL(0x80071440), f"layout inatteso spawner: {o(F):#x}"
    assert o(0x8006f8f4) == ADDU("a0", "a2", "zero")
    assert o(0x8006f9b8) == JALR("ra", "v0"), f"jalr inatteso: {o(0x8006f9b8):#x}"
    assert o(0x8006fa1c) == SH("v0", 0x62, "s2")
    assert o(0x8006f8e8) == J(0x8006fa8c) and o(0x8006f8ec) == ADDIU("s1", "s1", 8)
    wF = [
        LUI("at", 0x8011),                    # f8f0
        LW("at", -6432, "at"),                # f8f4  count pool unita' (0x8010e6e0)
        ADDU("a0", "a2", "zero"),             # f8f8  arg tipo (riempie il load-delay)
        SLTI("at", "at", POOL2_CAP),          # f8fc
        BEQ("at", "zero", 0x8006f900, 0x8006f8e4),  # f900  pieno -> skip record
        LUI("v1", 0x8011),                    # f904  (delay, innocua)
        LW("v1", -6456, "v1"),                # f908  count pool oggetti (0x8010e6c8)
        NOP,                                  # f90c  load-delay
        SLTI("at", "v1", 16),                 # f910
        BEQ("at", "zero", 0x8006f914, 0x8006f8e4),  # f914  pieno -> skip record
        NOP,                                  # f918  (delay)
        JAL(0x80071440),                      # f91c  crea unita'
        NOP,                                  # f920  (delay, a0 gia' pronto)
        LBU("a0", 3, "s1"),                   # f924  route id
        JAL(0x80082054),                      # f928
        ADDU("s0", "v0", "zero"),             # f92c  (delay) s0 = unita'
        SW("v0", 0x310, "s0"),                # f930  route
        SH("zero", 0x314, "s0"),              # f934
        LBU("v0", 2, "s1"),                   # f938  team
        NOP,                                  # f93c  load-delay del R3000!
        SLL("a0", "v0", 3),                   # f940  team*228 (57*4)
        SUBU("a0", "a0", "v0"),               # f944
        SLL("a0", "a0", 3),                   # f948
        ADDU("a0", "a0", "v0"),               # f94c
        SLL("a0", "a0", 2),                   # f950
        ADDU("s7", "a0", "s4"),               # f954  s7 = &team (cache)
        ADDU("a0", "s7", "zero"),             # f954
        JAL(0x80078b4c),                      # f958
        ADDU("a1", "zero", "zero"),           # f95c  (delay)
        ADDU("a0", "s7", "zero"),             # f960
        JAL(0x80078d34),                      # f964
        ADDU("a1", "s0", "zero"),             # f968  (delay)
        ADDU("a0", "s0", "zero"),             # f96c
        JAL(0x8005469c),                      # f970
        ADDU("a1", "s7", "zero"),             # f974  (delay)
        LHU("v0", 4, "s1"),                   # f978  x
        LHU("v1", 6, "s1"),                   # f97c  z (riempie il gap)
        SH("v0", 8, "s0"),                    # f980
        ADDIU("a0", "s0", 8),                 # f984
        JAL(0x800ab6b0),                      # f988  quota terreno
        SH("v1", 12, "s0"),                   # f98c  (delay)
        SH("v0", 10, "s0"),                   # f990  alt
        LW("v0", 8, "s0"),                    # f994
        LW("a0", 12, "s0"),                   # f998
        LW("v1", 4, "s0"),                    # f99c  vtable
        SW("v0", 0x10c, "s0"),                # f9a0
        SW("a0", 0x110, "s0"),                # f9a4
        LW("v0", 0x8c, "v1"),                 # f9a8  metodo (riordinata prima della lh)
        LH("a0", 0x88, "v1"),                 # f9ac
        JALR("ra", "v0"),                     # f9b0
        ADDU("a0", "s0", "a0"),               # f9b4  (delay)
        JAL(0x8005b490),                      # f9b8
        ADDU("a0", "s0", "zero"),             # f9bc  (delay)
        LHU("v0", 0, "s1"),                   # f9c0  tipo
        ADDIU("a0", "s0", 0x120),             # f9c4
        SLL("at", "v0", 2),                   # f9c8
        ADDU("at", "at", "s5"),               # f9cc
        LW("v1", 0, "at"),                    # f9d0
        SH("v0", 0x106, "a0"),                # f9d4  (riempie il gap)
        SW("v1", 0x108, "a0"),                # f9d8
        # --- store spawn-point con cap 8 (ex patch F) ---
        LHU("v0", 0x62, "s2"),                # f9e0  n
        LW("a0", 8, "s0"),                    # f9e4  x|alt
        SLTIU("at", "v0", 8),                 # f9e8
        BEQ("at", "zero", 0x8006f9ec, 0x8006fa20),  # f9ec  pieno -> niente store
        SLL("v1", "v0", 3),                   # f9f0  (delay)
        ADDU("v1", "v1", "s2"),               # f9f4
        SW("a0", 0x64, "v1"),                 # f9f8
        LW("a0", 12, "s0"),                   # f9fc  z|rot
        ADDIU("v0", "v0", 1),                 # fa00
        SW("a0", 0x68, "v1"),                 # fa04
        SH("v0", 0x62, "s2"),                 # fa08
        NOP, NOP, NOP, NOP, NOP,              # fa0c..fa1c
    ]
    assert len(wF) == 76, len(wF)
    out = [(A, wA), (B, wB), (C, wC), (F, wF)]

    # --- finestra H: FUN_800749c4, l'allocatore free-list GENERICO di tutte
    # le liste a capienza fissa (pool unita', roster squadra, ...). Vanilla
    # NON controlla l'esaurimento: a lista piena legge free[count] OLTRE il
    # proprio array (l'arena e' impacchettata: e' l'array della lista vicina)
    # e incatena indici spazzatura -> liste circolari/scritture selvagge.
    # Riscrittura compatta (28 word, si riciclano i reload ridondanti di cur
    # e arr_next): se count >= cap ritorna 0xffff pulito (i chiamanti che
    # controllano -1, tipo l'attach roster FUN_80078d34, falliscono con
    # grazia). Il return -1 salta a un thunk jr ra;nop esistente.
    H = 0x800749c4
    THUNK = 0x800747fc
    assert o(H) == ADDU("a2", "a0", "zero"), f"allocatore inatteso: {o(H):#x}"
    assert o(0x80074a30) == ADDU("v0", "a3", "zero")
    assert o(THUNK) == 0x03E00008 and o(THUNK + 4) == 0
    wH = [
        LW("v1", 4, "a0"),                    # count
        LW("v0", 0, "a0"),                    # capienza
        ADDU("a2", "a0", "zero"),             # a2 = lista (colma i delay)
        RT("v1", "v0", "v0", 0x2b),           # sltu v0, count, cap
        BEQ("v0", "zero", H + 0x10, THUNK),   # pieno -> jr ra (v0 = -1)
        I(0x0d, "zero", "v0", 0xffff),        # (delay) ori v0 = -1
        LW("a0", 20, "a2"),                   # arr_free
        SLL("v0", "v1", 1),
        ADDU("v0", "v0", "a0"),
        LHU("a3", 0, "v0"),                   # idx = free[count]
        LW("v0", 12, "a2"),                   # arr_prev
        ADDIU("v1", "v1", 1),
        SW("v1", 4, "a2"),                    # count++
        LHU("a1", 8, "a2"),                   # cur
        SLL("a0", "a3", 1),
        ADDU("v0", "a0", "v0"),
        SH("a1", 0, "v0"),                    # prev[idx] = cur
        LW("v1", 16, "a2"),                   # arr_next
        I(0x0d, "zero", "v0", 0xffff),
        ADDU("a0", "a0", "v1"),
        SH("v0", 0, "a0"),                    # next[idx] = -1
        BEQ("a1", "v0", H + 0x54, H + 0x64),  # cur == -1 -> skip link
        SLL("v0", "a1", 1),                   # (delay)
        ADDU("v0", "v0", "v1"),
        SH("a3", 0, "v0"),                    # next[cur] = idx
        SW("a3", 8, "a2"),                    # cur = idx
        o(0x80074a2c),                        # jr ra
        ADDU("v0", "a3", "zero"),             # (delay) return idx
    ]
    assert len(wH) == 28, len(wH)
    out.append((H, wH))

    # --- G (parte ENG): rebase dei 3 riferimenti alla base del pool unita'
    # (tutti calcolano entry = base + i*0x388: coppie lui/addiu adiacenti)
    hi, lo = P2_NEWBASE >> 16, P2_NEWBASE & 0xffff
    assert lo < 0x8000, "base con lo>=0x8000: servirebbe hi+1"
    for lui_a, add_a, rt_lui, rt_add, rs_add in (
            (0x8008bc84, 0x8008bc88, "v0", "s6", "v0"),
            (0x8008c3f0, 0x8008c3f4, "v0", "s4", "v0"),
            (0x80095680, 0x80095684, "v0", "s2", "v0")):
        assert o(lui_a) == LUI(rt_lui, 0x8011), f"lui inattesa a {lui_a:#x}"
        assert o(add_a) == ADDIU(rt_add, rs_add, 0x0524), f"addiu inattesa a {add_a:#x}"
        out.append((lui_a, [LUI(rt_lui, hi), ADDIU(rt_add, rs_add, lo)]))
    # --- D: limite buddies (slti r,count,4 -> MAX_BUDDIES) ---
    for a in BUDDY_CAP_ENG:
        w = o(a)
        assert (w >> 26) in (0x0a, 0x0b) and (w & 0xffff) == 4, f"guardia buddies inattesa a {a:#x}: {w:#x}"
        out.append((a, [(w & 0xffff0000) | MAX_BUDDIES]))
    return out


# sentinelle dei byte vanilla per riconoscere lo stato del file
VANILLA_CHECK = [
    (0x800a8360, 0x00000000),  # nop nel parser
    (0x800a8838, 0x38420800),  # xori v0,v0,0x800 in FUN_800a8780
]
PATCH_CHECK = [(0x800a8360, LHU("at", 0x10, "s2")), (0x8007082c, NOP),
               (0x8006f8f0, LUI("at", 0x8011)),      # F: guardie pool spawner
               (0x8008bc84, LUI("v0", P2_NEWBASE >> 16))]  # G: pool rilocato
def _buddies_patched(d):
    return (struct.unpack_from("<I", d, 0x800738f0 - BASE)[0] & 0xffff) == MAX_BUDDIES


def _gw(buf, ram):
    return struct.unpack_from("<I", buf, ram - GAME_BASE)[0]


def _game_vanilla(d):
    """riconosce un GAME.BIN non patchato dai valori nativi delle due patch"""
    return ((_gw(d, BUDDY_CAP_GAME[0]) & 0xffff) == 4 and
            (_gw(d, PRELOAD_FN) & 0xffff) == ((-PRELOAD_FRAME) & 0xffff))


def patch_game():
    """GAME.BIN: guardie buddies (D) + buffer di preload unita' (E), da .orig."""
    d = bytearray(open(GAME, "rb").read())
    if os.path.exists(GAME + ".orig"):
        d = bytearray(open(GAME + ".orig", "rb").read())
        if not _game_vanilla(d):
            print("ERRORE: GAME.BIN.orig non vanilla?!")
            sys.exit(1)
    elif _game_vanilla(d):
        shutil.copy2(GAME, GAME + ".orig")
    else:
        print("ERRORE: GAME.BIN in stato sconosciuto e manca .orig")
        sys.exit(1)

    # D) slti/sltiu r,count,4 -> MAX_BUDDIES
    for a in BUDDY_CAP_GAME:
        w = _gw(d, a)
        assert (w >> 26) in (0x0a, 0x0b) and (w & 0xffff) == 4, f"guardia GAME inattesa a {a:#x}: {w:#x}"
        struct.pack_into("<I", d, a - GAME_BASE, (w & 0xffff0000) | MAX_BUDDIES)

    # E) frame di FUN_800e2bb8 piu' grande: il buffer a sp+16 arriva a
    #    PRELOAD_SLOTS voci perche' i registri salvati salgono di DELTA
    if PRELOAD_DELTA:
        for a, sign in ((PRELOAD_FN, -1), (PRELOAD_EPI, +1)):
            w = _gw(d, a)
            assert w == ADDIU("sp", "sp", sign * PRELOAD_FRAME), \
                f"frame inatteso a {a:#x}: {w:#x}"
            struct.pack_into("<I", d, a - GAME_BASE,
                             ADDIU("sp", "sp", sign * (PRELOAD_FRAME + PRELOAD_DELTA)))
        for a, off in PRELOAD_SAVES.items():
            w = _gw(d, a)
            assert (w >> 26) in (0x2b, 0x23) and (w >> 21) & 31 == R["sp"] and (w & 0xffff) == off, \
                f"salvataggio inatteso a {a:#x}: {w:#x}"
            struct.pack_into("<I", d, a - GAME_BASE,
                             (w & 0xffff0000) | ((off + PRELOAD_DELTA) & 0xffff))

    # G) pool unita' classe-buddy: 9 -> POOL2_CAP, array rilocato a P2_NEWBASE
    hi, lo = P2_NEWBASE >> 16, P2_NEWBASE & 0xffff
    # G-cap: FUN_8007490c(0x8010e6dc, 9) -> POOL2_CAP
    w = _gw(d, 0x800e3424)
    assert w == ADDIU("a1", "zero", 9), f"init cap inattesa: {w:#x}"
    struct.pack_into("<I", d, 0x800e3424 - GAME_BASE, ADDIU("a1", "zero", POOL2_CAP))
    # G-id: FUN_800e3458 riserva un blocco di ID GLOBALI per le entry di
    # pool1+pool3+pool2 (FUN_80040a98(16+8+9=33)): senza questo le entry oltre
    # la 9a di pool2 ricevono id fuori blocco che l'allocatore riassegna ad
    # altri oggetti -> handle table aliasata -> liste circolari (hang).
    w = _gw(d, 0x800e3464)
    assert w == ADDIU("a0", "zero", 33), f"blocco id inatteso: {w:#x}"
    struct.pack_into("<I", d, 0x800e3464 - GAME_BASE,
                     ADDIU("a0", "zero", 16 + 8 + POOL2_CAP))
    # G-rebase: coppie lui/addiu che costruiscono la base (lui puo' stare
    # lontana dall'addiu: indirizzi verificati a mano, consumatori esclusivi)
    for lui_a, add_a, rt_lui, rt_add, rs_add in (
            (0x800e35a8, 0x800e35ac, "v0", "t5", "v0"),
            (0x800e3704, 0x800e3708, "a0", "a0", "a0"),
            (0x800e398c, 0x800e3990, "v1", "v1", "v1"),
            (0x800e3afc, 0x800e3b00, "v0", "s3", "v0"),
            (0x800e3ea4, 0x800e3ea8, "v1", "v1", "v1"),
            (0x800e42a0, 0x800e42bc, "s3", "s1", "s3"),
            (0x800e433c, 0x800e437c, "s3", "a0", "s3")):
        wl, wa = _gw(d, lui_a), _gw(d, add_a)
        assert wl == LUI(rt_lui, 0x8011), f"lui inattesa a {lui_a:#x}: {wl:#x}"
        assert wa == ADDIU(rt_add, rs_add, 0x0524), f"addiu inattesa a {add_a:#x}: {wa:#x}"
        struct.pack_into("<I", d, lui_a - GAME_BASE, LUI(rt_lui, hi))
        struct.pack_into("<I", d, add_a - GAME_BASE, ADDIU(rt_add, rs_add, lo))
    # G-count: i due loop "tutte le entry" contano cap-1 -> POOL2_CAP-1
    for a, rt in ((0x800e35a4, "t0"), (0x800e42c0, "s0")):
        w = _gw(d, a)
        assert w == ADDIU(rt, "zero", 8), f"contatore inatteso a {a:#x}: {w:#x}"
        struct.pack_into("<I", d, a - GAME_BASE, ADDIU(rt, "zero", POOL2_CAP - 1))
    # G-bound: fine-array del loop di walk = base + cap*stride
    w = _gw(d, 0x800e4384)
    assert w == ADDIU("s0", "a0", 9 * POOL2_STRIDE), f"bound inatteso: {w:#x}"
    struct.pack_into("<I", d, 0x800e4384 - GAME_BASE,
                     ADDIU("s0", "a0", POOL2_CAP * POOL2_STRIDE))

    open(GAME, "wb").write(d)
    print(f"GAME.BIN patchato (buddies per team: {MAX_BUDDIES}; "
          f"preload unità: {PRELOAD_SLOTS} voci; pool unità: {POOL2_CAP} slot "
          f"@{P2_NEWBASE:#x})")


def patch_sys():
    """SYS.BIN: riduce la size dell'arena heap di ARENA_STEAL nell'init
    (FUN_8003d3f0): l'and di allineamento (size &= ~3) diventa
    addiu size, size, -ARENA_STEAL. Le size passate sono gia' allineate.
    In-place e idempotente (SYS.BIN e' anche toccato da tb_mission)."""
    SYS = os.path.join(ROOT, "teambudd/estratto/SYS.BIN")
    SYS_BASE = 0x80038f80
    d = bytearray(open(SYS, "rb").read())
    off = 0x8003d41c - SYS_BASE
    w = struct.unpack_from("<I", d, off)[0]
    new = ADDIU("a0", "a0", -ARENA_STEAL)
    if w == new:
        print("SYS.BIN già patchato (arena) : ok")
        return
    AND_A0_A0_A1 = (R["a0"] << 21) | (R["a1"] << 16) | (R["a0"] << 11) | 0x24
    assert w == AND_A0_A0_A1, f"istruzione arena inattesa: {w:#x}"
    struct.pack_into("<I", d, off, new)
    open(SYS, "wb").write(d)
    print(f"SYS.BIN patchato (arena -{ARENA_STEAL:#x}: fine <= {P2_NEWBASE:#x})")


def state(d):
    ok_v = all(struct.unpack_from("<I", d, a - BASE)[0] == w for a, w in VANILLA_CHECK)
    ok_p = all(struct.unpack_from("<I", d, a - BASE)[0] == w for a, w in PATCH_CHECK) and _buddies_patched(d)
    return "vanilla" if ok_v else ("patched" if ok_p else "sconosciuto")


def main():
    revert = "--revert" in sys.argv
    d = bytearray(open(ENG, "rb").read())
    st = state(d)
    if revert:
        if os.path.exists(ENG + ".orig"):
            shutil.copy2(ENG + ".orig", ENG)
            print("ENG.BIN ripristinato da .orig")
        else:
            print("nessun backup .orig: niente da fare" if st == "vanilla" else "ERRORE: manca .orig!")
        if os.path.exists(GAME + ".orig"):
            shutil.copy2(GAME + ".orig", GAME)
            print("GAME.BIN ripristinato da .orig")
        return
    if st == "patched":
        print("ENG.BIN già patchato: ok")
        patch_game()
        patch_sys()
        return
    # riparte sempre dal vanilla: da .orig se esiste (anche se lo stato attuale
    # e' una versione patch precedente), altrimenti dal file corrente
    if os.path.exists(ENG + ".orig"):
        d_orig = open(ENG + ".orig", "rb").read()
        if state(bytearray(d_orig)) != "vanilla":
            print("ERRORE: .orig non vanilla?!")
            sys.exit(1)
    elif st == "vanilla":
        shutil.copy2(ENG, ENG + ".orig")
        d_orig = bytes(d)
    else:
        print("ERRORE: ENG.BIN in stato sconosciuto e manca .orig")
        sys.exit(1)
    d = bytearray(d_orig)
    # verifica di sanità: le word 'originali' riusate devono esistere dove previsto
    assert orig(d_orig, 0x800a835c) == 0x86420008, "layout inatteso (lh v0,0x8(s2))"
    assert orig(d_orig, 0x800a88d8) == 0x254a0001, "layout inatteso (addiu t2,t2,1)"
    for start, ws in build_patches(d_orig):
        struct.pack_into(f"<{len(ws)}I", d, start - BASE, *ws)
    open(ENG, "wb").write(d)
    print(f"ENG.BIN patchato (team f8 lista extra + no-tetto team + buddies {MAX_BUDDIES})")
    patch_game()
    patch_sys()


if __name__ == "__main__":
    main()
