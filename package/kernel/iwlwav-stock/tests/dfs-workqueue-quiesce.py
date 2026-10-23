#!/usr/bin/env python3
"""Run the actual DFS workqueue producer/worker/quiesce functions in pthread fixtures."""

import argparse
from pathlib import Path
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('tree', type=Path)
parser.add_argument('--cc', default='gcc')
parser.add_argument('--qemu', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source = (args.tree / 'wireless/driver/linux/mtlk_df_user.c').read_text()
radio = (args.tree / 'wireless/driver/linux/wave_radio.c').read_text()
driver = (args.tree / 'wireless/driver/linux/mtlk_mmb_drv.c').read_text()


def extract(name):
    match = re.search(r'^(?:static\s+)?void\s+(?:__MTLK_IFUNC\s+)?' + name +
                      r'\s*\([^;]*?\)\s*\{', source, re.M)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]


names = ('mtlk_df_user_quiesce_prop_dfs_wq', 'mtlk_df_user_uninit_prop_dfs_wq',
         'mtlk_df_user_add_propagate_event', 'mtlk_df_user_propagate_dfs_state',
         'mtlk_df_user_schedule_prop_dfs_wq')
functions = '\n\n'.join(extract(name) for name in names)
assert 'spin_lock_init(&df_user->prop_dfs_gate_lock)' in source
assert 'mtlk_df_user_quiesce_prop_dfs_wq(mtlk_df_get_user(wave_radio_df_get(radio)))' in radio
assert driver.index('wave_radio_scan_quiesce(radio_descr);') < driver.index('_mmb_drv_mac80211_deinit, (obj, radio_descr)')

harness = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define TRUE 1
#define FALSE 0
#define __MTLK_IFUNC
#define MTLK_MEM_TAG_PROP_DFS_STATE 1
#define NL80211_RADAR_DETECTED 1
#define ILOG2_V(...) ((void)0)
#define ILOG2_D(...) ((void)0)
#define ELOG_V(...) ((void)0)
#define MTLK_CONTAINER_OF(ptr,type,member) ((type*)((char*)(ptr)-offsetof(type,member)))
#define MTLK_LIST_GET_CONTAINING_RECORD(ptr,type,member) MTLK_CONTAINER_OF(ptr,type,member)
typedef int BOOL;
typedef unsigned char uint8;
typedef unsigned uint32;
typedef pthread_mutex_t spinlock_t;
typedef pthread_mutex_t mtlk_osal_mutex_t;
#define spin_lock_init(p) pthread_mutex_init((p),NULL)
#define spin_lock_irqsave(p,f) do {(f)=0;pthread_mutex_lock(p);}while(0)
#define spin_unlock_irqrestore(p,f) do {(void)(f);pthread_mutex_unlock(p);}while(0)
typedef struct entry { struct entry *prev,*next; } mtlk_dlist_entry_t;
typedef struct { mtlk_dlist_entry_t head; unsigned depth; } mtlk_dlist_t;
static void mtlk_dlist_init(mtlk_dlist_t *l){l->head.prev=l->head.next=&l->head;l->depth=0;}
static mtlk_dlist_entry_t *mtlk_dlist_head(mtlk_dlist_t *l){return &l->head;}
static mtlk_dlist_entry_t *mtlk_dlist_next(mtlk_dlist_entry_t *e){return e->next;}
#define mtlk_dlist_foreach(l,e,h) for((h)=mtlk_dlist_head(l),(e)=mtlk_dlist_next(h);(e)!=(h);(e)=mtlk_dlist_next(e))
#define mtlk_dlist_push_back_obj(l,obj,member) do {mtlk_dlist_entry_t *e=&(obj)->member; \
  e->prev=(l)->head.prev;e->next=&(l)->head;e->prev->next=e;(l)->head.prev=e;(l)->depth++;}while(0)
static mtlk_dlist_entry_t *mtlk_dlist_remove(mtlk_dlist_t *l,mtlk_dlist_entry_t *e){
  mtlk_dlist_entry_t *prev=e->prev;prev->next=e->next;e->next->prev=prev;l->depth--;return prev;}
struct cfg80211_chan_def {int center_freq1;};
enum nl80211_dfs_state { NL80211_DFS_AVAILABLE=0 };
enum nl80211_radar_event { NL80211_RADAR_CAC_FINISHED=0 };
typedef struct { mtlk_dlist_entry_t lentry;struct cfg80211_chan_def chandef;
  enum nl80211_dfs_state dfs_state;enum nl80211_radar_event event;uint8 rbm;BOOL cac_started;
} mtlk_dfs_state_cfg_t;
struct wireless_dev {int live;};
struct work_struct {void (*func)(struct work_struct*);};
struct workqueue_struct {pthread_mutex_t lock;pthread_cond_t cond;pthread_t thread;
  struct work_struct *work;int queued,running,stop;};
