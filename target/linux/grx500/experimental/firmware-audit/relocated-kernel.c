/* SPDX-License-Identifier: GPL-2.0-only
 * Experimental AX3000 second-stage decoder. Stock U-Boot expands this stage
 * at uncached 0xa4000000; the Linux image is decoded at 0xa0020000. Both
 * addresses use the SAME uncached window as the vendor kernel entry.
 * No NAND, environment, MMIO, segment or cache configuration is changed.
 */
#include <stddef.h>
#include "LzmaDecode.h"

#define OUTPUT_LIMIT (0x03000000U - 0x00020000U)
#define PROB_COUNT (LZMA_BASE_SIZE + (LZMA_LIT_SIZE << 4))
static CProb probabilities[PROB_COUNT];

int grx500_decode(const unsigned char *input, size_t length,
		 unsigned char *output, size_t capacity)
{
	CLzmaDecoderState state;
	SizeT consumed = 0, produced = 0;
	unsigned int size;
	int result;
	if (length < 18)
		return 1;
	if (input[9] || input[10] || input[11] || input[12])
		return 2; /* Requires a known size below 4 GiB. */
	size = (unsigned int)input[5] | ((unsigned int)input[6] << 8) |
	       ((unsigned int)input[7] << 16) | ((unsigned int)input[8] << 24);
	if (!size || size > OUTPUT_LIMIT || size > capacity)
		return 3;
	if (LzmaDecodeProperties(&state.Properties, input, 5) != LZMA_RESULT_OK)
		return 4;
	if (state.Properties.lc + state.Properties.lp > 4)
		return 5;
	state.Probs = probabilities;
	result = LzmaDecode(&state, input + 13, length - 13, &consumed,
			    output, size, &produced);
	return result == LZMA_RESULT_OK && produced == size ? 0 : 6;
}

#ifndef GRX500_DECODER_TEST
extern const unsigned char payload_start[], payload_end[];

int loader_main(unsigned long arg0, unsigned long arg1,
		unsigned long arg2, unsigned long arg3)
{
	int result = grx500_decode(payload_start, payload_end - payload_start,
				  (unsigned char *)0xa0020000, OUTPUT_LIMIT);
	if (result)
		return result;
	/* The bootloader and this stage both write through the uncached alias,
	 * and Linux starts through that same alias, as in the stock boot flow.
	 */
	__asm__ __volatile__("sync" ::: "memory");
	((void (*)(unsigned long, unsigned long, unsigned long, unsigned long))
	 0xa0020000)(arg0, arg1, arg2, arg3);
	return 7;
}
#endif
