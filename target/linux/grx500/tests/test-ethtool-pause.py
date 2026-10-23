#!/usr/bin/env python3
"""Exercise GRX500 ethtool pause get/set logic against exact driver code."""
from pathlib import Path
import re
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] /
          'files/drivers/net/ethernet/lantiq/ltq_eth_drv_xrx500.c').read_text()


def extract(return_type, name):
    match = re.search(r'^static ' + return_type + r' ' + name +
                      r'\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


functions = '\n\n'.join((extract('void', 'get_pauseparam'),
                           extract('int', 'set_pauseparam')))

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define fallthrough __attribute__((__fallthrough__))
#define GSW_statusOk 0
#define GSW_FLOW_AUTO 0
#define GSW_FLOW_RX 1
#define GSW_FLOW_TX 2
#define GSW_FLOW_RXTX 3
#define GSW_FLOW_OFF 4
#define dev_err(...) do { } while (0)

typedef struct {
    unsigned int nPortId;
    unsigned int eFlowCtrl;
    unsigned int marker;
} GSW_portCfg_t;

struct ethtool_pauseparam {
    unsigned int autoneg;
    unsigned int rx_pause;
    unsigned int tx_pause;
};

struct net_device {
    struct { int unused; } dev;
    unsigned int dev_id;
};

struct core_ops;
struct common_ops {
    int (*PortCfgGet)(struct core_ops *ops, GSW_portCfg_t *cfg);
    int (*PortCfgSet)(struct core_ops *ops, GSW_portCfg_t *cfg);
};
struct core_ops {
    struct common_ops gsw_common_ops;
};

static struct core_ops mock_ops;
static int ops_available;
static int get_result;
static int set_result;
static unsigned int returned_mode;
static unsigned int get_calls;
static unsigned int set_calls;
static GSW_portCfg_t written_cfg;

static struct core_ops *get_swcore_ops(struct net_device *dev)
{
    (void)dev;
    return ops_available ? &mock_ops : NULL;
}

static int port_cfg_get(struct core_ops *ops, GSW_portCfg_t *cfg)
{
    assert(ops == &mock_ops);
    get_calls++;
    assert(cfg->nPortId == 7);
    if (get_result != GSW_statusOk)
        return get_result;
    cfg->eFlowCtrl = returned_mode;
    cfg->marker = 0x51a7;
    return GSW_statusOk;
}

static int port_cfg_set(struct core_ops *ops, GSW_portCfg_t *cfg)
{
    assert(ops == &mock_ops);
    set_calls++;
    written_cfg = *cfg;
    return set_result;
}

FUNCTIONS

static void reset_fixture(void)
{
    ops_available = 1;
    get_result = set_result = GSW_statusOk;
    returned_mode = GSW_FLOW_OFF;
    get_calls = set_calls = 0;
    memset(&written_cfg, 0, sizeof(written_cfg));
    mock_ops.gsw_common_ops.PortCfgGet = port_cfg_get;
    mock_ops.gsw_common_ops.PortCfgSet = port_cfg_set;
}

static void check_get(struct net_device *dev, unsigned int mode,
                      unsigned int autoneg, unsigned int rx, unsigned int tx)
{
    struct ethtool_pauseparam pause = { 9, 9, 9 };

    reset_fixture();
    returned_mode = mode;
    get_pauseparam(dev, &pause);
    assert(get_calls == 1);
    assert(pause.autoneg == autoneg);
    assert(pause.rx_pause == rx);
    assert(pause.tx_pause == tx);
}

static void check_set(struct net_device *dev, unsigned int autoneg,
                      unsigned int rx, unsigned int tx, unsigned int mode)
{
    struct ethtool_pauseparam pause = { autoneg, rx, tx };

    reset_fixture();
    assert(set_pauseparam(dev, &pause) == 0);
    assert(get_calls == 1 && set_calls == 1);
    assert(written_cfg.nPortId == dev->dev_id);
    assert(written_cfg.eFlowCtrl == mode);
    assert(written_cfg.marker == 0x51a7);
}

int main(void)
{
    struct net_device dev = { .dev_id = 7 };
    struct ethtool_pauseparam pause = { 9, 9, 9 };
    unsigned int cases = 0;

    reset_fixture();
    ops_available = 0;
    get_pauseparam(&dev, &pause);
    assert(!pause.autoneg && !pause.rx_pause && !pause.tx_pause);
    assert(!get_calls);
    cases++;

    reset_fixture();
    get_result = -3;
    pause = (struct ethtool_pauseparam){ 9, 9, 9 };
    get_pauseparam(&dev, &pause);
    assert(!pause.autoneg && !pause.rx_pause && !pause.tx_pause);
    assert(get_calls == 1);
    cases++;

    check_get(&dev, GSW_FLOW_AUTO, 1, 1, 1); cases++;
    check_get(&dev, GSW_FLOW_RXTX, 0, 1, 1); cases++;
    check_get(&dev, GSW_FLOW_RX, 0, 1, 0); cases++;
    check_get(&dev, GSW_FLOW_TX, 0, 0, 1); cases++;
    check_get(&dev, GSW_FLOW_OFF, 0, 0, 0); cases++;
    check_get(&dev, 99, 0, 0, 0); cases++;

    reset_fixture();
    ops_available = 0;
    pause = (struct ethtool_pauseparam){0};
    assert(set_pauseparam(&dev, &pause) == -EINVAL);
    assert(!get_calls && !set_calls);
    cases++;

    reset_fixture();
    get_result = -3;
    assert(set_pauseparam(&dev, &pause) == -EIO);
    assert(get_calls == 1 && !set_calls);
    cases++;

    check_set(&dev, 1, 1, 1, GSW_FLOW_AUTO); cases++;
    check_set(&dev, 0, 1, 1, GSW_FLOW_RXTX); cases++;
    check_set(&dev, 0, 1, 0, GSW_FLOW_RX); cases++;
    check_set(&dev, 0, 0, 1, GSW_FLOW_TX); cases++;
    check_set(&dev, 0, 0, 0, GSW_FLOW_OFF); cases++;

    reset_fixture();
    set_result = -3;
    pause = (struct ethtool_pauseparam){ .rx_pause = 1 };
    assert(set_pauseparam(&dev, &pause) == -EIO);
    assert(get_calls == 1 && set_calls == 1);
    cases++;

    printf("PASS: %u GRX500 ethtool pause cases\n", cases);
    return 0;
}
'''.replace('FUNCTIONS', functions)

with tempfile.TemporaryDirectory() as tmp:
    c_file = Path(tmp) / 'test.c'
    binary = Path(tmp) / 'test'
    c_file.write_text(harness)
    subprocess.run([
        'gcc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        str(c_file), '-o', str(binary),
    ], check=True)
    subprocess.run([str(binary)], check=True)
