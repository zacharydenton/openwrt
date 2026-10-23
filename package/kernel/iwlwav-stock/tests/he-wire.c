/* Host test for the firmware byte serializer used by both AP and STA. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "wave_he_compat.h"

int main(void)
{
  unsigned char in[64] = {0}, cap[18], mcs[8], ppe[13];
  unsigned int i;
  in[0] = 1;
  for (i = 17; i < 29; i++) in[i] = i;
  assert(wave_he_pack(cap, mcs, ppe, in, 20) < 0);
  assert(wave_he_pack(cap, mcs, ppe, in, 21) == 0);
  assert(cap[0] == 35 && cap[1] == 1 && cap[17] == 0);
  assert(!memcmp(mcs, in + 17, 4));
  for (i = 4; i < 8; i++) assert(mcs[i] == 255);
  for (i = 0; i < 13; i++) assert(ppe[i] == 0);

  in[6] = 8; /* contiguous 160 MHz */
  assert(wave_he_pack(cap, mcs, ppe, in, 24) < 0);
  assert(wave_he_pack(cap, mcs, ppe, in, 25) == 0);
  assert(!memcmp(mcs, in + 17, 8) && cap[7] == 8);

  in[6] = 24; /* peer also supports 80+80: skip that map before PPE */
  in[12] = 128;
  in[29] = 0x79; /* two NSS, all four RU sizes: 55 bits, seven bytes */
  for (i = 30; i < 36; i++) in[i] = 0xff;
  for (i = 0; i < 36; i++)
    assert(wave_he_pack(cap, mcs, ppe, in, i) < 0);
  assert(wave_he_pack(cap, mcs, ppe, in, 36) == 0);
  assert(cap[7] == 8 && !memcmp(mcs, in + 17, 8));
  assert(ppe[0] == 0x79 && ppe[6] == 0x7f && ppe[7] == 0);

  in[29] = 0x7f; /* eight NSS incoming; firmware consumes first four */
  memset(in + 30, 0xff, 24);
  assert(wave_he_pack(cap, mcs, ppe, in, 53) < 0);
  assert(wave_he_pack(cap, mcs, ppe, in, 54) == 0);
  assert(ppe[0] == 0x7b && ppe[12] == 0x7f);

  in[6] = 16; /* 80+80 without contiguous160: do not misassign second map */
  in[12] = 0;
  assert(wave_he_pack(cap, mcs, ppe, in, 25) == 0);
  assert(cap[7] == 0 && mcs[4] == 255 && mcs[7] == 255);
  in[12] = 128; in[25] = 0; /* malformed PPE: no RU represented */
  assert(wave_he_pack(cap, mcs, ppe, in, 26) < 0);
  puts("HE firmware packing: 80/160/80+80, NSS, PPE bounds passed");
  return 0;
}
