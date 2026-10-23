#!/usr/bin/env python3
"""Exercise the actual early-boot bank parser with bounded hostile arguments."""
from pathlib import Path
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] /
          'files/arch/mips/intel-mips/prom.c').read_text()
parser = source[source.index('static char __init grx500_parse_bank'):
                source.index('void __init prom_init')]
harness = r'''
#include <assert.h>
#include <string.h>
#define __init
#define COMMAND_LINE_SIZE 2048
PARSER
int main(void) {
 assert(grx500_parse_bank("rootfsname=rootfsA", 0) == 'A');
 assert(grx500_parse_bank("rootfsname=rootfsB", 0) == 'B');
 assert(grx500_parse_bank("mem=480M rootfsname=rootfsB ro", 0) == 'B');
 assert(grx500_parse_bank("", 0) == 0);
 assert(grx500_parse_bank("xrootfsname=rootfsA", 0) == 0);
 const char *bad[] = {"rootfsname=rootfs", "rootfsname=rootfsC",
 "rootfsname=rootfsAB", "rootfsname=rootfsA/",
 "rootfsname=rootfsA\n", "rootfsname=../rootfsA", "rootfsname=rootfsAevil",
 "rootfsname=rootfsA rootfsname=rootfsB", "rootfsname=rootfsA rootfsname=rootfsA",
 "rootfsname=bad rootfsname=rootfsB", "rootfsname=rootfsB rootfsname=bad"};
 for (unsigned i=0; i < sizeof(bad)/sizeof(bad[0]); i++)
  assert(grx500_parse_bank(bad[i], 0) == '?');
 // The same rule applies across separate argv entries, including equal banks.
 for (char bank = 'A'; bank <= 'B'; bank++) {
  assert(grx500_parse_bank("rootfsname=rootfsA", bank) == '?');
  assert(grx500_parse_bank("rootfsname=rootfsB", bank) == '?');
  assert(grx500_parse_bank("rootfsname=bad", bank) == '?');
  assert(grx500_parse_bank("console=ttyLTQ0 ro", bank) == bank);
 }
 assert(grx500_parse_bank("rootfsname=rootfsA", '?') == '?');
 char bounded[COMMAND_LINE_SIZE];
 memset(bounded,'x',sizeof(bounded));
 memcpy(bounded,"rootfsname=rootfsA ",19);
 assert(grx500_parse_bank(bounded, 0) == '?');
 bounded[sizeof(bounded)-1] = 0;
 assert(grx500_parse_bank(bounded, 0) == 'A');
 memset(bounded,' ',sizeof(bounded));
 memcpy(bounded+sizeof(bounded)-18,"rootfsname=rootfsA",18);
 assert(grx500_parse_bank(bounded, 0) == '?');
 // Exactly bounded selectors and every truncated prefix are also checked.
 const char *token = "rootfsname=rootfsA";
 for (size_t length = 0; length <= strlen(token); length++) {
  char short_arg[19];
  memcpy(short_arg, token, length); short_arg[length] = 0;
  char actual = grx500_parse_bank(short_arg, 0);
  assert(actual == (length == 18 ? 'A' : length >= 11 ? '?' : 0));
 }
 return 0;
}
'''.replace('PARSER', parser)
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path/'test.c').write_text(harness)
    subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                    '-o', str(path/'test'), str(path/'test.c')], check=True)
    subprocess.run([str(path/'test')], check=True)
print('Boot-bank parser boundary tests passed (ASan/UBSan).')
