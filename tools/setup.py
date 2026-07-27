#!/usr/bin/env python3
"""
Team Buddies Level Editor - one-shot setup.

Bootstraps a working editor installation from YOUR OWN dump of
Team Buddies (Europe) (SCES-02986). No game data is included in this
repository; you must provide a .bin disc image you legally own.

  python3 tools/setup.py /path/to/TeamBuddies.bin

Steps (each one is skipped if its output already exists, so the script is
safe to re-run and safe on an already-working installation):
  1. check prerequisites (git, cmake, a C++ compiler)
  2. clone + build mkpsxiso (provides mkpsxiso and dumpsxiso)
  3. extract the disc image into teambudd/estratto/ + generate the
     rebuild project file teambudd/teambuddies.xml
  4. back up BUDDIES.DAT as BUDDIES.DAT.orig (the rebuild source of truth)
  5. unpack BUDDIES.DAT into teambudd/dat_estratto/ (tb_extract.py)
  6. render the terrain of all levels into teambudd/grounds/ (render_ground.py)

Then run:  python3 tools/editor_server.py  ->  http://localhost:8787
"""
import argparse, glob, os, shutil, struct, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MKPSXISO_DIR = os.path.join(ROOT, "mkpsxiso")
MKPSXISO = os.path.join(MKPSXISO_DIR, "build/mkpsxiso")
DUMPSXISO = os.path.join(MKPSXISO_DIR, "build/dumpsxiso")
TB = os.path.join(ROOT, "teambudd")
ESTRATTO = os.path.join(TB, "estratto")
DAT = os.path.join(ESTRATTO, "BUDDIES.DAT")
DAT_ESTRATTO = os.path.join(TB, "dat_estratto")
GROUNDS = os.path.join(TB, "grounds")
MKPSXISO_GIT = "https://github.com/Lameguy64/mkpsxiso.git"


def step(msg):
    print(f"\n=== {msg}")


def run(cmd, **kw):
    print("  $ " + " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def check_prereqs():
    step("checking prerequisites")
    missing = [t for t in ("git", "cmake") if shutil.which(t) is None]
    if missing:
        sys.exit(f"missing tools: {', '.join(missing)} - install them and retry")
    print("  ok")


def build_mkpsxiso():
    step("mkpsxiso / dumpsxiso")
    if os.path.exists(MKPSXISO) and os.path.exists(DUMPSXISO):
        print("  already built, skipping")
        return
    if not os.path.isdir(MKPSXISO_DIR):
        run(["git", "clone", "--recursive", MKPSXISO_GIT, MKPSXISO_DIR])
    run(["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release"], cwd=MKPSXISO_DIR)
    run(["cmake", "--build", "build", "-j"], cwd=MKPSXISO_DIR)
    if not (os.path.exists(MKPSXISO) and os.path.exists(DUMPSXISO)):
        sys.exit("mkpsxiso build did not produce the expected binaries")


def extract_iso(bin_path):
    step("extracting the disc image")
    if os.path.exists(DAT):
        print("  teambudd/estratto/ already populated, skipping")
        return
    if not os.path.exists(bin_path):
        sys.exit(f"disc image not found: {bin_path}")
    os.makedirs(ESTRATTO, exist_ok=True)
    run([DUMPSXISO, bin_path, "-x", ESTRATTO, "-s", os.path.join(TB, "teambuddies.xml")])
    if not os.path.exists(DAT):
        sys.exit("BUDDIES.DAT not found after extraction - is this a Team Buddies disc image?")
    cnf = os.path.join(ESTRATTO, "SYSTEM.CNF")
    if os.path.exists(cnf) and b"SCES_029.86" not in open(cnf, "rb").read():
        print("  WARNING: this does not look like SCES-02986 (PAL). The tools were")
        print("  reverse-engineered against that version; other versions are untested.")


def backup_dat():
    step("backing up BUDDIES.DAT")
    if os.path.exists(DAT + ".orig"):
        print("  BUDDIES.DAT.orig already present, skipping")
        return
    shutil.copy2(DAT, DAT + ".orig")
    print("  created teambudd/estratto/BUDDIES.DAT.orig")


def extract_dat():
    step("unpacking BUDDIES.DAT")
    if os.path.exists(os.path.join(DAT_ESTRATTO, "manifest.tsv")):
        print("  teambudd/dat_estratto/ already populated, skipping")
        return
    run([sys.executable, os.path.join(ROOT, "tools/tb_extract.py"), DAT, DAT_ESTRATTO])


def render_grounds():
    step("rendering level terrain (this takes a couple of minutes)")
    os.makedirs(GROUNDS, exist_ok=True)
    todo = []
    for folder in sorted(glob.glob(os.path.join(DAT_ESTRATTO, "bind/*"))):
        if not glob.glob(os.path.join(folder, "*.PND")):
            continue
        out = os.path.join(GROUNDS, os.path.basename(folder) + ".png")
        if not os.path.exists(out):
            todo.append((folder, out))
    if not todo:
        print("  all terrains already rendered, skipping")
        return
    for i, (folder, out) in enumerate(todo, 1):
        print(f"  [{i}/{len(todo)}] {os.path.basename(folder)}")
        subprocess.run([sys.executable, os.path.join(ROOT, "tools/render_ground.py"),
                        folder, out, "8"], check=True, capture_output=True)


def main():
    ap = argparse.ArgumentParser(description="Bootstrap the Team Buddies level editor "
                                             "from your own disc image.")
    ap.add_argument("bin", nargs="?", help="path to your Team Buddies .bin disc image "
                                           "(SCES-02986; not needed on re-runs once extracted)")
    args = ap.parse_args()
    check_prereqs()
    build_mkpsxiso()
    if not os.path.exists(DAT):
        if not args.bin:
            ap.error("first run needs the path to your .bin disc image")
        extract_iso(args.bin)
    else:
        print("\n=== disc already extracted, skipping")
    backup_dat()
    extract_dat()
    render_grounds()
    step("done!")
    print("  start the editor with:  python3 tools/editor_server.py")
    print("  then open:              http://localhost:8787")


if __name__ == "__main__":
    main()
