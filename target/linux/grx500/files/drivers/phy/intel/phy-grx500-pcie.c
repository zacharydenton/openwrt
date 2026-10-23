// SPDX-License-Identifier: GPL-2.0
/* GRX500 PCIe PHY, based on Intel phy-intel-slim.c, Copyright (C) 2018 Intel. */
#include <linux/delay.h>
#include <linux/io.h>
#include <linux/mfd/syscon.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/phy/phy.h>
#include <linux/platform_device.h>
#include <linux/property.h>
#include <linux/regmap.h>
#include <linux/reset.h>

#define PHY_CFG4 0xc014
#define PHY_PIPE_POWER_DOWN BIT(15)
#define LCPLL_CFG0 0x94
#define LCPLL_CFG1 0x98
#define LCPLL_SSC_CTRL 0x9c
#define LCPLL_COEF0 0xa4
#define LCPLL_LOCKED BIT(1)
#define CHIPTOP_IFMUX 0x120

/* All three PHYs share the same LCPLL. Serialize its complete lock sequence. */
static DEFINE_MUTEX(grx500_lcpll_lock);
static bool grx500_ssc_ready;

struct grx500_pcie_phy {
	struct device *dev;
	void __iomem *base;
	struct regmap *cgu;
	struct regmap *chiptop;
	struct reset_control *reset;
	u32 id;
	bool ssc;
};

static int grx500_ssc_enable(struct grx500_pcie_phy *phy)
{
	static const struct reg_sequence setup[] = {
		{LCPLL_CFG1, 0x10003004}, {LCPLL_CFG1, 0x10103004},
		{LCPLL_CFG0, 0x00000190}, {LCPLL_CFG0, 0x00000191},
	};
	static const struct reg_sequence coefficients[] = {
		{LCPLL_COEF0 + 0, 0x0000ff60}, {LCPLL_COEF0 + 4, 0x0000ff60},
		{LCPLL_COEF0 + 8, 0x0000ff60}, {LCPLL_COEF0 + 12, 0x0000ff60},
		{LCPLL_COEF0 + 16, 0x000000a0}, {LCPLL_COEF0 + 20, 0x000000a0},
		{LCPLL_COEF0 + 24, 0x000000a0}, {LCPLL_COEF0 + 28, 0x000000a0},
		{LCPLL_SSC_CTRL, 0x0000ff1c}, {LCPLL_SSC_CTRL, 0x0000ff1f},
		{LCPLL_SSC_CTRL, 0x0000ff1c}, {LCPLL_SSC_CTRL, 0x0000ff1d},
	};
	u32 value;
	int ret = 0;

	if (!phy->ssc)
		return 0;
	mutex_lock(&grx500_lcpll_lock);
	if (grx500_ssc_ready)
		goto out;
	ret = regmap_multi_reg_write(phy->cgu, setup, ARRAY_SIZE(setup));
	if (ret)
		goto out;
	ret = regmap_read_poll_timeout(phy->cgu, LCPLL_CFG0, value,
					value & LCPLL_LOCKED, 100, 100000);
	if (ret)
		goto out;
	ret = regmap_multi_reg_write(phy->cgu, coefficients, ARRAY_SIZE(coefficients));
	if (!ret) {
		usleep_range(1000, 2000);
		grx500_ssc_ready = true;
	}
out:
	mutex_unlock(&grx500_lcpll_lock);
	return ret;
}

static int grx500_pcie_phy_init(struct phy *generic_phy)
{
	struct grx500_pcie_phy *phy = phy_get_drvdata(generic_phy);
	u32 value;
	int ret;

	/* These on-chip registers are CPU-native endian on GRX500. */
	value = __raw_readl(phy->base + PHY_CFG4);
	__raw_writel(value | PHY_PIPE_POWER_DOWN, phy->base + PHY_CFG4);
	usleep_range(1000, 2000);
	ret = grx500_ssc_enable(phy);
	/* Always restore the PHY's power state, including LCPLL failure. */
	__raw_writel(value & ~PHY_PIPE_POWER_DOWN, phy->base + PHY_CFG4);
	usleep_range(1000, 2000);
	if (ret)
		return dev_err_probe(phy->dev, ret, "PCIe LCPLL configuration failed\n");
	ret = reset_control_assert(phy->reset);
	if (ret)
		return ret;
	udelay(1);
	ret = reset_control_deassert(phy->reset);
	if (ret)
		return ret;
	udelay(1);
	/* CHIPTOP bit 22+id is reference-clock disable, active high. */
	return regmap_update_bits(phy->chiptop, CHIPTOP_IFMUX, BIT(22 + phy->id), 0);
}

static int grx500_pcie_phy_exit(struct phy *generic_phy)
{
	struct grx500_pcie_phy *phy = phy_get_drvdata(generic_phy);

	/* Powering down a live GRX500 PHY can halt the SoC. Gate its output only.
	 * The shared LCPLL remains configured; other PCIe ports may still use it.
	 */
	return regmap_update_bits(phy->chiptop, CHIPTOP_IFMUX,
				 BIT(22 + phy->id), BIT(22 + phy->id));
}

static const struct phy_ops grx500_pcie_phy_ops = {
	.init = grx500_pcie_phy_init,
	.exit = grx500_pcie_phy_exit,
};

static int grx500_pcie_phy_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct grx500_pcie_phy *priv;
	struct phy_provider *provider;
	struct phy *phy;
	u32 ssc;
	int id;

	priv = devm_kzalloc(dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;
	id = of_alias_get_id(dev->of_node, "pciephy");
	if (id < 0 || id > 2)
		return -EINVAL;
	priv->id = id;
	priv->dev = dev;
	priv->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(priv->base))
		return PTR_ERR(priv->base);
	priv->cgu = syscon_regmap_lookup_by_phandle(dev->of_node, "intel,ssc-syscon");
	if (IS_ERR(priv->cgu))
		return dev_err_probe(dev, PTR_ERR(priv->cgu), "CGU unavailable\n");
	priv->chiptop = syscon_regmap_lookup_by_phandle(dev->of_node, "intel,syscon");
	if (IS_ERR(priv->chiptop))
		return dev_err_probe(dev, PTR_ERR(priv->chiptop), "CHIPTOP unavailable\n");
	priv->reset = devm_reset_control_get_exclusive(dev, "phy");
	if (IS_ERR(priv->reset))
		return dev_err_probe(dev, PTR_ERR(priv->reset), "PHY reset unavailable\n");
	if (!device_property_read_u32(dev, "intel,ssc-enable", &ssc))
		priv->ssc = !!ssc;
	phy = devm_phy_create(dev, dev->of_node, &grx500_pcie_phy_ops);
	if (IS_ERR(phy))
		return PTR_ERR(phy);
	phy_set_drvdata(phy, priv);
	provider = devm_of_phy_provider_register(dev, of_phy_simple_xlate);
	return PTR_ERR_OR_ZERO(provider);
}

static const struct of_device_id grx500_pcie_phy_match[] = {
	{ .compatible = "intel,grx500-pciephy" },
	{}
};
static struct platform_driver grx500_pcie_phy_driver = {
	.probe = grx500_pcie_phy_probe,
	.driver = { .name = "grx500-pcie-phy", .of_match_table = grx500_pcie_phy_match },
};
builtin_platform_driver(grx500_pcie_phy_driver);
