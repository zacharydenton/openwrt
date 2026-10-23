// SPDX-License-Identifier: GPL-2.0-only
/*
 * GRX500 NAND controller with stock BCH4 layout and protected factory data.
 * EBU operations derived from xway_nand.c:
 * Copyright (C) 2012 John Crispin, 2016 Hauke Mehrtens.
 * GRX500 mapping and BCH settings follow TP-Link AX3000 V1 GPL sources.
 */
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/iopoll.h>
#include <linux/mtd/partitions.h>
#include <linux/mtd/rawnand.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/sizes.h>

#define EBU_ADDSEL1 0x24
#define EBU_BUSCON1 0x64
#define EBU_NAND_CON 0xb0
#define EBU_NAND_WAIT 0xb4
#define NAND_READY BIT(0)
#define NAND_TRANSFER_COMPLETE BIT(3)
#define NAND_ENABLE BIT(0)
#define NAND_CE BIT(20)
#define NAND_IO_DATA BIT(4)
#define NAND_IO_CMD (BIT(4) | BIT(3))
#define NAND_IO_ADDR (BIT(4) | BIT(2))

struct grx500_nand {
	struct nand_controller controller;
	struct nand_chip chip;
	void __iomem *ebu;
	void __iomem *data;
	struct clk *clk;
};

static int grx500_nand_wait(struct grx500_nand *nand, u32 mask,
			   unsigned int timeout_us)
{
	u32 status;

	return read_poll_timeout_atomic(__raw_readl, status, status & mask,
					0, timeout_us, false, nand->ebu + EBU_NAND_WAIT);
}

static bool grx500_nand_command(u8 command)
{
	switch (command) {
	case NAND_CMD_READ0:
	case NAND_CMD_READ1:
	case NAND_CMD_READOOB:
	case NAND_CMD_READSTART:
	case NAND_CMD_RNDOUT:
	case NAND_CMD_RNDOUTSTART:
	case NAND_CMD_READID:
	case NAND_CMD_PARAM:
	case NAND_CMD_STATUS:
	case NAND_CMD_RESET:
	case NAND_CMD_GET_FEATURES:
	case NAND_CMD_SET_FEATURES:
	case NAND_CMD_SEQIN:
	case NAND_CMD_PAGEPROG:
	case NAND_CMD_RNDIN:
	case NAND_CMD_ERASE1:
	case NAND_CMD_ERASE2:
		return true;
	default:
		/* Unsupported vendor commands never reach the chip. */
		return false;
	}
}

