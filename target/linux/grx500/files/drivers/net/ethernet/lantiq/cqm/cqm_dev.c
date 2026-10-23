// SPDX-License-Identifier: GPL-2.0-only
/* GRX500 OF platform data. The OF core owns the single platform device. */
#include "cqm_dev.h"

struct cqm_data *cqm_platform_data(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct cqm_data *data;
	unsigned int highprio;
	int i, irq;

	data = devm_kzalloc(dev, sizeof(*data), GFP_KERNEL);
	if (!data)
		return ERR_PTR(-ENOMEM);
	while (platform_get_resource(pdev, IORESOURCE_MEM, data->num_resources))
		data->num_resources++;
	if (data->num_resources != 12)
		return ERR_PTR(-EINVAL);
	data->num_intrs = platform_irq_count(pdev);
	if (data->num_intrs < 5)
		return ERR_PTR(data->num_intrs < 0 ? data->num_intrs : -EINVAL);
	data->intrs = devm_kcalloc(dev, data->num_intrs, sizeof(*data->intrs), GFP_KERNEL);
	if (!data->intrs)
		return ERR_PTR(-ENOMEM);
	for (i = 0; i < data->num_intrs; i++) {
		irq = platform_get_irq(pdev, i);
		if (irq < 0)
			return ERR_PTR(irq);
		data->intrs[i] = irq;
	}
	data->cqm_clk[0] = devm_clk_get(dev, "freq");
	if (IS_ERR(data->cqm_clk[0]))
		return ERR_CAST(data->cqm_clk[0]);
	data->cqm_clk[1] = devm_clk_get(dev, "cbm");
	if (IS_ERR(data->cqm_clk[1]))
		return ERR_CAST(data->cqm_clk[1]);
	if (of_property_read_u32(dev->of_node, "intel,highprio-lan", &highprio) || highprio > 1)
		return ERR_PTR(-EINVAL);
	data->highprio_lan = highprio;
	platform_set_drvdata(pdev, data);
	return data;
}
