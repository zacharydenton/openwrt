#!/usr/bin/env python3
"""Run the actual BIP frame builder with a host OpenSSL shash adapter.

This tests serialization, MIC coverage, key selection and IPN limits. It is not
an emulation of the wireless hardware or the Linux DMA/locking environment.
"""
from pathlib import Path
import subprocess
import tempfile
import sys
from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if len(sys.argv) != 2:
    raise SystemExit('usage: pmf-frame-test.py PREPARED_DRIVER_SOURCE')
source = (Path(sys.argv[1]) / 'wireless/driver/linux/core.c').read_text()
start = source.index('static int wave_pmf_protect(')
end = source.index('\nstatic int\nreset_security_stuff', start)
function = source[start:end]
shim = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <openssl/cmac.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint64_t u64;
struct ieee80211_hdr { u16 frame_control, duration; u8 addr1[6],addr2[6],addr3[6]; u16 seq; } __attribute__((packed));
struct crypto_shash { const u8 *key; unsigned key_len; };
struct crypto_aead { const u8 *key; unsigned key_len; };
struct shash_desc { struct crypto_shash *tfm; CMAC_CTX *ctx; };
#define SHASH_DESC_ON_STACK(n,x) struct shash_desc storage = {0}, *n = &storage
#define MTLK_ERR_OK 0
#define MTLK_ERR_NO_MEM 1
#define MTLK_ERR_NOT_READY 2
#define MTLK_ERR_PKT_DROPPED 3
#define GFP_ATOMIC 0
#define WLAN_EID_MMIE 76
#define WLAN_CIPHER_SUITE_AES_CMAC 6
#define IEEE80211_FCTL_RETRY 0x0800
#define IEEE80211_FCTL_PM 0x1000
#define IEEE80211_FCTL_MOREDATA 0x2000
struct slow { unsigned default_mgmt_key; bool igtk_configured; struct crypto_shash *igtk_tfm[2]; struct crypto_aead *igtk_gmac[2]; u64 igtk_ipn[2]; unsigned igtk_cipher_suite[2]; };
typedef struct { int net_state_lock; struct slow *slow_ctx; } mtlk_core_t;
#define mtlk_osal_lock_acquire(x) ((void)0)
#define mtlk_osal_lock_release(x) ((void)0)
#define kmalloc(n,f) malloc(n)
#define kfree(p) free(p)
#define le16_to_cpu(x) (x)
static bool is_multicast_ether_addr(const u8 *p) { return p[0]&1; }
static bool _ieee80211_is_robust_mgmt_frame(struct ieee80211_hdr *h) {
 unsigned st = h->frame_control & 0xfc; return st == 0xc0 || st == 0xa0;
}
static void put_unaligned_le16(u16 n, void *v) { u8 *p=v; p[0]=n; p[1]=n>>8; }
static int crypto_shash_init(struct shash_desc *d) {
 d->ctx=CMAC_CTX_new();
 return !CMAC_Init(d->ctx,d->tfm->key,d->tfm->key_len,d->tfm->key_len==16?EVP_aes_128_cbc():EVP_aes_256_cbc(),NULL);
}
static int crypto_shash_update(struct shash_desc *d,const u8 *p,size_t n) { return !CMAC_Update(d->ctx,p,n); }
static int crypto_shash_finup(struct shash_desc *d,const u8 *p,size_t n,u8 *out) {
 size_t sz=16; return !(CMAC_Update(d->ctx,p,n) && CMAC_Final(d->ctx,out,&sz));
}
static void shash_desc_zero(struct shash_desc *d) { CMAC_CTX_free(d->ctx); }
static int wave_pmf_gmac(struct crypto_aead *tfm,const u8 *aad,const u8 *body,size_t n,const u8 *sa,u64 ipn,u8 *mic) {
 EVP_CIPHER_CTX *ctx=EVP_CIPHER_CTX_new(); u8 nonce[12], discard[16]; int len,ok; unsigned i;
 memcpy(nonce,sa,6); for(i=0;i<6;i++) nonce[6+i]=ipn>>(8*(5-i));
 ok=EVP_EncryptInit_ex(ctx,tfm->key_len==16?EVP_aes_128_gcm():EVP_aes_256_gcm(),NULL,tfm->key,nonce)
 && EVP_EncryptUpdate(ctx,NULL,&len,aad,20) && EVP_EncryptUpdate(ctx,NULL,&len,body,n)
 && EVP_EncryptFinal_ex(ctx,discard,&len) && EVP_CIPHER_CTX_ctrl(ctx,EVP_CTRL_GCM_GET_TAG,16,mic);
 EVP_CIPHER_CTX_free(ctx); return !ok;
}

