#!/usr/bin/env python3
"""Exercise the patched mac80211 RX/status callbacks and admission gate."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("tree", type=Path)
parser.add_argument("--cc", default="gcc")
parser.add_argument("--qemu", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
source = (args.tree / "wireless/driver/linux/mac80211.c").read_text()
radio = (args.tree / "wireless/driver/linux/wave_radio.c").read_text()
driver = (args.tree / "wireless/driver/linux/mtlk_mmb_drv.c").read_text()


def extract(name):
    match = re.search(
        r"^(?:static\s+)?(?:void|bool)\s+(?:__MTLK_IFUNC\s+)?" + name
        + r"\s*\([^;]*?\)\s*\{", source, re.M
    )
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


names = (
    "wave_sta_tx_lifetime_init",
    "wave_sta_tx_get",
    "wave_sta_tx_put",
    "wave_sta_tx_idle",
    "wv_ieee80211_tx_quiesce",
    "wv_ieee80211_mngmn_frame_rx",
    "wv_ieee80211_tx_status",
)
functions = "\n\n".join(extract(name) for name in names)
assert "if (!mac80211 || !wave_sta_tx_get(mac80211))" in functions
assert "dev_kfree_skb_any(skb);" in extract("wv_ieee80211_tx_status")
assert driver.index("wave_radio_mac80211_tx_quiesce(radio_descr);") < driver.index(
    "_mmb_drv_mac80211_deinit, (obj, radio_descr)"
)
assert radio.index("wv_ieee80211_unregister(radio->mac80211);") < radio.index(
    "wv_ieee80211_free(radio->mac80211);"
)

harness = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define __MTLK_IFUNC
#define ELOG_V(...) ((void)0)
#define WARN_ON_ONCE(c) (c)
#define TX_STATUS_SUCCESS 1
#define IEEE80211_TX_CTL_NO_ACK 1
#define IEEE80211_TX_STAT_ACK 2
#define spin_lock_init(p) pthread_mutex_init((p), NULL)
#define spin_lock_irqsave(p,f) do { (f)=0; pthread_mutex_lock(p); } while(0)
#define spin_unlock_irqrestore(p,f) do { (void)(f); pthread_mutex_unlock(p); } while(0)
#define init_waitqueue_head(p) (*(p)=0)
#define wake_up_all(p) ((void)0)
#define wait_event(w, condition) do { (void)(w); while (!(condition)) usleep(100); } while(0)
typedef pthread_mutex_t spinlock_t;
typedef unsigned char u8;
typedef uint8_t uint8;
typedef uint16_t uint16;
typedef struct wave_sta_tx_lifetime {
  spinlock_t lock; int wait; unsigned users; bool stopping;
} wave_sta_tx_lifetime_t;
struct ieee80211_hw { void *priv; };
typedef struct _wv_mac80211_t {
  struct wave_sta_tx_lifetime tx_lifetime;
  struct ieee80211_hw *mac80211_hw;
} wv_mac80211_t;
typedef struct { wv_mac80211_t *mac; } wave_radio_t;
typedef struct { wave_radio_t *vap_handle; } mtlk_core_t;
struct ieee80211_rx_status { int marker; };
struct ieee80211_tx_info { unsigned flags; };
struct sk_buff { unsigned char data[256]; unsigned len; struct ieee80211_rx_status rx;
  struct ieee80211_tx_info tx; };
#define IEEE80211_SKB_RXCB(s) (&(s)->rx)
#define IEEE80211_SKB_CB(s) (&(s)->tx)
static unsigned allocated, freed, rx_callbacks, tx_callbacks, acked;
static int wiphy_live=1, block_rx, rx_entered, allow_rx, quiesce_done;
static pthread_mutex_t cb_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cb_cond=PTHREAD_COND_INITIALIZER;
static wave_radio_t radio;
static wv_mac80211_t owner;
static struct ieee80211_hw hw;
static mtlk_core_t nic;
static wave_radio_t *wave_vap_radio_get(wave_radio_t *vap){return vap;}
static wv_mac80211_t *wave_radio_mac80211_get(wave_radio_t *r){return r->mac;}
static wv_mac80211_t *__wv_ieee80211_hw_get_mac80211(struct ieee80211_hw *h){return h->priv;}
static struct sk_buff *dev_alloc_skb(int size){assert(size>0&&size<256);
  struct sk_buff *s=calloc(1,sizeof(*s));assert(s);__sync_add_and_fetch(&allocated,1);return s;}
static void dev_kfree_skb_any(struct sk_buff *s){assert(s);__sync_add_and_fetch(&freed,1);free(s);}
static void *skb_put(struct sk_buff *s,int size){s->len=size;return s->data;}
static void wave_memcpy(void *dst,int cap,const void *src,int size){assert(size<=cap);memcpy(dst,src,size);}
static void _wv_ieee80211_hw_rx_status(struct ieee80211_hw *h,struct ieee80211_rx_status *r,
  int f,int sig,uint16 rate,u8 mode,uint8 pmf){(void)h;(void)r;(void)f;(void)sig;(void)rate;(void)mode;(void)pmf;}
static void ieee80211_rx_irqsafe(struct ieee80211_hw *h,struct sk_buff *s){
  assert(h==&hw && __atomic_load_n(&wiphy_live,__ATOMIC_ACQUIRE));
  pthread_mutex_lock(&cb_lock);++rx_callbacks;
  if(block_rx){rx_entered=1;pthread_cond_broadcast(&cb_cond);
    while(!allow_rx)pthread_cond_wait(&cb_cond,&cb_lock);}
  pthread_mutex_unlock(&cb_lock);dev_kfree_skb_any(s);
}
static void ieee80211_tx_status_irqsafe(struct ieee80211_hw *h,struct sk_buff *s){
  assert(h==&hw && __atomic_load_n(&wiphy_live,__ATOMIC_ACQUIRE));
  __sync_add_and_fetch(&tx_callbacks,1);
  if(s->tx.flags&IEEE80211_TX_STAT_ACK)__sync_add_and_fetch(&acked,1);
  dev_kfree_skb_any(s);
}
FUNCTIONS
static void setup(void){memset(&owner,0,sizeof(owner));hw.priv=&owner;owner.mac80211_hw=&hw;
  radio.mac=&owner;nic.vap_handle=&radio;wave_sta_tx_lifetime_init(&owner);
  allocated=freed=rx_callbacks=tx_callbacks=acked=0;
  wiphy_live=1;block_rx=rx_entered=allow_rx=quiesce_done=0;}
static void finish(void){assert(allocated==freed && wave_sta_tx_idle(&owner));
  pthread_mutex_destroy(&owner.tx_lifetime.lock);}
static void recv(void){static const u8 frame[24]={1,2,3};
  wv_ieee80211_mngmn_frame_rx(&nic,frame,sizeof(frame),5180,-42,0,0,0,0);}
static void status(void){struct sk_buff *s=dev_alloc_skb(32);
  wv_ieee80211_tx_status(&hw,s,TX_STATUS_SUCCESS);}
static void *rx_thread(void *unused){(void)unused;recv();return NULL;}
static void *close_thread(void *unused){(void)unused;wv_ieee80211_tx_quiesce(&owner);
  __atomic_store_n(&quiesce_done,1,__ATOMIC_RELEASE);return NULL;}
static void *producer(void *unused){(void)unused;for(int i=0;i<1000;i++){
  recv();status();if(!(i%7))usleep(1);}return NULL;}
int main(void){
  setup();recv();status();assert(rx_callbacks==1 && tx_callbacks==1 && acked==1);
  wv_ieee80211_tx_quiesce(&owner);wiphy_live=0;recv();status();
  assert(rx_callbacks==1 && tx_callbacks==1 && allocated==freed);finish();
  puts("PASS: ordinary callbacks, post-close RX rejection and skb release");

  setup();block_rx=1;pthread_t rx,closer;
  assert(!pthread_create(&rx,NULL,rx_thread,NULL));
  pthread_mutex_lock(&cb_lock);while(!rx_entered)pthread_cond_wait(&cb_cond,&cb_lock);
  pthread_mutex_unlock(&cb_lock);
  assert(!pthread_create(&closer,NULL,close_thread,NULL));usleep(20000);
  assert(!__atomic_load_n(&quiesce_done,__ATOMIC_ACQUIRE));
  pthread_mutex_lock(&cb_lock);allow_rx=1;pthread_cond_broadcast(&cb_cond);
  pthread_mutex_unlock(&cb_lock);pthread_join(rx,NULL);pthread_join(closer,NULL);
  wiphy_live=0;recv();status();assert(rx_callbacks==1 && tx_callbacks==0);
  finish();puts("PASS: quiesce waits for in-flight management RX");

  setup();pthread_t workers[4];for(int i=0;i<4;i++)
    assert(!pthread_create(&workers[i],NULL,producer,NULL));
  usleep(1000);wv_ieee80211_tx_quiesce(&owner);wiphy_live=0;
  for(int i=0;i<4;i++)pthread_join(workers[i],NULL);
  assert(allocated==freed);finish();
  puts("PASS: four producers race with closure without late callbacks or leaks");
  return 0;
}
'''.replace("\nFUNCTIONS\n", "\n" + functions + "\n")


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "probe.c").write_text(harness)
    flags = ["-static"] if args.qemu else ["-fsanitize=address,undefined", "-fno-pie", "-no-pie"]
    subprocess.run([args.cc, "-std=gnu11", "-O1", "-g", "-pthread", *flags,
                    str(output / "probe.c"), "-o", str(output / "probe")], check=True)
    command = [str(output / "probe")]
    if args.qemu:
        command.insert(0, str(args.qemu.resolve()))
    subprocess.run(command, check=True, cwd=output)


if args.output:
    run(args.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix="wave-mac-callback-") as temporary:
        run(Path(temporary))
