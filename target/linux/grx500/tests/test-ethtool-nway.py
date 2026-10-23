#!/usr/bin/env python3
"""Exercise the GRX500 Ethernet autonegotiation restart callback."""
from pathlib import Path
import re
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] /
          'files/drivers/net/ethernet/lantiq/ltq_eth_drv_xrx500.c').read_text()
match = re.search(r'^static int nway_reset\([^;]*?\)\s*\{', source, re.M)
assert match, 'nway_reset'
end, depth = match.end(), 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
function = source[match.start():end]

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>

struct net_device { int marker; };
static struct net_device *expected_dev;
static int helper_result;
static unsigned int helper_calls;

static int phy_ethtool_nway_reset(struct net_device *dev)
{
    assert(dev == expected_dev);
    helper_calls++;
    return helper_result;
}

FUNCTION

int main(void)
{
    static const int results[] = { 0, -ENODEV, -EIO, -EINVAL, -EOPNOTSUPP };
    struct net_device dev = { .marker = 0x5a5a };
    unsigned int i;

    expected_dev = &dev;
    for (i = 0; i < sizeof(results) / sizeof(results[0]); i++) {
        helper_result = results[i];
        helper_calls = 0;
        assert(nway_reset(&dev) == results[i]);
        assert(helper_calls == 1);
        assert(dev.marker == 0x5a5a);
    }

    printf("PASS: %u GRX500 PHY autonegotiation restart cases\n", i);
    return 0;
}
'''.replace('FUNCTION', function)

with tempfile.TemporaryDirectory(prefix='grx500-nway-') as tmp:
    path = Path(tmp)
    (path / 'probe.c').write_text(harness)
    subprocess.run([
        'gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fno-pie', '-no-pie', '-fsanitize=address,undefined',
        '-fno-omit-frame-pointer', str(path / 'probe.c'), '-o',
        str(path / 'probe')
    ], check=True)
    subprocess.run([str(path / 'probe')], cwd=path, check=True)
