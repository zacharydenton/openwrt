#!/usr/bin/env python3
"""Exercise GRX500 Ethernet MAC-address updates against the exact driver code."""
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


function = extract('int', 'ltq_set_mac_address')

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint8_t u8;

#define ETH_ALEN 6
#define pr_debug(...) do { } while (0)

struct sockaddr {
    unsigned short sa_family;
    u8 sa_data[14];
};

struct ltq_eth_priv {
    int xgmac_id;
};

struct net_device {
    const u8 *dev_addr;
    u8 addr_storage[ETH_ALEN];
    int running;
    struct ltq_eth_priv *priv;
};

struct mac_ops {
    int (*set_macaddr)(struct mac_ops *ops, u8 *mac_addr);
};

static struct mac_ops mock_ops;
static int return_ops;
static int requested_devid;
static int requested_mac_id;
static unsigned int hw_set_calls;
static unsigned int mac_set_calls;
static u8 programmed_addr[ETH_ALEN];

static void *netdev_priv(const struct net_device *dev)
{
    return dev->priv;
}

static int netif_running(const struct net_device *dev)
{
    return dev->running;
}

static int is_valid_ether_addr(const u8 *addr)
{
    static const u8 zero[ETH_ALEN];

    return !(addr[0] & 1) && memcmp(addr, zero, ETH_ALEN);
}

static void ether_addr_copy(u8 *dest, const u8 *src)
{
    memcpy(dest, src, ETH_ALEN);
}

static void eth_hw_addr_set(struct net_device *dev, const u8 *addr)
{
    hw_set_calls++;
    memcpy(dev->addr_storage, addr, ETH_ALEN);
    dev->dev_addr = dev->addr_storage;
}

static struct mac_ops *gsw_get_mac_ops(int devid, int mac_id)
{
    requested_devid = devid;
    requested_mac_id = mac_id;
    return return_ops ? &mock_ops : NULL;
}

static int mock_set_macaddr(struct mac_ops *ops, u8 *mac_addr)
{
    assert(ops == &mock_ops);
    mac_set_calls++;
    memcpy(programmed_addr, mac_addr, ETH_ALEN);
    return 0;
}

FUNCTION

static void reset_fixture(struct net_device *dev, struct ltq_eth_priv *priv)
{
    static const u8 original[ETH_ALEN] = { 0x02, 0, 0, 0, 0, 1 };

    memset(dev, 0, sizeof(*dev));
    memset(priv, 0, sizeof(*priv));
    memcpy(dev->addr_storage, original, ETH_ALEN);
    dev->dev_addr = dev->addr_storage;
    dev->priv = priv;
    priv->xgmac_id = -1;
    return_ops = requested_devid = requested_mac_id = 0;
    hw_set_calls = mac_set_calls = 0;
    memset(programmed_addr, 0, sizeof(programmed_addr));
    mock_ops.set_macaddr = mock_set_macaddr;
}

int main(void)
{
    static const u8 valid[ETH_ALEN] = { 0x02, 0xaa, 0xbb, 0xcc, 0xdd, 0xee };
    static const u8 multicast[ETH_ALEN] = { 0x01, 0, 0, 0, 0, 1 };
    struct ltq_eth_priv priv;
    struct net_device dev;
    struct sockaddr addr = {0};
    unsigned int cases = 0;

    reset_fixture(&dev, &priv);
    memcpy(addr.sa_data, valid, ETH_ALEN);
    dev.running = 1;
    assert(ltq_set_mac_address(&dev, &addr) == -EBUSY);
    assert(!hw_set_calls && !mac_set_calls);
    cases++;

    reset_fixture(&dev, &priv);
    memset(addr.sa_data, 0, ETH_ALEN);
    assert(ltq_set_mac_address(&dev, &addr) == -EINVAL);
    assert(!hw_set_calls);
    cases++;

    reset_fixture(&dev, &priv);
    memcpy(addr.sa_data, multicast, ETH_ALEN);
    assert(ltq_set_mac_address(&dev, &addr) == -EINVAL);
    assert(!hw_set_calls);
    cases++;

    reset_fixture(&dev, &priv);
    memcpy(addr.sa_data, valid, ETH_ALEN);
    assert(ltq_set_mac_address(&dev, &addr) == 0);
    assert(hw_set_calls == 1 && !memcmp(dev.dev_addr, valid, ETH_ALEN));
    assert(!mac_set_calls);
    cases++;

    reset_fixture(&dev, &priv);
    priv.xgmac_id = 3;
    memcpy(addr.sa_data, valid, ETH_ALEN);
    assert(ltq_set_mac_address(&dev, &addr) == 0);
    assert(hw_set_calls == 1 && !mac_set_calls);
    assert(requested_devid == 0 && requested_mac_id == 3);
    cases++;

    reset_fixture(&dev, &priv);
    priv.xgmac_id = 4;
    return_ops = 1;
    memcpy(addr.sa_data, valid, ETH_ALEN);
    assert(ltq_set_mac_address(&dev, &addr) == 0);
    assert(hw_set_calls == 1 && mac_set_calls == 1);
    assert(!memcmp(dev.dev_addr, valid, ETH_ALEN));
    assert(!memcmp(programmed_addr, valid, ETH_ALEN));
    assert(!memcmp(addr.sa_data, valid, ETH_ALEN));
    cases++;

    printf("PASS: %u GRX500 Ethernet MAC-address cases\n", cases);
    return 0;
}
'''.replace('FUNCTION', function)

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
