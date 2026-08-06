// Cerca i byte little-endian dei valori dati come argomenti in tutta la
// memoria inizializzata (per trovare tabelle di function pointer)
// @category TeamBuddies
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.MemoryBlock;

public class FindPtr extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String s : getScriptArgs()) {
            long v = Long.parseLong(s.replace("0x", ""), 16);
            byte[] pat = new byte[] {(byte) v, (byte) (v >> 8), (byte) (v >> 16), (byte) (v >> 24)};
            println("=== ptr 0x" + Long.toHexString(v) + " ===");
            for (MemoryBlock b : currentProgram.getMemory().getBlocks()) {
                if (!b.isInitialized()) continue;
                Address a = b.getStart();
                while (a != null && a.compareTo(b.getEnd()) < 0) {
                    a = currentProgram.getMemory().findBytes(a, b.getEnd(), pat, null, true, monitor);
                    if (a == null) break;
                    println("  trovato a " + a);
                    a = a.add(4);
                }
            }
        }
    }
}
