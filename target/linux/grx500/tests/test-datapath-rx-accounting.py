#!/usr/bin/env python3
"""Exercise exact GRX500 datapath callback-result accounting and ownership."""
from pathlib import Path
import re
import subprocess
import tempfile

source = (Path(__file__).resolve().parents[1] /
          'files/drivers/net/datapath/dpm/gswip30/datapath_rx.c').read_text()


def extract(return_type, name):
    match = re.search(r'^static ' + return_type + r' ' + name +
                      r'\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


function = extract('void', 'dp_rx_deliver')

harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

struct net_device;
struct sk_buff;
typedef int32_t dp_rx_fn_t(struct net_device *rxif,
                           struct net_device *txif,
                           struct sk_buff *skb, int32_t len);

#define DP_SUCCESS 0
#define UP_STATS(counter) ((counter)++)
#define MIB_G_STATS_INC(counter) (global_stats.counter++)

struct net_device { int id; };
struct sk_buff { unsigned int consumed; };
struct dev_mib {
    unsigned int rx_fn_rxif_pkt;
    unsigned int rx_fn_txif_pkt;
    unsigned int rx_fn_dropped;
};
struct mib_global_stats {
    unsigned int rx_rxif_pkts;
    unsigned int rx_txif_pkts;
    unsigned int rx_rxif_clone;
    unsigned int rx_drop;
};
static struct mib_global_stats global_stats;

enum dp_rx_delivery {
    DP_RX_DELIVER_RX,
    DP_RX_DELIVER_TX,
    DP_RX_DELIVER_LCT_CLONE,
};

static struct net_device *expected_rxif;
static struct net_device *expected_txif;
static struct sk_buff *expected_skb;
static int32_t expected_len;
static int callback_result;
static unsigned int callback_calls;

static int32_t callback(struct net_device *rxif, struct net_device *txif,
                        struct sk_buff *skb, int32_t len)
{
    assert(rxif == expected_rxif);
    assert(txif == expected_txif);
    assert(skb == expected_skb);
    assert(len == expected_len);
    assert(!skb->consumed);
    skb->consumed++;
    callback_calls++;
    return callback_result;
}

FUNCTION

static void reset_fixture(struct dev_mib *mib, struct sk_buff *skb)
{
    memset(mib, 0, sizeof(*mib));
    memset(skb, 0, sizeof(*skb));
    memset(&global_stats, 0, sizeof(global_stats));
    callback_result = DP_SUCCESS;
    callback_calls = 0;
    expected_skb = skb;
    expected_len = 73;
}

static void assert_only_drop(const struct dev_mib *mib)
{
    assert(!mib->rx_fn_rxif_pkt && !mib->rx_fn_txif_pkt);
    assert(mib->rx_fn_dropped == 1);
    assert(!global_stats.rx_rxif_pkts && !global_stats.rx_txif_pkts);
    assert(!global_stats.rx_rxif_clone && global_stats.rx_drop == 1);
}

int main(void)
{
    struct net_device rx = { .id = 1 }, tx = { .id = 2 };
    struct dev_mib mib;
    struct sk_buff skb;
    unsigned int cases = 0;

    reset_fixture(&mib, &skb);
    expected_rxif = &rx; expected_txif = NULL;
    dp_rx_deliver(callback, &rx, NULL, &skb, 73, &mib,
                  DP_RX_DELIVER_RX);
    assert(callback_calls == 1 && skb.consumed == 1);
    assert(mib.rx_fn_rxif_pkt == 1 && !mib.rx_fn_txif_pkt);
    assert(!mib.rx_fn_dropped && global_stats.rx_rxif_pkts == 1);
    assert(!global_stats.rx_txif_pkts && !global_stats.rx_rxif_clone);
    assert(!global_stats.rx_drop);
    cases++;

    reset_fixture(&mib, &skb);
    expected_rxif = &rx; expected_txif = NULL; callback_result = -1;
    dp_rx_deliver(callback, &rx, NULL, &skb, 73, &mib,
                  DP_RX_DELIVER_RX);
    assert(callback_calls == 1 && skb.consumed == 1);
    assert_only_drop(&mib);
    cases++;

    reset_fixture(&mib, &skb);
    expected_rxif = &rx; expected_txif = NULL; callback_result = 2;
    dp_rx_deliver(callback, &rx, NULL, &skb, 73, &mib,
                  DP_RX_DELIVER_RX);
    assert(callback_calls == 1 && skb.consumed == 1);
    assert_only_drop(&mib);
    cases++;

    reset_fixture(&mib, &skb);
    expected_rxif = NULL; expected_txif = &tx;
    dp_rx_deliver(callback, NULL, &tx, &skb, 73, &mib,
                  DP_RX_DELIVER_TX);
    assert(callback_calls == 1 && skb.consumed == 1);
    assert(!mib.rx_fn_rxif_pkt && mib.rx_fn_txif_pkt == 1);
    assert(!mib.rx_fn_dropped && global_stats.rx_txif_pkts == 1);
    assert(!global_stats.rx_rxif_pkts && !global_stats.rx_rxif_clone);
    assert(!global_stats.rx_drop);
    cases++;

    reset_fixture(&mib, &skb);
    expected_rxif = NULL; expected_txif = &tx; callback_result = -1;
    dp_rx_deliver(callback, NULL, &tx, &skb, 73, &mib,
                  DP_RX_DELIVER_TX);
    assert(callback_calls == 1 && skb.consumed == 1);
    assert_only_drop(&mib);
    cases++;

    reset_fixture(&mib, &skb);
    expected_rxif = &rx; expected_txif = NULL;
    dp_rx_deliver(callback, &rx, NULL, &skb, 73, &mib,
                  DP_RX_DELIVER_LCT_CLONE);
    assert(callback_calls == 1 && skb.consumed == 1);
    assert(mib.rx_fn_rxif_pkt == 1 && !mib.rx_fn_txif_pkt);
    assert(!mib.rx_fn_dropped && global_stats.rx_rxif_clone == 1);
    assert(!global_stats.rx_rxif_pkts && !global_stats.rx_txif_pkts);
    assert(!global_stats.rx_drop);
    cases++;

    reset_fixture(&mib, &skb);
    expected_rxif = &rx; expected_txif = NULL; callback_result = -1;
    dp_rx_deliver(callback, &rx, NULL, &skb, 73, &mib,
                  DP_RX_DELIVER_LCT_CLONE);
    assert(callback_calls == 1 && skb.consumed == 1);
    assert_only_drop(&mib);
    cases++;

    printf("PASS: %u GRX500 datapath RX callback accounting cases\n", cases);
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
