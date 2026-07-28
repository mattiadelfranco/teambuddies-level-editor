#!/usr/bin/env python3
"""
Team Buddies (PSX) - Parser dei modelli .LOD (MDL.BND) e delle texture TIM.BND.

Formato .LOD (reversato 28 lug 2026, validato su tutti i 121 modelli dei livelli):

  file:   name[32]  u32 (0x80000000 | n_lod)  lod_block x n_lod
  lod:    u32 0x28  u16 959(ver)  u16 n_parts  name[32]  part x n_parts
  part:   u32 0x48  header[72]  geometria[gsz]
  header: u32 0x7fc0(scala?) u32 ? u32 colore RGB (0x7f=neutro)
          bbox min/max 2x(3h+pad)  char[8] nome texture ("no_tex!"=nessuna)
          char[28] nome bound  u32 0  u32 gsz
  I byte dopo il primo NUL dei campi nome sono spazzatura dell'exporter.

  geometria = stream di tag u32 [u16 code][u16 aux], terminato da 0x00000000.
  code: campi [6][5][5]: f0=(code>>10)/4-1, f1=((code>>5)&31)/2-1, f2=(code&31)-1
  - aux bit15=0: seguono 36B = 3 vertici+normali caricati in un BUFFER A 15 SLOT:
      payload s16[18] = [a0 b0 a1 b1 a2 b2 c1 c2] [n1c n2c]
                        [n0a n0b n1a n1b n2a n2b] [c0 n0c]
      V1=(a0,b0,c0)->slot f2, V2=(a1,b1,c1)->slot f1, V3=(a2,b2,c2)->slot f0
      (il tag di caricamento NON e' una faccia)
  - aux bit15=1: primitiva: v0=f0, v2=f1, v3=f2 (slot); v1=((aux&0xff)>>2)-1,
      v1<0 -> triangolo (v0,v2,v3), altrimenti quad strip (v0,v1,v2,v3).
      aux bit14=1: seguono 8B = 4 coppie UV u8 (ordine v0,v1,v2,v3; tri: 3+pad).
  Assi modello: a=verticale (positivo=su), b/c orizzontali; unita' = 1/64 di
  unita' dato mondo (1 tile = 512 unita' modello).
"""
import struct, os, io


def _cstr(b):
    return b.split(b"\0")[0].decode("latin-1", "replace")


def parse_lod(d):
    """-> {name, lods: [ {parts: [ {tex, color, bbox, verts, norms, prims} ]} ]}
    verts/norms: liste di triple (a,b,c); prims: {idx:[3-4 indici], uv:[coppie]|None}
    """
    name = _cstr(d[:32])
    n_lod = struct.unpack_from("<I", d, 0x20)[0] & 0xffff
    out = {"name": name, "lods": []}
    o = 0x24
    for _ in range(n_lod):
        while o + 4 <= len(d) and struct.unpack_from("<I", d, o)[0] == 0:
            o += 4                      # pad tra i livelli di dettaglio
        if o + 8 > len(d):
            break
        marker, = struct.unpack_from("<I", d, o)
        if marker != 0x28:
            raise ValueError(f"atteso blocco LOD (0x28) a 0x{o:x}, trovato 0x{marker:x}")
        ver, n_parts = struct.unpack_from("<HH", d, o + 4)
        o += 8 + 32                     # ver/count + nome LOD
        lod = {"parts": []}
        for _p in range(n_parts):
            m, = struct.unpack_from("<I", d, o)
            if m != 0x48:
                raise ValueError(f"atteso part (0x48) a 0x{o:x}, trovato 0x{m:x}")
            h = o + 4
            color, = struct.unpack_from("<I", d, h + 8)
            bbox = struct.unpack_from("<3h2x3h2x", d, h + 12)
            tex = _cstr(d[h + 28:h + 36])
            gsz, = struct.unpack_from("<I", d, h + 68)
            part = _parse_geo(d, h + 72, gsz)
            part["tex"] = None if tex in ("no_tex!", "") else tex
            part["color"] = ((color >> 0) & 255, (color >> 8) & 255, (color >> 16) & 255)
            part["bbox"] = bbox
            lod["parts"].append(part)
            o = h + 72 + gsz
        out["lods"].append(lod)
    return out


