// Elenca le funzioni che referenziano gli indirizzi dati come argomenti
// @category TeamBuddies
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class XRefs extends GhidraScript {
    @Override
    public void run() throws Exception {
        for (String s : getScriptArgs()) {
            long a = Long.parseLong(s.replace("0x", ""), 16);
            Address addr = toAddr(a);
            println("=== XREF a 0x" + Long.toHexString(a) + " ===");
            for (Reference r : getReferencesTo(addr)) {
                Function fn = getFunctionContaining(r.getFromAddress());
                println("  " + r.getFromAddress() + " (" + r.getReferenceType() + ") in "
                        + (fn == null ? "?" : fn.getName()));
            }
        }
    }
}
