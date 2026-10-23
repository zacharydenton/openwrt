/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef _NET_GRX500_SKB_H
#define _NET_GRX500_SKB_H
#include <linux/skbuff.h>
/* Owned only while the skb is in the GRX500 software datapath. */
struct grx500_skb_cb {
	u32 DW0, DW1, DW2, DW3;
};
static inline struct grx500_skb_cb *grx500_skb_cb(const struct sk_buff *skb)
{
	BUILD_BUG_ON(sizeof(struct grx500_skb_cb) > sizeof(skb->cb));
	return (struct grx500_skb_cb *)skb->cb;
}
#endif
