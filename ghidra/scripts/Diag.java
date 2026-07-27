// @category TeamBuddies
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.mem.*;

public class Diag extends GhidraScript {
    @Override
    public void run() throws Exception {
        println("lang=" + currentProgram.getLanguage().getLanguageID());
        for (MemoryBlock b : currentProgram.getMemory().getBlocks())
            println("block " + b.getName() + " " + b.getStart() + "-" + b.getEnd() + " x=" + b.isExecute() + " init=" + b.isInitialized());
        Address a = toAddr(0x80083338L);
        byte[] bs = getBytes(a, 16);
        StringBuilder sb = new StringBuilder();
        for (byte x : bs) sb.append(String.format("%02x ", x));
        println("bytes @0x80083338: " + sb);
        boolean ok = disassemble(a);
        println("disassemble -> " + ok + " ins=" + currentProgram.getListing().getInstructionAt(a));
    }
}
