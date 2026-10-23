#!/usr/bin/env python3
"""Exercise GRX500 Ethernet flow control and watchdog recovery."""
from pathlib import Path
import re
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] /
          'files/drivers/net/ethernet/lantiq/ltq_eth_drv_xrx500.c').read_text()


def extract(name):
    match = re.search(r'^static (?:int32_t|void) ' + name +
                      r'\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


functions = '\n\n'.join(extract(name) for name in (
    'dp_fp_stop_tx', 'dp_fp_restart_tx', 'ltq_tx_timeout'))

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>

#define DP_SUCCESS 0

struct rtnl_link_stats64 {
    uint64_t tx_errors;
};

struct ltq_eth_priv {
    struct rtnl_link_stats64 stats;
};

struct net_device {
    unsigned int num_tx_queues;
    int running;
    struct ltq_eth_priv *priv;
};

static struct net_device *expected_dev;
static unsigned int stopped_queues;
static unsigned int stop_calls;
static unsigned int woken_queues;
static unsigned int wake_calls;
static unsigned int warning_calls;
static unsigned int warned_queue;

static void netif_tx_stop_all_queues(struct net_device *dev)
{
    assert(dev == expected_dev);
    stop_calls++;
    stopped_queues += dev->num_tx_queues;
}

static int netif_running(const struct net_device *dev)
{
    assert(dev == expected_dev);
    return dev->running;
}

static void netif_tx_wake_all_queues(struct net_device *dev)
{
    assert(dev == expected_dev);
    wake_calls++;
    woken_queues += dev->num_tx_queues;
}

static void *netdev_priv(const struct net_device *dev)
{
    assert(dev == expected_dev);
    return dev->priv;
}

static void record_netdev_warning(struct net_device *dev, unsigned int queue)
{
    assert(dev == expected_dev);
    warning_calls++;
    warned_queue = queue;
}

#define netdev_warn(dev, format, ...) record_netdev_warning(dev, __VA_ARGS__)

FUNCTIONS

int main(void)
{
    struct ltq_eth_priv priv = { .stats.tx_errors = 41 };
    struct net_device dev = {
        .num_tx_queues = 8,
        .running = 0,
        .priv = &priv,
    };

    assert(dp_fp_stop_tx(NULL) == -EINVAL);
    assert(stop_calls == 0);

    expected_dev = &dev;
    assert(dp_fp_stop_tx(&dev) == DP_SUCCESS);
    assert(stop_calls == 1);
    assert(stopped_queues == 8);

    assert(dp_fp_restart_tx(NULL) == -EINVAL);
    assert(wake_calls == 0);

    assert(dp_fp_restart_tx(&dev) == DP_SUCCESS);
    assert(wake_calls == 0);
    assert(woken_queues == 0);

    dev.running = 1;
    assert(dp_fp_restart_tx(&dev) == DP_SUCCESS);
    assert(wake_calls == 1);
    assert(woken_queues == 8);

    ltq_tx_timeout(&dev, 7);
    assert(priv.stats.tx_errors == 42);
    assert(wake_calls == 2);
    assert(woken_queues == 16);
    assert(warning_calls == 1);
    assert(warned_queue == 7);

    dev.num_tx_queues = 1;
    ltq_tx_timeout(&dev, 0);
    assert(priv.stats.tx_errors == 43);
    assert(wake_calls == 3);
    assert(woken_queues == 17);
    assert(warning_calls == 2);
    assert(warned_queue == 0);

    puts("PASS: 7 GRX500 Ethernet flow-control and timeout cases");
    return 0;
}
'''.replace('FUNCTIONS', functions)

with tempfile.TemporaryDirectory(prefix='grx500-ethernet-flow-') as tmp:
    path = Path(tmp)
    (path / 'probe.c').write_text(harness)
    subprocess.run([
        'gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fno-pie', '-no-pie', '-fsanitize=address,undefined',
        '-fno-omit-frame-pointer', str(path / 'probe.c'), '-o',
        str(path / 'probe')
    ], check=True)
    subprocess.run([str(path / 'probe')], cwd=path, check=True)
