#!/usr/bin/env python3
"""Exercise GRX500 Ethernet datapath RX/TX callback ownership and bounds."""
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


functions = '\n\n'.join((extract('int', 'eth_rx'),
                           extract('int32_t', 'dp_fp_rx')))

harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef uint32_t u32;
typedef struct { unsigned char bytes[8]; } ltq_pmac_header_t;

#define ETH_HLEN 14
#define DP_SUCCESS 0
#define DP_FAILURE -1
#define NET_RX_SUCCESS 0
#define NET_RX_DROP 1
#define NET_XMIT_SUCCESS 0
#define NET_XMIT_DROP 1
#define NET_XMIT_CN 2
#define NETIF_F_RXCSUM 1UL
#define CHECKSUM_NONE 0
#define CHECKSUM_UNNECESSARY 1
#define pr_debug(...) do { } while (0)
#define pr_err(...) do { } while (0)
#define pr_err_ratelimited(...) do { } while (0)
#define net_xmit_eval(result) ((result) == NET_XMIT_CN ? 0 : (result))

struct rtnl_link_stats64 {
    uint64_t rx_packets;
    uint64_t rx_bytes;
    uint64_t rx_dropped;
    uint64_t rx_errors;
    uint64_t rx_length_errors;
    uint64_t tx_dropped;
};

struct ltq_eth_priv {
    struct rtnl_link_stats64 stats;
};

struct net_device {
    char name[8];
    unsigned long features;
    int running;
    struct ltq_eth_priv *priv;
};

struct sk_buff {
    unsigned char storage[128];
    unsigned char *data;
    u32 len;
    u32 head_len;
    struct net_device *dev;
    uint16_t protocol;
    int ip_summed;
    unsigned int consumed;
};

static struct net_device *expected_dev;
static int may_pull_failure;
static int trim_failure;
static int netif_result;
static int xmit_result;
static unsigned int free_calls;
static unsigned int may_pull_calls;
static unsigned int may_pull_length;
static unsigned int trim_calls;
static unsigned int trim_length;
static unsigned int netif_calls;
static unsigned int xmit_calls;
static unsigned int type_calls;
static unsigned int netif_length;
static unsigned int xmit_length;
static unsigned int xmit_data_offset;

static void *netdev_priv(const struct net_device *dev)
{
    assert(dev == expected_dev);
    return dev->priv;
}

static int netif_running(const struct net_device *dev)
{
    assert(dev == expected_dev);
    return dev->running;
}

static int pskb_may_pull(struct sk_buff *skb, unsigned int len)
{
    may_pull_calls++;
    may_pull_length = len;
    if (may_pull_failure || len > skb->len)
        return 0;
    if (skb->head_len < len)
        skb->head_len = len;
    return 1;
}

static int pskb_trim(struct sk_buff *skb, unsigned int len)
{
    trim_calls++;
    trim_length = len;
    if (trim_failure)
        return -ENOMEM;
    if (len < skb->len) {
        skb->len = len;
        if (skb->head_len > len)
            skb->head_len = len;
    }
    return 0;
}

static void *skb_pull(struct sk_buff *skb, unsigned int len)
{
    assert(len <= skb->len);
    assert(len <= skb->head_len);
    skb->data += len;
    skb->len -= len;
    skb->head_len -= len;
    return skb->data;
}

static uint16_t eth_type_trans(struct sk_buff *skb, struct net_device *dev)
{
    assert(dev == expected_dev);
    type_calls++;
    skb_pull(skb, ETH_HLEN);
    return 0x0800;
}

static int netif_rx(struct sk_buff *skb)
{
    assert(skb->dev == expected_dev);
    assert(!skb->consumed);
    netif_calls++;
    netif_length = skb->len;
    skb->consumed++;
    return netif_result;
}

static int dev_queue_xmit(struct sk_buff *skb)
{
    assert(skb->dev == expected_dev);
    assert(!skb->consumed);
    xmit_calls++;
    xmit_length = skb->len;
    xmit_data_offset = (unsigned int)(skb->data - skb->storage);
    skb->consumed++;
    return xmit_result;
}

static void dev_kfree_skb_any(struct sk_buff *skb)
{
    assert(!skb->consumed);
    free_calls++;
    skb->consumed++;
}

FUNCTIONS

static void init_skb(struct sk_buff *skb, u32 len, u32 head_len)
{
    memset(skb, 0, sizeof(*skb));
    assert(len <= sizeof(skb->storage));
    assert(head_len <= len);
    for (u32 i = 0; i < len; i++)
        skb->storage[i] = (unsigned char)(i * 17 + 3);
    skb->data = skb->storage;
    skb->len = len;
    skb->head_len = head_len;
    skb->ip_summed = CHECKSUM_NONE;
}

static void reset_fixture(struct ltq_eth_priv *priv)
{
    memset(priv, 0, sizeof(*priv));
    may_pull_failure = trim_failure = 0;
    netif_result = NET_RX_SUCCESS;
    xmit_result = NET_XMIT_SUCCESS;
    free_calls = may_pull_calls = may_pull_length = 0;
    trim_calls = trim_length = netif_calls = xmit_calls = type_calls = 0;
    netif_length = xmit_length = xmit_data_offset = 0;
}