typedef struct mtlk_df_user mtlk_df_user_t;
typedef struct {mtlk_df_user_t *user;} mtlk_df_t;
struct mtlk_df_user {mtlk_df_t *df;struct wireless_dev wdev;
  struct work_struct propagate_dfs_state_work;struct workqueue_struct *propagate_dfs_state_wq;
  mtlk_dlist_t propagate_dfs_state_list;mtlk_osal_mutex_t prop_dfs_mutex;
  spinlock_t prop_dfs_gate_lock;BOOL prop_dfs_closing;};
static unsigned allocs,callbacks;
static int wiphy_live=1,block_callback,callback_entered,allow_callback,quiesce_done;
static pthread_mutex_t cb_lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cb_cond=PTHREAD_COND_INITIALIZER;
static void *mtlk_osal_mem_alloc(size_t n,int tag){(void)tag;void *p=calloc(1,n);assert(p);__sync_add_and_fetch(&allocs,1);return p;}
static void mtlk_osal_mem_free(void *p){assert(p);__sync_sub_and_fetch(&allocs,1);free(p);}
static void mtlk_osal_mutex_acquire(mtlk_osal_mutex_t *p){pthread_mutex_lock(p);}
static void mtlk_osal_mutex_release(mtlk_osal_mutex_t *p){pthread_mutex_unlock(p);}
static mtlk_df_t *mtlk_df_user_get_master_df(mtlk_df_user_t *u){return u->df;}
static mtlk_df_user_t *mtlk_df_get_user(mtlk_df_t *df){return df->user;}
static void *mtlk_df_get_vap_handle(mtlk_df_t *df){return df;}
static int mtlk_vap_is_master(void *vap){return vap!=NULL;}
static struct wireless_dev *mtlk_df_user_get_wdev(mtlk_df_user_t *u){return &u->wdev;}
static void rtnl_lock(void){pthread_mutex_lock(&cb_lock);}
static void rtnl_unlock(void){pthread_mutex_unlock(&cb_lock);}
static void wv_cfg80211_regulatory_propagate_dfs_state(struct wireless_dev *w,
  struct cfg80211_chan_def *c,enum nl80211_dfs_state s,enum nl80211_radar_event e,uint8 rbm){
  (void)c;(void)s;(void)e;(void)rbm;assert(w->live && __atomic_load_n(&wiphy_live,__ATOMIC_ACQUIRE));
  __sync_add_and_fetch(&callbacks,1);
  if(block_callback){callback_entered=1;pthread_cond_broadcast(&cb_cond);
    while(!allow_callback)pthread_cond_wait(&cb_cond,&cb_lock);}
}
static void wv_cfg80211_radar_event(struct wireless_dev *w,struct cfg80211_chan_def *c,BOOL started,uint8 rbm){
  (void)w;(void)c;(void)started;(void)rbm;abort();}
static void *worker(void *ptr){struct workqueue_struct *q=ptr;pthread_mutex_lock(&q->lock);
  while(1){while(!q->queued&&!q->stop)pthread_cond_wait(&q->cond,&q->lock);
    if(q->stop&&!q->queued)break;q->queued=0;q->running=1;struct work_struct *w=q->work;
    pthread_mutex_unlock(&q->lock);w->func(w);pthread_mutex_lock(&q->lock);
    q->running=0;pthread_cond_broadcast(&q->cond);}
  pthread_mutex_unlock(&q->lock);return NULL;}
static struct workqueue_struct *make_wq(struct work_struct *w){struct workqueue_struct *q=calloc(1,sizeof(*q));assert(q);
  pthread_mutex_init(&q->lock,NULL);pthread_cond_init(&q->cond,NULL);q->work=w;
  assert(!pthread_create(&q->thread,NULL,worker,q));return q;}
static int queue_work(struct workqueue_struct *q,struct work_struct *w){assert(q&&q->work==w);
  pthread_mutex_lock(&q->lock);int queued=!q->queued;if(queued){q->queued=1;pthread_cond_broadcast(&q->cond);}
  pthread_mutex_unlock(&q->lock);return queued;}
static void flush_workqueue(struct workqueue_struct *q){pthread_mutex_lock(&q->lock);
  while(q->queued||q->running)pthread_cond_wait(&q->cond,&q->lock);pthread_mutex_unlock(&q->lock);}
static void destroy_workqueue(struct workqueue_struct *q){flush_workqueue(q);pthread_mutex_lock(&q->lock);
  q->stop=1;pthread_cond_broadcast(&q->cond);pthread_mutex_unlock(&q->lock);pthread_join(q->thread,NULL);
  pthread_mutex_destroy(&q->lock);pthread_cond_destroy(&q->cond);free(q);}