static int grx500_nand_exec_op(struct nand_chip *chip,
			      const struct nand_operation *op, bool check_only)
{
	struct grx500_nand *nand = nand_get_controller_data(chip);
	const struct nand_op_instr *instr;
	unsigned int i, j;
	u32 value;
	int ret = 0;

	if (op->cs)
		return -EINVAL;
	/* Validate the complete operation before any write to controller or chip. */
	for (i = 0; i < op->ninstrs; i++) {
		instr = &op->instrs[i];
		switch (instr->type) {
		case NAND_OP_CMD_INSTR:
			if (!grx500_nand_command(instr->ctx.cmd.opcode))
				return -EOPNOTSUPP;
			break;
		case NAND_OP_ADDR_INSTR:
		case NAND_OP_DATA_IN_INSTR:
		case NAND_OP_DATA_OUT_INSTR:
		case NAND_OP_WAITRDY_INSTR:
			break;
		default:
			return -EOPNOTSUPP;
		}
	}
	if (check_only)
		return 0;
	value = __raw_readl(nand->ebu + EBU_NAND_CON);
	__raw_writel(value | NAND_ENABLE | NAND_CE, nand->ebu + EBU_NAND_CON);
	for (i = 0; i < op->ninstrs && !ret; i++) {
		instr = &op->instrs[i];
		switch (instr->type) {
		case NAND_OP_CMD_INSTR:
			writeb(instr->ctx.cmd.opcode, nand->data + NAND_IO_CMD);
			ret = grx500_nand_wait(nand, NAND_TRANSFER_COMPLETE, 1000);
			break;
		case NAND_OP_ADDR_INSTR:
			for (j = 0; j < instr->ctx.addr.naddrs && !ret; j++) {
				writeb(instr->ctx.addr.addrs[j], nand->data + NAND_IO_ADDR);
				ret = grx500_nand_wait(nand, NAND_TRANSFER_COMPLETE, 1000);
			}
			break;
		case NAND_OP_DATA_IN_INSTR:
			for (j = 0; j < instr->ctx.data.len && !ret; j++) {
				((u8 *)instr->ctx.data.buf.in)[j] = readb(nand->data + NAND_IO_DATA);
				ret = grx500_nand_wait(nand, NAND_TRANSFER_COMPLETE, 1000);
			}
			break;
		case NAND_OP_DATA_OUT_INSTR:
			for (j = 0; j < instr->ctx.data.len && !ret; j++) {
				writeb(((const u8 *)instr->ctx.data.buf.out)[j],
				       nand->data + NAND_IO_DATA);
				ret = grx500_nand_wait(nand, NAND_TRANSFER_COMPLETE, 1000);
			}
			break;
		case NAND_OP_WAITRDY_INSTR:
			/* Sleepable ready/busy wait; never spin for a full reset timeout. */
			ret = read_poll_timeout(__raw_readl, value, value & NAND_READY,
					20, clamp_t(u64, (u64)instr->ctx.waitrdy.timeout_ms * 1000,
						    1000, 1000000),
					false, nand->ebu + EBU_NAND_WAIT);
			break;
		default:
			ret = -EOPNOTSUPP;
		}
		if (!ret && instr->delay_ns)
			ndelay(instr->delay_ns);
	}
	value = __raw_readl(nand->ebu + EBU_NAND_CON);
	__raw_writel(value & ~(NAND_CE | NAND_ENABLE), nand->ebu + EBU_NAND_CON);
	return ret;
}

static int grx500_nand_attach(struct nand_chip *chip)
{
	struct mtd_info *mtd = nand_to_mtd(chip);

	if (chip->options & NAND_BUSWIDTH_16 || mtd->writesize < 2048 || mtd->oobsize < 64)
		return -EINVAL;
	/* Exact stock CONFIG_LTQ_BCH_MODE + CONFIG_LTQ_BCH_4BITS format. */
	chip->ecc.engine_type = NAND_ECC_ENGINE_TYPE_SOFT;
	chip->ecc.algo = NAND_ECC_ALGO_BCH;
	chip->ecc.size = 512;
	chip->ecc.strength = 4;
	/* Default BCH layout stores 7 ECC bytes/step at the OOB tail, matching stock. */
	return 0;
}

static const struct nand_controller_ops grx500_nand_ops = {
	.attach_chip = grx500_nand_attach,
	.exec_op = grx500_nand_exec_op,
};

static void grx500_nand_disable_clock(void *data)
{
	clk_disable_unprepare(data);
}

/* Stock U-Boot mtdparts, not the incompatible reference-board DT layout.
 * Bootloader, GPHY and calibration remain protected. The opt-in factory trial
 * build permits redundant environment updates for guarded bank commitment.
 */
static const struct mtd_partition grx500_partitions[] = {
	{ .name = "uboot", .offset = 0, .size = 0x100000,
	  .mask_flags = MTD_WRITEABLE },
	{ .name = "ubootconfigA", .offset = 0x100000, .size = 0x40000,
	  .mask_flags = IS_ENABLED(CONFIG_GRX500_FACTORY_TRIAL) ? 0 : MTD_WRITEABLE },
	{ .name = "ubootconfigB", .offset = 0x140000, .size = 0x40000,
	  .mask_flags = IS_ENABLED(CONFIG_GRX500_FACTORY_TRIAL) ? 0 : MTD_WRITEABLE },
	{ .name = "gphyfirmware", .offset = 0x180000, .size = 0x40000,
	  .mask_flags = MTD_WRITEABLE },
	{ .name = "calibration", .offset = 0x1c0000, .size = 0x100000,
	  .mask_flags = MTD_WRITEABLE },
	{ .name = "system_sw", .offset = 0x2c0000, .size = 0x7c00000 },
	{ .name = "res", .offset = 0x7ec0000, .size = MTDPART_SIZ_FULL,
	  .mask_flags = MTD_WRITEABLE },
};

