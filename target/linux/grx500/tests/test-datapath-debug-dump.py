#!/usr/bin/env python3
"""Exercise the exact GRX500 skb debug-dump bounds helper."""
from pathlib import Path
import re
import subprocess
import tempfile

base = Path(__file__).resolve().parents[1]
header = (base / 'files/drivers/net/datapath/dpm/datapath.h').read_text()
rx_source = (base /
             'files/drivers/net/datapath/dpm/gswip30/datapath_rx.c').read_text()
tx_source = (base / 'files/drivers/net/datapath/dpm/datapath_tx.c').read_text()


def extract(name):
    match = re.search(r'^static inline unsigned int ' + name +
                      r'\([^;]*?\)\s*\{', header, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (header[end] == '{') - (header[end] == '}')
        end += 1
    return header[match.start():end]


function = extract('dp_skb_dump_len')

# Every raw skb data dump must use the common linear-head bound. Fixed-size
# PMAC dumps have already been pulled into the linear head by the RX path.
assert rx_source.count('dp_skb_dump_len(') == 3
assert tx_source.count('dp_skb_dump_len(') == 1
assert 'skb->len > dp_print_len' not in rx_source
assert not re.search(r'dp_dump_raw_data\(skb->data,\s*skb->len', tx_source)

harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

struct sk_buff {
    unsigned int len;
    unsigned int head_len;
    unsigned char *data;
};

#define skb_headlen(skb) ((skb)->head_len)
#define min_t(type, a, b) ({ type _a = (a); type _b = (b); _a < _b ? _a : _b; })

FUNCTION

static volatile unsigned int reads;

static void consume(const struct sk_buff *skb, unsigned int offset, int limit)
{
    unsigned int len = dp_skb_dump_len(skb, offset, limit);
    unsigned int i;

    for (i = 0; i < len; i++)
        reads += skb->data[offset + i];
}

static void check(struct sk_buff *skb, unsigned int offset, int limit,
                  unsigned int expected)
{
    unsigned int actual = dp_skb_dump_len(skb, offset, limit);

    assert(actual == expected);
    consume(skb, offset, limit);
}

int main(void)
{
    struct sk_buff skb;
    unsigned int cases = 0;

    skb.data = malloc(64);
    assert(skb.data);
    for (unsigned int i = 0; i < 64; i++)
        skb.data[i] = (unsigned char)i;
    skb.len = 64;
    skb.head_len = 64;

    check(&skb, 0, 0, 64); cases++;
    check(&skb, 0, -1, 64); cases++;
    check(&skb, 0, 16, 16); cases++;
    check(&skb, 0, 64, 64); cases++;
    check(&skb, 0, 128, 64); cases++;
    check(&skb, 8, 0, 56); cases++;
    check(&skb, 8, 12, 12); cases++;
    check(&skb, 64, 32, 0); cases++;
    check(&skb, 80, 32, 0); cases++;

    /* Total length includes fragments; the raw-pointer dump stops at the
     * 64-byte linear allocation regardless of that larger logical length.
     */
    skb.len = 4096;
    check(&skb, 0, 4096, 64); cases++;
    check(&skb, 8, 4096, 56); cases++;

    free(skb.data);
    printf("PASS: %u GRX500 datapath debug-dump bound cases\n", cases);
    return reads == UINT32_MAX;
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
