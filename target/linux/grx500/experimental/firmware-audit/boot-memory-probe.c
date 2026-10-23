/* SPDX-License-Identifier: GPL-2.0-only
 * Host memory model using the vendor archive's U-Boot LZMA decoder.
 * Offsets represent the physical RAM aliasing of cached/uncached windows.
 */
#include <stdio.h>
#include <stdlib.h>
#include "LzmaTools.h"

int main(int argc, char **argv)
{
	FILE *file;
	unsigned char *ram;
	unsigned long source, destination;
	long length;
	SizeT expanded = 64 * 1024 * 1024;
	int result;
	if (argc != 5)
		return 90;
	file = fopen(argv[1], "rb");
	if (!file)
		return 91;
	fseek(file, 0, SEEK_END); length = ftell(file); rewind(file);
	source = strtoul(argv[2], 0, 0);
	destination = strtoul(argv[3], 0, 0);
	if (length < 77 || length > 32 * 1024 * 1024 ||
	    source > 64 * 1024 * 1024 || destination > 64 * 1024 * 1024)
		return 92;
	ram = calloc(1, 128 * 1024 * 1024);
	if (!ram || fread(ram + source, 1, length, file) != (size_t)length)
		return 93;
	fclose(file);
	result = lzmaBuffToBuffDecompress(ram + destination, &expanded,
					ram + source + 64, length - 64);
	fprintf(stderr, "status=%d expanded=%lu\n", result, (unsigned long)expanded);
	if (expanded > 64 * 1024 * 1024)
		return 94;
	file = fopen(argv[4], "wb");
	if (!file)
		return 95;
	if (fwrite(ram + destination, 1, expanded, file) != expanded || fclose(file))
		return 96;
	free(ram);
	return result;
}
