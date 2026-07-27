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

Uso:  python3 tools/tb_patch_eng.py [--revert]
Backup automatico in ENG.BIN.orig. Idempotente.
"""
import struct, sys, os, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENG = os.path.join(ROOT, "teambudd/estratto/ENG.BIN")
BASE = 0x80051954

# --- mini assembler MIPS (solo il necessario) ---
R = {"zero": 0, "at": 1, "v0": 2, "v1": 3, "a0": 4, "a1": 5, "a2": 6, "a3": 7,
     "t0": 8, "t1": 9, "t2": 10, "t3": 11, "t4": 12, "t5": 13, "t6": 14, "t7": 15,
     "s0": 16, "s1": 17, "s2": 18, "s3": 19, "sp": 29, "ra": 31}

def I(op, rs, rt, imm):  # I-type
    return (op << 26) | (R[rs] << 21) | (R[rt] << 16) | (imm & 0xffff)

def SLL(rd, rt, sa):
    return (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | 0x00

def SRL(rd, rt, sa):
    return (R[rt] << 16) | (R[rd] << 11) | (sa << 6) | 0x02

def RT(rs, rt, rd, funct):  # R-type aritmetica
    return (R[rs] << 21) | (R[rt] << 16) | (R[rd] << 11) | funct

def LHU(rt, off, base): return I(0x25, base, rt, off)
def SH(rt, off, base):  return I(0x29, base, rt, off)
def ANDI(rt, rs, imm):  return I(0x0c, rs, rt, imm)
def ADDIU(rt, rs, imm): return I(0x09, rs, rt, imm)
def OR(rd, rs, rt):     return RT(rs, rt, rd, 0x25)
def SUBU(rd, rs, rt):   return RT(rs, rt, rd, 0x23)
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
    return [(A, wA), (B, wB)]


# sentinelle dei byte vanilla per riconoscere lo stato del file
VANILLA_CHECK = [
    (0x800a8360, 0x00000000),  # nop nel parser
    (0x800a8838, 0x38420800),  # xori v0,v0,0x800 in FUN_800a8780
]
PATCH_CHECK = [(0x800a8360, LHU("at", 0x10, "s2"))]


def state(d):
    ok_v = all(struct.unpack_from("<I", d, a - BASE)[0] == w for a, w in VANILLA_CHECK)
    ok_p = all(struct.unpack_from("<I", d, a - BASE)[0] == w for a, w in PATCH_CHECK)
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
        return
    if st == "patched":
        print("ENG.BIN già patchato: ok")
        return
    if st != "vanilla":
        print("ERRORE: ENG.BIN in stato sconosciuto, non tocco nulla")
        sys.exit(1)
    if not os.path.exists(ENG + ".orig"):
        shutil.copy2(ENG, ENG + ".orig")
    d_orig = bytes(d)
    # verifica di sanità: le word 'originali' riusate devono esistere dove previsto
    assert orig(d_orig, 0x800a835c) == 0x86420008, "layout inatteso (lh v0,0x8(s2))"
    assert orig(d_orig, 0x800a88d8) == 0x254a0001, "layout inatteso (addiu t2,t2,1)"
    for start, ws in build_patches(d_orig):
        struct.pack_into(f"<{len(ws)}I", d, start - BASE, *ws)
    open(ENG, "wb").write(d)
    print(f"ENG.BIN patchato (campo team f8 per la lista extra): {len(d)} byte")


if __name__ == "__main__":
    main()