FUNCTIONS
static mtlk_df_user_t user;static mtlk_df_t df;
static void setup(void){memset(&user,0,sizeof(user));df.user=&user;user.df=&df;user.wdev.live=1;
  spin_lock_init(&user.prop_dfs_gate_lock);pthread_mutex_init(&user.prop_dfs_mutex,NULL);
  mtlk_dlist_init(&user.propagate_dfs_state_list);
  user.propagate_dfs_state_work.func=mtlk_df_user_propagate_dfs_state;
  user.propagate_dfs_state_wq=make_wq(&user.propagate_dfs_state_work);
  allocs=callbacks=0;wiphy_live=1;block_callback=callback_entered=allow_callback=quiesce_done=0;}
static void add(int n){struct cfg80211_chan_def c={.center_freq1=n};
  mtlk_df_user_add_propagate_event(&user,&c,NL80211_DFS_AVAILABLE,NL80211_RADAR_CAC_FINISHED,0,0);}
static void close_user(void){mtlk_df_user_uninit_prop_dfs_wq(&user);
  assert(!allocs&&!user.propagate_dfs_state_list.depth);pthread_mutex_destroy(&user.prop_dfs_mutex);
  pthread_mutex_destroy(&user.prop_dfs_gate_lock);}
static void *quiesce_thread(void *p){(void)p;mtlk_df_user_quiesce_prop_dfs_wq(&user);
  __atomic_store_n(&quiesce_done,1,__ATOMIC_RELEASE);return NULL;}
static void *producer_thread(void *p){(void)p;for(int i=0;i<1000;i++){
  add(i);mtlk_df_user_schedule_prop_dfs_wq(&user);if(!(i%7))sched_yield();}return NULL;}
int main(void){
  setup();add(1);mtlk_df_user_schedule_prop_dfs_wq(&user);flush_workqueue(user.propagate_dfs_state_wq);
  assert(callbacks==1&&!allocs);add(2);assert(allocs==1);
  mtlk_df_user_quiesce_prop_dfs_wq(&user);assert(callbacks==1&&!allocs);
  for(int i=0;i<10;i++){add(i);mtlk_df_user_schedule_prop_dfs_wq(&user);}assert(callbacks==1&&!allocs);
  user.wdev.live=0;wiphy_live=0;close_user();puts("PASS: normal delivery, unscheduled purge and post-close rejection");

  setup();block_callback=1;add(1);mtlk_df_user_schedule_prop_dfs_wq(&user);
  pthread_mutex_lock(&cb_lock);while(!callback_entered)pthread_cond_wait(&cb_cond,&cb_lock);pthread_mutex_unlock(&cb_lock);
  pthread_t closer;assert(!pthread_create(&closer,NULL,quiesce_thread,NULL));usleep(20000);
  assert(!__atomic_load_n(&quiesce_done,__ATOMIC_ACQUIRE));
  pthread_mutex_lock(&cb_lock);allow_callback=1;pthread_cond_broadcast(&cb_cond);pthread_mutex_unlock(&cb_lock);
  pthread_join(closer,NULL);assert(callbacks==1&&!allocs);
  user.wdev.live=0;wiphy_live=0;add(2);mtlk_df_user_schedule_prop_dfs_wq(&user);close_user();
  puts("PASS: quiesce waits for an in-flight cfg80211 callback");

  setup();pthread_t producer;assert(!pthread_create(&producer,NULL,producer_thread,NULL));
  usleep(1000);mtlk_df_user_quiesce_prop_dfs_wq(&user);user.wdev.live=0;wiphy_live=0;
  pthread_join(producer,NULL);assert(!allocs&&!user.propagate_dfs_state_list.depth);
  close_user();puts("PASS: 1000 producer attempts race with closure without late callbacks");
  return 0;
}
'''
harness = harness.replace('\nFUNCTIONS\n', '\n' + functions + '\n')


def run(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / 'probe.c').write_text(harness)
    flags = ['-static'] if args.qemu else ['-fsanitize=address,undefined', '-fno-pie', '-no-pie']
    subprocess.run([args.cc, '-std=gnu11', '-O1', '-g', '-pthread', *flags,
                    str(path / 'probe.c'), '-o', str(path / 'probe')], check=True)
    command = [str(path / 'probe')]
    if args.qemu:
        command.insert(0, str(args.qemu.resolve()))
    subprocess.run(command, check=True, cwd=path)


if args.output:
    run(args.output.resolve())
else:
    with tempfile.TemporaryDirectory(prefix='wave-dfs-quiesce-') as tmp:
        run(Path(tmp))
