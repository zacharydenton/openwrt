/* SPDX-License-Identifier: GPL-2.0-only
 * Host-native, static /bin/sh replacement for the isolated nvrammanager test.
 * It NEVER interprets commands or calls vol_mgmt. It only captures stdin.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
	char type[24], name[128], path[128], buf[8192];
	unsigned size;
	size_t n, total = 0;
	FILE *out, *log;
	if (argc != 3 || strcmp(argv[1], "-c") ||
	    sscanf(argv[2], "/usr/sbin/vol_mgmt upgrade_dualvol_stdin %23s %u %127[^\n]",
	           type, &size, name) != 3)
		return 90;
	if (strcmp(type, "kernel") && strcmp(type, "rootfs") &&
	    strcmp(type, "bootcore") && strcmp(type, "firmware") && strcmp(type, "uboot"))
		return 91;
	if (size > 33554432)
		return 92;
	snprintf(path, sizeof(path), "/work/capture.%s", type);
	out = fopen(path, "wx");
	if (!out)
		return 93;
	while ((n = fread(buf, 1, sizeof(buf), stdin))) {
		if (total + n > size || fwrite(buf, 1, n, out) != n)
			return 94;
		total += n;
	}
	if (ferror(stdin) || fclose(out) || total != size)
		return 95;
	log = fopen("/work/calls.txt", "a");
	if (!log)
		return 96;
	fprintf(log, "%s\t%u\t%s\n", type, size, name);
	return fclose(log) ? 97 : 0;
}
