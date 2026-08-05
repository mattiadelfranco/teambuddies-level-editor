#!/usr/bin/env python3
"""
Team Buddies (PSX) - .PAD skeletal animation reader.

Format (see docs/FORMATS.md):
    0    "PAD0"
    4    u16 n_frames
    6    u16 n_bones          (== part count of the paired .LOD)
    8    per bone: char name[32] + n_frames * 8-byte frame records

The 8-byte frame record layout was recovered from the running game: the
decoder lives at 0x800B1778 (ENG) and is called by the animation evaluator
FUN_800ADDA0, found with a read watchpoint on a PAD buffer in RAM
(DuckStation MCP). From the disassembly:

    w0, w1 = u32 LE pair
    rot_x = ((w0 >> 16) & 0xff) << 4      PSX angle, 0x1000 = full turn
    rot_y = ((w0 >>  8) & 0xff) << 4
    rot_z = ( w0        & 0xff) << 4
    tx    = s16( (sra(w0 << 1, 19) & 0xffc0) | (w1 >> 26) )   14-bit
    ty    = s16(  sra(w1 << 6, 19) )                          13-bit
    tz    = s16(  sra(w1 << 19, 19) )                         13-bit

The evaluator negates the three angles (`subu v0, zero, v0` + `andi 0xfff`)
before building the matrix, and writes 32-byte PSX MATRIX entries.

Usage:
    python3 tools/tb_pad.py <file.PAD> [frame]
"""
import struct
import sys


def _sra(x, n):
    x &= 0xffffffff
    return ((x ^ 0x80000000) >> n) - (0x80000000 >> n)


def _s16(v):
    v &= 0xffff
    return v - 65536 if v >= 32768 else v


def decode_frame(w0, w1):
    """One 8-byte record -> ((rx, ry, rz) in PSX units, (tx, ty, tz))."""
    rot = (((w0 >> 16) & 0xff) << 4, ((w0 >> 8) & 0xff) << 4, (w0 & 0xff) << 4)
    tr = (_s16((_sra(w0 << 1, 19) & 0xffc0) | ((w1 >> 26) & 0x3f)),
          _s16(_sra(w1 << 6, 19) & 0xffff),
          _s16(_sra(w1 << 19, 19) & 0xffff))
    return rot, tr


def parse(data):
    """-> {n_frames, n_bones, bones: [{name, frames: [(rot, tr), ...]}]}"""
    if data[:4] != b"PAD0":
        raise ValueError("not a PAD0 file")
    nf, nb = struct.unpack_from("<2H", data, 4)
    stride = 32 + nf * 8
    bones = []
    for b in range(nb):
        base = 8 + b * stride
        name = data[base:base + 32].split(b"\0")[0].decode("latin-1")
        frames = [decode_frame(*struct.unpack_from("<2I", data, base + 32 + f * 8))
                  for f in range(nf)]
        bones.append({"name": name, "frames": frames})
    return {"n_frames": nf, "n_bones": nb, "bones": bones}


if __name__ == "__main__":
    d = open(sys.argv[1], "rb").read()
    frame = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    p = parse(d)
    print(f"{p['n_frames']} frames, {p['n_bones']} bones — frame {frame}:")
    for b in p["bones"]:
        rot, tr = b["frames"][frame]
        deg = tuple(round(r / 4096 * 360, 1) for r in rot)
        print(f"  {b['name']:16s} rot={deg}°  trans={tr}")