def _parse_geo(d, geo, gsz):
    o, end = geo, geo + gsz
    slots = [0] * 15                    # indice nel vertex array per slot
    verts, norms, prims = [], [], []
    while o + 4 <= end:
        code, aux = struct.unpack_from("<HH", d, o)
        o += 4
        if code == 0 and aux == 0:
            break
        f0 = (code >> 10) // 4 - 1
        f1 = ((code >> 5) & 31) // 2 - 1
        f2 = (code & 31) - 1
        if not (aux & 0x8000):
            p = struct.unpack_from("<18h", d, o)
            o += 36
            a0, b0, a1, b1, a2, b2, c1, c2, n1c, n2c, \
                n0a, n0b, n1a, n1b, n2a, n2b, c0, n0c = p
            for slot, v, n in ((f2, (a0, b0, c0), (n0a, n0b, n0c)),
                               (f1, (a1, b1, c1), (n1a, n1b, n1c)),
                               (f0, (a2, b2, c2), (n2a, n2b, n2c))):
                if 0 <= slot < 15:
                    slots[slot] = len(verts)
                    verts.append(v)
                    norms.append(n)
        else:
            uv = None
            if aux & 0x4000:
                uv = struct.unpack_from("<8B", d, o)
                o += 8
            v1 = ((aux & 0xff) >> 2) - 1
            f = [f0, v1, f1, f2] if v1 >= 0 else [f0, f1, f2]
            if any(i < 0 or i > 14 for i in f):
                continue                # tag anomalo: salta
            idx = [slots[i] for i in f]
            uvp = None
            if uv is not None:
                uvp = [(uv[2 * k], uv[2 * k + 1]) for k in range(len(f))]
            prims.append({"idx": idx, "uv": uvp})
    return {"verts": verts, "norms": norms, "prims": prims}


def best_lod(model):
    """il livello di dettaglio piu' ricco (di solito il primo)"""
    return max(model["lods"],
               key=lambda l: sum(len(p["verts"]) for p in l["parts"]))


def parse_bind(d):
    """BIND generico -> lista (nome, bytes)"""
    if d[:4] != b"BIND":
        raise ValueError("non e' un BIND")
    cnt, = struct.unpack_from("<I", d, 4)
    out = []
    off = 8
    for _ in range(cnt):
        name = _cstr(d[off:off + 32])
        o, s = struct.unpack_from("<II", d, off + 32)
        out.append((name, d[o:o + s]))
        off += 40
    return out


def tim_to_rgba(d, clut_row=0):
    """TIM 4/8bpp -> (w, h, bytes RGBA). Colore 0 (nero pieno) = trasparente."""
    magic, typ = struct.unpack_from("<II", d, 0)
    assert magic == 0x10, "non e' una TIM"
    bpp = typ & 7
    o = 8
    cluts = None
    if typ & 8:
        clen, _, _, cw, ch = struct.unpack_from("<IHHHH", d, o)
        row = min(clut_row, ch - 1)
        cluts = []
        for c in range(cw):
            v, = struct.unpack_from("<H", d, o + 12 + (row * cw + c) * 2)
            r = (v & 31) * 8
            g = ((v >> 5) & 31) * 8
            b = ((v >> 10) & 31) * 8
            cluts.append((r, g, b, 0 if v == 0 else 255))
        o += clen
    ilen, _, _, iw, ih = struct.unpack_from("<IHHHH", d, o)
    px = d[o + 12: o + 12 + iw * 2 * ih]
    out = bytearray()
    if bpp == 0:      # 4bpp
        w = iw * 4
        for b in px:
            out += bytes(cluts[b & 15]) + bytes(cluts[b >> 4])
    elif bpp == 1:    # 8bpp
        w = iw * 2
        for b in px:
            out += bytes(cluts[b])
    else:
        raise ValueError(f"TIM bpp {bpp} non gestita")
    return w, ih, bytes(out)


def tim_to_png(d, clut_row=0):
    from PIL import Image
    w, h, rgba = tim_to_rgba(d, clut_row)
    img = Image.frombytes("RGBA", (w, h), rgba)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def export_obj(model, path):
    """dump di controllo in Wavefront OBJ (solo geometria, LOD migliore)"""
    lod = best_lod(model)
    with open(path, "w") as f:
        f.write(f"# {model['name']}\n")
        base = 1
        for part in lod["parts"]:
            f.write(f"o {model['name']}_{base}\n")
            for a, b, c in part["verts"]:
                f.write(f"v {b} {a} {c}\n")           # a=verticale -> y
            for p in part["prims"]:
                i = [k + base for k in p["idx"]]
                if len(i) == 3:
                    f.write(f"f {i[0]} {i[1]} {i[2]}\n")
                else:                                  # quad PERIMETRALE 0,1,2,3
                    f.write(f"f {i[0]} {i[1]} {i[2]} {i[3]}\n")
            base += len(part["verts"])
    print(f"scritto {path}")


if __name__ == "__main__":
    import sys, glob
    if len(sys.argv) < 2:
        print("uso: tb_lod.py <MDL.BND|file.LOD> [nome_modello] [out.obj]")
        sys.exit(1)
    d = open(sys.argv[1], "rb").read()
    if d[:4] == b"BIND":
        entries = parse_bind(d)
        if len(sys.argv) < 3:
            for n, b in entries:
                m = parse_lod(b)
                lod = best_lod(m)
                nv = sum(len(p["verts"]) for p in lod["parts"])
                np_ = sum(len(p["prims"]) for p in lod["parts"])
                texs = {p["tex"] for p in lod["parts"] if p["tex"]}
                print(f"{n:28s} lod={len(m['lods'])} verts={nv:4d} prims={np_:4d} tex={sorted(texs)}")
            sys.exit(0)
        b = dict(entries)[sys.argv[2]]
        m = parse_lod(b)
    else:
        m = parse_lod(d)
    out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/model.obj"
    export_obj(m, out)
