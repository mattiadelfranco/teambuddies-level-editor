// Disassembla e stampa una finestra attorno agli indirizzi dati
// @category TeamBuddies
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;

public class DumpAsm extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Listing listing = currentProgram.getListing();
        for (String s : args) {
            long a = Long.parseLong(s.replace("0x", ""), 16);
            Address lo = toAddr(a - 0x140), hi = toAddr(a + 0x140);
            clearListing(lo, hi);
            disassemble(lo);
            for (Address p = lo; p.compareTo(hi) < 0; ) {
                Instruction ins = listing.getInstructionAt(p);
                if (ins == null) { disassemble(p); ins = listing.getInstructionAt(p); }
                if (ins == null) { p = p.add(4); continue; }
                println(String.format("%s%s: %s", p.equals(toAddr(a)) ? ">>" : "  ", p, ins));
                p = p.add(ins.getLength());
            }
            println("-----");
        }
    }
}
