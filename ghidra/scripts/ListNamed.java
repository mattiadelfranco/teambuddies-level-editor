// Elenca le funzioni con nome non-default (firme PSY-Q applicate)
// @category TeamBuddies
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;

public class ListNamed extends GhidraScript {
    @Override
    public void run() throws Exception {
        int tot = 0, named = 0;
        for (Function f : currentProgram.getFunctionManager().getFunctions(true)) {
            tot++;
            String n = f.getName();
            if (!n.startsWith("FUN_") && !n.startsWith("thunk_FUN_")) {
                named++;
                println(f.getEntryPoint() + "  " + n);
            }
        }
        println("TOT funzioni: " + tot + ", con nome: " + named);
    }
}
