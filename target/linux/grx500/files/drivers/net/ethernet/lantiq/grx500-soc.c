// SPDX-License-Identifier: GPL-2.0-only
/* GRX500 chip ID layout from Intel's drivers/arch support (2014-2018). */
#include <linux/export.h>
#include <linux/init.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <lantiq.h>

#define GRX500_CHIP_ID 0x1f107344
static unsigned int grx500_revision;

unsigned int ltq_get_soc_rev(void)
{
	return grx500_revision;
}
EXPORT_SYMBOL_GPL(ltq_get_soc_rev);

static int __init grx500_read_revision(void)
{
	void __iomem *base;
	u32 id;

	base = ioremap(GRX500_CHIP_ID, sizeof(id));
	if (!base)
		panic("GRX500: cannot map chip ID register");
	id = __raw_readl(base);
	iounmap(base);
	grx500_revision = (id >> 28) & 7;
	pr_info("GRX500: chip ID %#08x, revision %u\n", id, grx500_revision);
	return 0;
}
core_initcall(grx500_read_revision);
