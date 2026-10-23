// SPDX-License-Identifier: GPL-2.0-only
/* Read-only guard before attaching an existing AX3000 factory UBI container. */
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <mtd/mtd-user.h>

#define PEB_SIZE 131072U
#define PART_SIZE 0x7c00000U
#define VTBL_RECORD_SIZE 172U
#define VTBL_RECORDS 128U
#define LAYOUT_VOLUME_ID 0x7fffefffU

static uint32_t be32(const unsigned char *p)
{
	return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 |
	       (uint32_t)p[2] << 8 | p[3];
}

static uint32_t crc32_ubi(const unsigned char *p, size_t n)
{
	uint32_t crc = UINT32_MAX;
	unsigned int i;

	while (n--) {
		crc ^= *p++;
		for (i = 0; i < 8; i++)
			crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320U : 0);
	}
	return crc;
}

static int read_at(int fd, void *buf, size_t n, off_t offset)
{
	ssize_t ret;
	do { ret = pread(fd, buf, n, offset); } while (ret < 0 && errno == EINTR);
	return ret == (ssize_t)n ? 0 : -1;
}

static int valid_table(const unsigned char *table)
{
	unsigned int i, len;
	int data = 0, kernel = 0, rootfs = 0;

	for (i = 0; i < VTBL_RECORDS; i++) {
		const unsigned char *r = table + i * VTBL_RECORD_SIZE;
		if (crc32_ubi(r, 168) != be32(r + 168))
			return 0;
		if (!be32(r))
			continue;
		len = (unsigned int)r[14] << 8 | r[15];
		if (len > 127 || !len || r[16 + len] || r[13])
			return 0;
		if (len == 4 && !memcmp(r + 16, "data", 4) && r[12] == 1 &&
		    be32(r + 4) == 1 && be32(r + 8) == 0)
			data++;
		if (len == 7 && (!memcmp(r + 16, "kernelA", 7) ||
				 !memcmp(r + 16, "kernelB", 7)))
			kernel++;
		if (len == 7 && (!memcmp(r + 16, "rootfsA", 7) ||
				 !memcmp(r + 16, "rootfsB", 7)))
			rootfs++;
	}
	return data == 1 && kernel > 0 && rootfs > 0;
}

static int check_container(int fd, uint32_t size, int raw_mtd)
{
	unsigned char ec[64], vid[64], table[VTBL_RECORDS * VTBL_RECORD_SIZE];
	uint32_t offset;

	for (offset = 0; offset < size; offset += PEB_SIZE) {
		if (raw_mtd) {
			int64_t block = offset;
			int bad = ioctl(fd, MEMGETBADBLOCK, &block);
			if (bad < 0)
				return 0;
			if (bad)
				continue;
		}
		if (read_at(fd, ec, sizeof(ec), offset) ||
		    be32(ec) != 0x55424923 || ec[4] != 1 ||
		    crc32_ubi(ec, 60) != be32(ec + 60) ||
		    be32(ec + 16) != 2048 || be32(ec + 20) != 4096)
			continue;
		if (read_at(fd, vid, sizeof(vid), offset + 2048) ||
		    be32(vid) != 0x55424921 || vid[4] != 1 || vid[5] != 1 ||
		    vid[7] != 5 || be32(vid + 8) != LAYOUT_VOLUME_ID ||
		    be32(vid + 12) > 1 || be32(vid + 28) != 0 ||
		    crc32_ubi(vid, 60) != be32(vid + 60))
			continue;
		if (!read_at(fd, table, sizeof(table), offset + 4096) && valid_table(table))
			return 1;
	}
	return 0;
}

int main(int argc, char **argv)
{
	struct mtd_info_user info;
	int fd, ok;

	if (argc != 2) {
		fprintf(stderr, "Usage: %s /dev/mtdN\n", argv[0]);
		return 2;
	}
	fd = open(argv[1], O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (fd < 0)
		return 1;
#ifdef GRX500_UBI_FIXTURE_TEST
	/* Host fixture tests only; never enabled in the installed utility. */
	info.size = (uint32_t)lseek(fd, 0, SEEK_END);
	ok = info.size && !(info.size % PEB_SIZE) && check_container(fd, info.size, 0);
#else
	ok = !ioctl(fd, MEMGETINFO, &info) && info.type == MTD_NANDFLASH &&
	     info.size == PART_SIZE && info.erasesize == PEB_SIZE &&
	     info.writesize == 2048 && check_container(fd, info.size, 1);
#endif
	close(fd);
	if (!ok)
		fprintf(stderr, "No validated existing AX3000 UBI volume table; refusing attach\n");
	return ok ? 0 : 1;
}