static int grx500_nand_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct grx500_nand *nand;
	struct mtd_info *mtd;
	struct resource *res;
	int ret;

	nand = devm_kzalloc(dev, sizeof(*nand), GFP_KERNEL);
	if (!nand)
		return -ENOMEM;
	nand->ebu = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(nand->ebu))
		return PTR_ERR(nand->ebu);
	nand->data = devm_platform_ioremap_resource(pdev, 1);
	if (IS_ERR(nand->data))
		return PTR_ERR(nand->data);
	res = platform_get_resource(pdev, IORESOURCE_MEM, 1);
	if (res->start != 0x17c00000)
		return -EINVAL;
	nand->clk = devm_clk_get(dev, NULL);
	if (IS_ERR(nand->clk))
		return dev_err_probe(dev, PTR_ERR(nand->clk), "EBU clock unavailable\n");
	ret = clk_prepare_enable(nand->clk);
	if (ret)
		return ret;
	ret = devm_add_action_or_reset(dev, grx500_nand_disable_clock, nand->clk);
	if (ret)
		return ret;
	/* CS1 mapping/timings copied from the stock GRX500 PIO NAND driver. */
	__raw_writel(res->start | (5 << 4) | 1, nand->ebu + EBU_ADDSEL1);
	__raw_writel(BIT(22) | (3 << 12) | (2 << 8) | (2 << 6) |
		     BIT(4) | BIT(2) | 1, nand->ebu + EBU_BUSCON1);
	__raw_writel(NAND_ENABLE | BIT(1) | BIT(4) | BIT(5) | BIT(6) |
		     BIT(7) | BIT(8) | BIT(10), nand->ebu + EBU_NAND_CON);
	nand_controller_init(&nand->controller);
	nand->controller.ops = &grx500_nand_ops;
	nand->chip.controller = &nand->controller;
	nand_set_controller_data(&nand->chip, nand);
	nand_set_flash_node(&nand->chip, dev->of_node);
	nand->chip.options |= NAND_NO_SUBPAGE_WRITE;
	mtd = nand_to_mtd(&nand->chip);
	mtd->dev.parent = dev;
	mtd->name = "17c00000.nand-parts";
	platform_set_drvdata(pdev, nand);
	ret = nand_scan(&nand->chip, 1);
	if (ret)
		return ret;
	/* This profile describes the AX3000's documented 128 MiB NAND only. */
	if (mtd->size != SZ_128M || mtd->writesize != SZ_2K ||
	    mtd->erasesize != SZ_128K) {
		dev_err(dev, "NAND geometry disagrees with AX3000 stock configuration\n");
		nand_cleanup(&nand->chip);
		return -EINVAL;
	}
	ret = mtd_device_register(mtd, grx500_partitions,
				  ARRAY_SIZE(grx500_partitions));
	if (ret)
		nand_cleanup(&nand->chip);
	return ret;
}

static void grx500_nand_remove(struct platform_device *pdev)
{
	struct grx500_nand *nand = platform_get_drvdata(pdev);
	int ret = mtd_device_unregister(nand_to_mtd(&nand->chip));

	WARN_ON(ret);
	nand_cleanup(&nand->chip);
}

static const struct of_device_id grx500_nand_match[] = {
	{ .compatible = "tplink,archer-ax3000-v1-nand" },
	{}
};

static struct platform_driver grx500_nand_driver = {
	.probe = grx500_nand_probe,
	.remove = grx500_nand_remove,
	.driver = { .name = "grx500-nand", .of_match_table = grx500_nand_match },
};
builtin_platform_driver(grx500_nand_driver);
