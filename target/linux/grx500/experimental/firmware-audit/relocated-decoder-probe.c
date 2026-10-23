/* SPDX-License-Identifier: GPL-2.0-only
 * Static MIPS userspace test of the actual second-stage decoder C function.
 * Does not execute startup.S or enter a kernel.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

int grx500_decode(const unsigned char *, size_t, unsigned char *, size_t);

int main(int argc, char **argv)
{
	FILE *file;
	long length;
	unsigned char *input, *output;
	size_t expanded;
	int result;
	if (argc != 3)
		return 90;
	file = fopen(argv[1], "rb");
	if (!file)
		return 91;
	fseek(file, 0, SEEK_END); length = ftell(file); rewind(file);
	if (length < 13 || length > 32 * 1024 * 1024)
		return 92;
	input = malloc(length);
	output = malloc(48 * 1024 * 1024);
	if (!input || !output || fread(input, 1, length, file) != (size_t)length)
		return 93;
	fclose(file);
	result = grx500_decode(input, length, output, 48 * 1024 * 1024);
	if (result)
		return result;
	expanded = (uint32_t)input[5] | ((uint32_t)input[6] << 8) |
		   ((uint32_t)input[7] << 16) | ((uint32_t)input[8] << 24);
	file = fopen(argv[2], "wb");
	if (!file || fwrite(output, 1, expanded, file) != expanded || fclose(file))
		return 94;
	free(input); free(output);
	return 0;
}
