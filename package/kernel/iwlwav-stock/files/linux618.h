#ifndef WAVE_LINUX618_H
#define WAVE_LINUX618_H
#include <linux/timer.h>
#include <linux/dma-mapping.h>
#include <crypto/arc4.h>
#include <net/mac80211.h>
#define del_timer timer_delete
#define del_timer_sync timer_delete_sync
#define PCI_DMA_BIDIRECTIONAL DMA_BIDIRECTIONAL
#define PCI_DMA_FROMDEVICE DMA_FROM_DEVICE
#define PCI_DMA_TODEVICE DMA_TO_DEVICE
/* Sizes and WEXT values from the matching vendor 3.10 wireless API. */
#define IEEE80211_HE_CAPABILITIES_SIZE 64
#define IW_ENCODE_ALG_GCMP 6
#define IW_ENCODE_ALG_GCMP_256 7
static inline struct ieee80211_vif *net_device_to_ieee80211_vif(struct net_device *dev)
{ return wdev_to_ieee80211_vif(dev->ieee80211_ptr); }
#include <linux/if_arp.h>
#define PDE_DATA pde_data
#define getnstimeofday ktime_get_real_ts64
static inline const char *ieee80211_vif_to_name(struct ieee80211_vif *vif)
{ return ieee80211_vif_to_wdev(vif)->netdev->name; }
#endif
