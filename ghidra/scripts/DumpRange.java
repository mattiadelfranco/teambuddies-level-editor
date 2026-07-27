// Disassembla un intervallo dato: args = start end
// @category TeamBuddies
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class DumpRange extends GhidraScript {
    @Override
    public void run() throws Exception {
        long a = Long.parseLong(getScriptArgs()[0].replace("0x",""), 16);
        long b = Long.parseLong(getScriptArgs()[1].replace("0x",""), 16);
        Address lo = toAddr(a), hi = toAddr(b);
        clearListing(lo, hi);
        disassemble(lo);
        Listing listing = currentProgram.getListing();
        for (Address p = lo; p.compareTo(hi) < 0; ) {
            Instruction ins = listing.getInstructionAt(p);
            if (ins == null) { disassemble(p); ins = listing.getInstructionAt(p); }
            if (ins == null) { p = p.add(4); continue; }
            println(String.format("  %s: %s", p, ins));
            p = p.add(ins.getLength());
        }
    }
}