int main(void)
{
    struct ltq_eth_priv rx_priv, tx_priv;
    struct net_device rx = {
        .name = "lan1", .features = NETIF_F_RXCSUM, .running = 1,
        .priv = &rx_priv,
    };
    struct net_device tx = {
        .name = "wan", .features = 0, .running = 1, .priv = &tx_priv,
    };
    struct sk_buff skb;
    unsigned int cases = 0;

    reset_fixture(&rx_priv);
    expected_dev = &rx;
    assert(dp_fp_rx(&rx, NULL, NULL, 60) == DP_FAILURE);
    assert(!free_calls);
    cases++;

    init_skb(&skb, 21, 21);
    assert(dp_fp_rx(&rx, NULL, &skb, 21) == DP_FAILURE);
    assert(skb.consumed == 1 && free_calls == 1);
    assert(rx_priv.stats.rx_errors == 1);
    assert(rx_priv.stats.rx_length_errors == 1);
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 60, 60);
    assert(dp_fp_rx(&rx, NULL, &skb, -1) == DP_FAILURE);
    assert(skb.consumed == 1 && rx_priv.stats.rx_length_errors == 1);
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 60, 60);
    assert(dp_fp_rx(&rx, NULL, &skb, 61) == DP_FAILURE);
    assert(skb.consumed == 1 && rx_priv.stats.rx_length_errors == 1);
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 60, 4);
    may_pull_failure = 1;
    assert(dp_fp_rx(&rx, NULL, &skb, 60) == DP_FAILURE);
    assert(may_pull_calls == 1 && may_pull_length == 22);
    assert(skb.consumed == 1 && rx_priv.stats.rx_length_errors == 1);
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 64, 22);
    trim_failure = 1;
    assert(dp_fp_rx(&rx, NULL, &skb, 60) == DP_FAILURE);
    assert(trim_calls == 1 && trim_length == 60);
    assert(skb.consumed == 1 && rx_priv.stats.rx_errors == 1);
    assert(rx_priv.stats.rx_length_errors == 0);
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 60, 60);
    expected_dev = NULL;
    assert(dp_fp_rx(NULL, NULL, &skb, 60) == DP_FAILURE);
    assert(skb.consumed == 1 && free_calls == 1);
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 60, 60);
    rx.running = 0;
    expected_dev = &rx;
    assert(dp_fp_rx(&rx, NULL, &skb, 60) == DP_FAILURE);
    assert(skb.consumed == 1 && rx_priv.stats.rx_dropped == 1);
    assert(!netif_calls);
    rx.running = 1;
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 64, 4);
    assert(dp_fp_rx(&rx, NULL, &skb, 60) == DP_SUCCESS);
    assert(may_pull_calls == 1 && may_pull_length == 22);
    assert(trim_calls == 1 && trim_length == 60);
    assert(skb.consumed == 1 && netif_calls == 1 && type_calls == 1);
    assert(netif_length == 38 && skb.ip_summed == CHECKSUM_UNNECESSARY);
    assert(rx_priv.stats.rx_packets == 1 && rx_priv.stats.rx_bytes == 52);
    cases++;

    reset_fixture(&rx_priv);
    init_skb(&skb, 60, 60);
    netif_result = NET_RX_DROP;
    assert(dp_fp_rx(&rx, NULL, &skb, 60) == DP_FAILURE);
    assert(skb.consumed == 1 && rx_priv.stats.rx_dropped == 1);
    assert(!rx_priv.stats.rx_packets && !rx_priv.stats.rx_bytes);
    cases++;

    reset_fixture(&rx_priv);
    reset_fixture(&tx_priv);
    init_skb(&skb, 60, 60);
    expected_dev = &rx;
    assert(dp_fp_rx(&rx, &tx, &skb, 60) == DP_SUCCESS);
    assert(netif_calls == 1 && !xmit_calls);
    cases++;

    reset_fixture(&tx_priv);
    init_skb(&skb, 60, 60);
    tx.running = 0;
    expected_dev = &tx;
    assert(dp_fp_rx(NULL, &tx, &skb, 60) == DP_FAILURE);
    assert(skb.consumed == 1 && tx_priv.stats.tx_dropped == 1);
    assert(!xmit_calls);
    tx.running = 1;
    cases++;

    reset_fixture(&tx_priv);
    init_skb(&skb, 60, 22);
    assert(dp_fp_rx(NULL, &tx, &skb, 60) == DP_SUCCESS);
    assert(skb.consumed == 1 && xmit_calls == 1);
    assert(xmit_length == 52 && xmit_data_offset == 8);
    assert(!tx_priv.stats.tx_dropped);
    cases++;

    reset_fixture(&tx_priv);
    init_skb(&skb, 60, 60);
    xmit_result = NET_XMIT_CN;
    assert(dp_fp_rx(NULL, &tx, &skb, 60) == DP_SUCCESS);
    assert(skb.consumed == 1 && !tx_priv.stats.tx_dropped);
    cases++;

    reset_fixture(&tx_priv);
    init_skb(&skb, 60, 60);
    xmit_result = NET_XMIT_DROP;
    assert(dp_fp_rx(NULL, &tx, &skb, 60) == DP_FAILURE);
    assert(skb.consumed == 1 && tx_priv.stats.tx_dropped == 1);
    assert(!free_calls);
    cases++;

    reset_fixture(&tx_priv);
    init_skb(&skb, 60, 60);
    xmit_result = -ENETDOWN;
    assert(dp_fp_rx(NULL, &tx, &skb, 60) == DP_FAILURE);
    assert(skb.consumed == 1 && tx_priv.stats.tx_dropped == 1);
    assert(!free_calls);
    cases++;

    printf("PASS: %u GRX500 Ethernet datapath RX/TX cases\n", cases);
    return 0;
}
'''.replace('FUNCTIONS', functions)

with tempfile.TemporaryDirectory(prefix='grx500-ethernet-rx-') as tmp:
    path = Path(tmp)
    (path / 'probe.c').write_text(harness)
    subprocess.run([
        'gcc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fno-pie', '-no-pie', '-fsanitize=address,undefined',
        '-fno-omit-frame-pointer', str(path / 'probe.c'), '-o',
        str(path / 'probe')
    ], check=True)
    subprocess.run([str(path / 'probe')], cwd=path, check=True)
