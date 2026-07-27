// Decompila le funzioni contenenti gli indirizzi passati come argomenti
// @category TeamBuddies
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.app.cmd.function.CreateFunctionCmd;

public class DumpFuncs extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (String s : args) {
            long a = Long.parseLong(s.replace("0x", ""), 16);
            Address addr = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(a);
            Function fn = getFunctionContaining(addr);
            if (fn == null) {
                new CreateFunctionCmd(addr).applyTo(currentProgram);
                fn = getFunctionContaining(addr);
            }
            if (fn == null) { println("=== 0x" + Long.toHexString(a) + ": nessuna funzione"); continue; }
            println("=== 0x" + Long.toHexString(a) + " in " + fn.getName() + " @ " + fn.getEntryPoint() + " ===");
            DecompileResults res = di.decompileFunction(fn, 120, monitor);
            if (res.decompileCompleted()) println(res.getDecompiledFunction().getC());
            else println("decompilazione fallita");
        }
        di.dispose();
    }
}
