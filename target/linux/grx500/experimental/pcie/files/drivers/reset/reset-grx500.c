// SPDX-License-Identifier: GPL-2.0
/* GRX500 RCU reset control, based on Intel reset-intel-syscon.c (2017). */
#include <linux/bitops.h>
#include <linux/init.h>
#include <linux/mfd/syscon.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/reset-controller.h>

struct grx500_reset {
	struct reset_controller_dev rcdev;
	struct regmap *map;
};

static u32 grx500_status_offset(u32 offset)
{
	return offset == 0x48 ? 0x24 : offset + 4;
}

static int grx500_reset_update(struct reset_controller_dev *rcdev,
			       unsigned long id, bool assert)
{
	struct grx500_reset *rst = container_of(rcdev, struct grx500_reset, rcdev);
	u32 offset = id >> 8, mask = BIT(id & 31), value;
	int ret;

	ret = regmap_update_bits(rst->map, offset, mask, assert ? mask : 0);
	if (ret)
		return ret;
	/* GPHY power down is a control bit without reset status. */
	if (offset == 0x48 && (id & 31) == 27)
		return 0;
	return regmap_read_poll_timeout(rst->map, grx500_status_offset(offset),
					value, !!(value & mask) == assert, 20, 200);
}

static int grx500_reset_assert(struct reset_controller_dev *rcdev, unsigned long id)
{
	return grx500_reset_update(rcdev, id, true);
}

static int grx500_reset_deassert(struct reset_controller_dev *rcdev, unsigned long id)
{
	return grx500_reset_update(rcdev, id, false);
}

static int grx500_reset_status(struct reset_controller_dev *rcdev, unsigned long id)
{
	struct grx500_reset *rst = container_of(rcdev, struct grx500_reset, rcdev);
	u32 value;
	int ret;

	ret = regmap_read(rst->map, grx500_status_offset(id >> 8), &value);
	return ret ? ret : !!(value & BIT(id & 31));
}

static int grx500_reset_xlate(struct reset_controller_dev *rcdev,
			      const struct of_phandle_args *spec)
{
	/* Only documented GRX500 reset request registers, never adjacent status. */
	if ((spec->args[0] != 0x10 && spec->args[0] != 0x48) || spec->args[1] > 31)
		return -EINVAL;
	return (spec->args[0] << 8) | spec->args[1];
}

static const struct reset_control_ops grx500_reset_ops = {
	.assert = grx500_reset_assert,
	.deassert = grx500_reset_deassert,
	.status = grx500_reset_status,
};

static int grx500_reset_probe(struct platform_device *pdev)
{
	struct grx500_reset *rst;

	rst = devm_kzalloc(&pdev->dev, sizeof(*rst), GFP_KERNEL);
	if (!rst)
		return -ENOMEM;
	rst->map = syscon_node_to_regmap(pdev->dev.of_node);
	if (IS_ERR(rst->map))
		return PTR_ERR(rst->map);
	rst->rcdev.dev = &pdev->dev;
	rst->rcdev.of_node = pdev->dev.of_node;
	rst->rcdev.ops = &grx500_reset_ops;
	rst->rcdev.of_reset_n_cells = 2;
	rst->rcdev.of_xlate = grx500_reset_xlate;
	rst->rcdev.nr_resets = 0x4820;
	return devm_reset_controller_register(&pdev->dev, &rst->rcdev);
}

static const struct of_device_id grx500_reset_match[] = {
	{ .compatible = "lantiq,rcu-grx500" },
	{}
};

static struct platform_driver grx500_reset_driver = {
	.probe = grx500_reset_probe,
	.driver = { .name = "grx500-reset", .of_match_table = grx500_reset_match },
};
builtin_platform_driver(grx500_reset_driver);
