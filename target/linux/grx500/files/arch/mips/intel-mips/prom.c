// SPDX-License-Identifier: GPL-2.0
/*
 * Copyright (C) 2014 Lei Chuanhua
 * Copyright (C) 2016 Intel Corporation.
 * Adapted from Intel's 2018 GRX500 submission for AX3000 device support.
 */
#include <linux/init.h>
#include <linux/io.h>
#include <linux/of_fdt.h>
#include <linux/of_platform.h>
#include <linux/string.h>
#include <linux/sizes.h>

#include <asm/bootinfo.h>
#include <asm/mips-cps.h>
#include <asm/prom.h>
#include <asm/smp-ops.h>

const char *get_system_type(void)
{
	return "Intel GRX350/GRX500";
}

/* Only accept the bank selector from vendor arguments. Its RAM sizes and
 * reference-board partition strings must not override this board's DT.
 */
static char grx500_rootfs_bank;

/* '?' is a sticky error across the complete U-Boot argument vector. */
static char __init grx500_parse_bank(const char *arg, char selected)
{
	const char *word = arg, *end;
	size_t len = strnlen(arg, COMMAND_LINE_SIZE);

	if (selected == '?' || len == COMMAND_LINE_SIZE)
		return '?';
	while (*word) {
		if (*word == ' ') {
			word++;
			continue;
		}
		end = strchr(word, ' ');
		if (!end)
			end = arg + len;
		if (end - word >= 11 && !memcmp(word, "rootfsname=", 11)) {
			if (selected || end - word != 18 ||
			    memcmp(word, "rootfsname=rootfs", 17) ||
			    (word[17] != 'A' && word[17] != 'B'))
				return '?';
			selected = word[17];
		}
		word = end;
	}
	return selected;
}

void __init prom_init(void)
{
	unsigned long argc = fw_arg0;
	u32 *argv;
	unsigned int i;
	char bank = 0;

	if (IS_ENABLED(CONFIG_MIPS_MT_SMP) && register_vsmp_smp_ops())
		panic("GRX500: MIPS MT SMP registration failed");

	if (!argc || argc > 64 || fw_arg1 < 0x80000000UL ||
	    fw_arg1 >= 0xc0000000UL || CPHYSADDR(fw_arg1) > SZ_256M - 256)
		return;
	argv = (u32 *)KSEG1ADDR(fw_arg1);
	for (i = 0; i < argc; i++) {
		const char *arg;
		if (argv[i] < 0x80000000U || argv[i] >= 0xc0000000U ||
		    CPHYSADDR(argv[i]) > SZ_256M - COMMAND_LINE_SIZE)
			return;
		arg = (const char *)KSEG1ADDR(argv[i]);
		bank = grx500_parse_bank(arg, bank);
		if (bank == '?')
			return;
	}
	grx500_rootfs_bank = bank;
}

void __init prom_free_prom_memory(void)
{
}

static void grx500_free_init_pages(void *begin, void *end)
{
	free_init_pages("unused kernel", __pa_symbol(begin), __pa_symbol(end));
}

void __init plat_mem_setup(void)
{
	void *dtb = get_fdt();

	if (!dtb)
		panic("GRX500: missing appended device tree");

	set_io_port_base(KSEG1);
	__dt_setup_arch(dtb);
	if (grx500_rootfs_bank)
		snprintf(arcs_cmdline, COMMAND_LINE_SIZE, "rootfsname=rootfs%c",
			 grx500_rootfs_bank);
	/* RAM kernels do not attach UBI here. Userspace first verifies an
	 * existing stock volume table before attaching it for factory MACs.
	 */
	if (sizeof(CONFIG_INITRAMFS_SOURCE) == 1) {
		if (!grx500_rootfs_bank)
			panic("GRX500: stock U-Boot rootfsname bank selector missing");
		strlcat(arcs_cmdline, " ubi.mtd=system_sw rootfstype=squashfs ro",
			COMMAND_LINE_SIZE);
	}
	if (mips_cps_numiocu(0) >= 2) {
		/* The GRX500 top peripheral window is behind the second IOCU. */
		write_gcr_reg0_base(0xa0000000);
		write_gcr_reg0_mask(0xf8000000 | CM_GCR_REGn_MASK_CMTGT_IOCU1);
	}
	free_init_pages_eva = grx500_free_init_pages;
}

void __init device_tree_init(void)
{
	unflatten_and_copy_device_tree();
}

static int __init grx500_publish_devices(void)
{
	return of_platform_default_populate(NULL, NULL, NULL);
}
arch_initcall(grx500_publish_devices);
