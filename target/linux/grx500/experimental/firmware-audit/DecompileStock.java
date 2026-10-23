// Direct Ghidra fallback: this output is not REA Evidence.
// Usage: analyzeHeadless PROJECT_DIR NAME -import ELF -processor MIPS:BE:32:default
//   -scriptPath SCRIPT_DIR -postScript DecompileStock.java OUTPUT NAME_REGEX
//   -deleteProject
// No target code is executed; the imported analysis database is disposable.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import java.io.PrintWriter;
import java.util.regex.Pattern;

public class DecompileStock extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length != 2) throw new IllegalArgumentException("OUTPUT NAME_REGEX required");
        Pattern selected = Pattern.compile(args[1]);
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (PrintWriter out = new PrintWriter(args[0], "UTF-8")) {
            out.println("/* Direct Ghidra output, NOT REA Evidence.");
            out.println("Input: " + currentProgram.getExecutablePath());
            out.println("SHA256: " + currentProgram.getExecutableSHA256());
            out.println("Language: " + currentProgram.getLanguageID());
            out.println("Function selection: " + args[1]);
            out.println("Pseudocode is inferred; floating-point ABI and runtime behavior unverified.");
            out.println("For ET_REL, addresses are Ghidra analysis coordinates, not runtime addresses. */");
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext() && !monitor.isCancelled()) {
                Function function = functions.next();
                if (!selected.matcher(function.getName()).find() || function.isExternal()) continue;
                if (currentProgram.getMemory().getBlock(function.getEntryPoint()).getName().equals("EXTERNAL")) continue;
                out.println("\n/* FUNCTION " + function.getName() + " @ " + function.getEntryPoint() + " */");
                DecompileResults result = decompiler.decompileFunction(function, 45, monitor);
                if (result.decompileCompleted()) out.println(result.getDecompiledFunction().getC());
                else out.println("/* FAILED: " + result.getErrorMessage() + " */");
                out.flush();
            }
        } finally { decompiler.dispose(); }
    }
}
