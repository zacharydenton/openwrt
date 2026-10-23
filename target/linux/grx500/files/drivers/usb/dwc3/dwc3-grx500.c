// SPDX-License-Identifier: GPL-2.0-only
/* GRX500 integration based on Intel's 2016-2017 dwc3-grx500.c. */
#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include "glue.h"

struct grx500_dwc3 {
	struct dwc3 dwc;
	struct clk *clk;
};

static int grx500_dwc3_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct dwc3_probe_data data = {};
	struct grx500_dwc3 *usb;
	struct regmap *chiptop;
	unsigned int offset;
	int ret;

	usb = devm_kzalloc(dev, sizeof(*usb), GFP_KERNEL);
	if (!usb)
		return -ENOMEM;
	chiptop = syscon_regmap_lookup_by_phandle_args(dev->of_node,
						     "intel,syscon", 1, &offset);
	if (IS_ERR(chiptop))
		return dev_err_probe(dev, PTR_ERR(chiptop), "missing chiptop syscon\n");
	if (offset != 0x18 && offset != 0x34)
		return -EINVAL;
	usb->clk = devm_clk_get_enabled(dev, NULL);
	if (IS_ERR(usb->clk))
		return dev_err_probe(dev, PTR_ERR(usb->clk), "failed to enable USB clock\n");
	msleep(100);

	/* Stock and Intel 4.9 use host AXI big endian, device little endian.
	 * GRX500 uses native MMIO accessors; descriptor memory stays USB LE.
	 */
	ret = regmap_update_bits(chiptop, offset, BIT(10) | BIT(9), BIT(10));
	if (ret)
		return ret;
	msleep(100);
	ret = dma_set_mask_and_coherent(dev, DMA_BIT_MASK(32));
	if (ret)
		return ret;
	data.res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	if (!data.res)
		return -ENODEV;
	usb->dwc.dev = dev;
	data.dwc = &usb->dwc;
	data.ignore_clocks_and_resets = true;
	ret = dwc3_core_probe(&data);
	if (ret)
		return dev_err_probe(dev, ret, "DWC3 initialization failed\n");
	return 0;
}

static void grx500_dwc3_remove(struct platform_device *pdev)
{
	dwc3_core_remove(platform_get_drvdata(pdev));
}

static int grx500_dwc3_suspend(struct device *dev)
{
	struct dwc3 *dwc = dev_get_drvdata(dev);
	struct grx500_dwc3 *usb = container_of(dwc, struct grx500_dwc3, dwc);
	int ret = dwc3_pm_suspend(dwc);

	if (!ret)
		clk_disable_unprepare(usb->clk);
	return ret;
}

static int grx500_dwc3_resume(struct device *dev)
{
	struct dwc3 *dwc = dev_get_drvdata(dev);
	struct grx500_dwc3 *usb = container_of(dwc, struct grx500_dwc3, dwc);
	int ret = clk_prepare_enable(usb->clk);

	if (ret)
		return ret;
	msleep(100);
	ret = dwc3_pm_resume(dwc);
	if (ret)
		clk_disable_unprepare(usb->clk);
	return ret;
}

static int grx500_dwc3_runtime_suspend(struct device *dev)
{
	return dwc3_runtime_suspend(dev_get_drvdata(dev));
}

static int grx500_dwc3_runtime_resume(struct device *dev)
{
	return dwc3_runtime_resume(dev_get_drvdata(dev));
}

static int grx500_dwc3_runtime_idle(struct device *dev)
{
	return dwc3_runtime_idle(dev_get_drvdata(dev));
}

static const struct dev_pm_ops grx500_dwc3_pm_ops = {
	SYSTEM_SLEEP_PM_OPS(grx500_dwc3_suspend, grx500_dwc3_resume)
	RUNTIME_PM_OPS(grx500_dwc3_runtime_suspend, grx500_dwc3_runtime_resume,
		       grx500_dwc3_runtime_idle)
};

static const struct of_device_id grx500_dwc3_match[] = {
	{ .compatible = "intel,grx500-dwc3" },
	{}
};
MODULE_DEVICE_TABLE(of, grx500_dwc3_match);

static struct platform_driver grx500_dwc3_driver = {
	.probe = grx500_dwc3_probe,
	.remove = grx500_dwc3_remove,
	.driver = {
		.name = "dwc3-grx500",
		.of_match_table = grx500_dwc3_match,
		.pm = pm_ptr(&grx500_dwc3_pm_ops),
	},
};
module_platform_driver(grx500_dwc3_driver);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Intel GRX500 DWC3 host integration");