'''
main = r'''
int main(void) {
 u8 key[32], frame[26] = {0xc0,0x38,0,0, 0xff,0xff,0xff,0xff,0xff,0xff,
  2,1,2,3,4,5, 2,1,2,3,4,5, 0x30,0x12, 3,0};
 struct crypto_shash tfm={key,16}; struct crypto_aead gmac={key,16}; struct slow slow={.default_mgmt_key=4,.igtk_configured=true};
 mtlk_core_t core={.slow_ctx=&slow}; unsigned i,j; u8 *out; size_t n; int res;
 for(i=0;i<32;i++) key[i]=i;
 slow.igtk_tfm[0]=&tfm;
 for(j=0;j<4;j++) {
  tfm.key_len=(j&1)?32:16; gmac.key_len=tfm.key_len;
  slow.igtk_tfm[0]=j<2?&tfm:NULL; slow.igtk_gmac[0]=j>=2?&gmac:NULL;
  slow.igtk_cipher_suite[0]=j?13:6; slow.igtk_ipn[0]=0x010203040505ULL;
  res=wave_pmf_protect(&core,frame,sizeof(frame),&out,&n);
  if(res || !out) return 1;
  for(i=0;i<n;i++) { printf("%02x",out[i]); }
  puts(""); free(out);
 }
 slow.igtk_ipn[0]=0xffffffffffffULL;
 if(wave_pmf_protect(&core,frame,sizeof(frame),&out,&n)!=MTLK_ERR_PKT_DROPPED || out) return 2;
 slow.igtk_tfm[0]=NULL; slow.igtk_gmac[0]=NULL;
 if(wave_pmf_protect(&core,frame,sizeof(frame),&out,&n)!=MTLK_ERR_NOT_READY || out) return 3;
 slow.igtk_configured=false;
 if(wave_pmf_protect(&core,frame,sizeof(frame),&out,&n) || out || n!=sizeof(frame)) return 4;
 frame[4]=2;
 slow.igtk_configured=true;
 if(wave_pmf_protect(&core,frame,sizeof(frame),&out,&n) || out) return 5;
 return 0;
}
'''
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp) / 'pmf.c'
    exe = Path(tmp) / 'pmf'
    src.write_text(shim + function + main)
    subprocess.run(['cc', '-Wno-deprecated-declarations', '-Wall', '-Wextra', '-o', str(exe), str(src), '-lcrypto'], check=True)
    output = subprocess.check_output([str(exe)], text=True).splitlines()
frame = bytes.fromhex('c0380000ffffffffffff02010203040502010203040530120300')
for i, (keylen, miclen, result) in enumerate(zip((16,32,16,32), (8,16,16,16), output)):
    mmie = bytes([76, 8+miclen, 4, 0]) + bytes.fromhex('060504030201') + bytes(miclen)
    aad = bytes.fromhex('c000') + frame[4:22]
    if i < 2:
        cmac = CMAC(algorithms.AES(bytes(range(keylen))))
        cmac.update(aad + frame[24:] + mmie)
        mic = cmac.finalize()[:miclen]
    else:
        nonce = frame[10:16] + bytes.fromhex('010203040506')
        mic = AESGCM(bytes(range(keylen))).encrypt(nonce, b'', aad + frame[24:] + mmie)
    expected = frame + mmie[:-miclen] + mic
    assert bytes.fromhex(result) == expected, (keylen, result, expected.hex())
print('PASS: actual BIP builder CMAC128/256 and GMAC128/256, masked AAD, little-endian IPN, exhaustion, absent-key fail-closed and unicast bypass')
