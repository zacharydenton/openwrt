// SPDX-License-Identifier: GPL-2.0-only
/* GRX500 USB PHY and hardware VBUS overcurrent protection.
 * Register sequence follows Intel/TP-Link's phy-ltq-dwc3.c and ltq-usb-oc.c.
 */
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/mfd/syscon.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/phy/phy.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>
#include <linux/reset.h>
#include <linux/workqueue.h>

#define GRX500_PAD_MUX_MASK GENMASK(2, 0)
#define GRX500_PAD_USB_OC 3
#define GRX500_OC_RETRY_MS 30000

struct grx500_usb_phy {
	struct device *dev;
	void __iomem *base;
	struct reset_control *reset;
	struct gpio_desc *vbus;
	struct regmap *pads;
	unsigned int pad_offset;
	struct mutex lock;
	struct delayed_work oc_work;
	int irq;
	bool powered;
	bool irq_enabled;
};

static int grx500_usb_mux(struct grx500_usb_phy *priv, unsigned int mux)
{
	return regmap_update_bits(priv->pads, priv->pad_offset,
				 GRX500_PAD_MUX_MASK, mux);
}

static void grx500_usb_oc_retry(struct work_struct *work)
{
	struct grx500_usb_phy *priv = container_of(to_delayed_work(work),
					struct grx500_usb_phy, oc_work);
	int ret;

	mutex_lock(&priv->lock);
	if (!priv->powered)
		goto out;
	/* The OC pad's hardware state machine cuts VBUS. Switching to GPIO
	 * for 10 ms, then back to OC mode, rearms it as in the stock driver.
	 */
	ret = grx500_usb_mux(priv, 0);
	if (ret)
		goto failed;
	msleep(10);
	ret = grx500_usb_mux(priv, GRX500_PAD_USB_OC);
	if (ret)
		goto failed;
	msleep(10);
	priv->irq_enabled = true;
	enable_irq(priv->irq);
	goto out;
failed:
	priv->powered = false;
	gpiod_set_value_cansleep(priv->vbus, 0);
	/* Return control to the inactive GPIO latch on a fatal mux error. */
	grx500_usb_mux(priv, 0);
	reset_control_assert(priv->reset);
	dev_err(priv->dev, "cannot rearm USB overcurrent protection: %d\n", ret);
out:
	mutex_unlock(&priv->lock);
}

static irqreturn_t grx500_usb_overcurrent(int irq, void *data)
{
	struct grx500_usb_phy *priv = data;

	mutex_lock(&priv->lock);
	if (priv->powered && priv->irq_enabled) {
		/* Hardware disconnects VBUS; masking the level IRQ prevents a
		 * storm while the protection circuit waits for its retry.
		 */
		disable_irq_nosync(irq);
		priv->irq_enabled = false;
		dev_warn_ratelimited(priv->dev, "USB overcurrent; retry in 30 seconds\n");
		mod_delayed_work(system_wq, &priv->oc_work,
				 msecs_to_jiffies(GRX500_OC_RETRY_MS));
	}
	mutex_unlock(&priv->lock);
	return IRQ_HANDLED;
}

static int grx500_usb_power_on(struct phy *phy)
{
	struct grx500_usb_phy *priv = phy_get_drvdata(phy);
	int ret;

	mutex_lock(&priv->lock);
	gpiod_set_value_cansleep(priv->vbus, 1);
	ret = grx500_usb_mux(priv, GRX500_PAD_USB_OC);
	if (ret) {
		gpiod_set_value_cansleep(priv->vbus, 0);
		goto out;
	}
	priv->powered = true;
	priv->irq_enabled = true;
	enable_irq(priv->irq);
out:
	mutex_unlock(&priv->lock);
	return ret;
}

static void grx500_usb_stop(struct grx500_usb_phy *priv)
{
	mutex_lock(&priv->lock);
	priv->powered = false;
	if (priv->irq_enabled) {
		disable_irq_nosync(priv->irq);
		priv->irq_enabled = false;
	}
	mutex_unlock(&priv->lock);
	synchronize_irq(priv->irq);
	cancel_delayed_work_sync(&priv->oc_work);
	mutex_lock(&priv->lock);
	gpiod_set_value_cansleep(priv->vbus, 0);
	if (grx500_usb_mux(priv, 0))
		dev_err(priv->dev, "cannot restore USB VBUS GPIO mode\n");
	mutex_unlock(&priv->lock);
}

static int grx500_usb_power_off(struct phy *phy)
{
	grx500_usb_stop(phy_get_drvdata(phy));
	return 0;
}

static int grx500_usb_init(struct phy *phy)
{
	struct grx500_usb_phy *priv = phy_get_drvdata(phy);
	u32 value;
	int ret;

	ret = reset_control_deassert(priv->reset);
	if (ret)
		return ret;
	msleep(100);
	if (device_property_read_bool(priv->dev, "intel,tx-polarity-invert")) {
		value = readl(priv->base + 0x4000);
		writel(value | BIT(3), priv->base + 0x4000);
	}
	if (device_property_read_bool(priv->dev, "intel,rx-polarity-invert")) {
		value = readl(priv->base + 0x4014);
		writel(value | BIT(1), priv->base + 0x4014);
	}
	return 0;
}

static int grx500_usb_exit(struct phy *phy)
{
	struct grx500_usb_phy *priv = phy_get_drvdata(phy);

	return reset_control_assert(priv->reset);
}

static const struct phy_ops grx500_usb_ops = {
	.init = grx500_usb_init,
	.exit = grx500_usb_exit,
	.power_on = grx500_usb_power_on,
	.power_off = grx500_usb_power_off,
	.owner = THIS_MODULE,
};

static void grx500_usb_cleanup(void *data)
{
	grx500_usb_stop(data);
}

static int grx500_usb_phy_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct grx500_usb_phy *priv;
	struct phy_provider *provider;
	struct phy *phy;
	int ret;

	priv = devm_kzalloc(dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;
	priv->dev = dev;
	priv->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(priv->base))
		return PTR_ERR(priv->base);
	priv->reset = devm_reset_control_get_exclusive(dev, "phy");
	if (IS_ERR(priv->reset))
		return dev_err_probe(dev, PTR_ERR(priv->reset), "missing PHY reset\n");
	priv->vbus = devm_gpiod_get(dev, "vbus", GPIOD_OUT_LOW);
	if (IS_ERR(priv->vbus))
		return dev_err_probe(dev, PTR_ERR(priv->vbus), "missing VBUS GPIO\n");
	priv->pads = syscon_regmap_lookup_by_phandle_args(dev->of_node,
					"intel,pad-syscon", 1, &priv->pad_offset);
	if (IS_ERR(priv->pads))
		return dev_err_probe(dev, PTR_ERR(priv->pads), "missing pad syscon\n");
	if (priv->pad_offset >= 0x100 || (priv->pad_offset & 3))
		return -EINVAL;
	priv->irq = platform_get_irq(pdev, 0);
	if (priv->irq < 0)
		return priv->irq;
	mutex_init(&priv->lock);
	INIT_DELAYED_WORK(&priv->oc_work, grx500_usb_oc_retry);
	ret = devm_request_threaded_irq(dev, priv->irq, NULL,
			grx500_usb_overcurrent, IRQF_ONESHOT | IRQF_NO_AUTOEN,
			dev_name(dev), priv);
	if (ret)
		return dev_err_probe(dev, ret, "cannot request overcurrent IRQ\n");
	ret = devm_add_action_or_reset(dev, grx500_usb_cleanup, priv);
	if (ret)
		return ret;
	phy = devm_phy_create(dev, dev->of_node, &grx500_usb_ops);
	if (IS_ERR(phy))
		return PTR_ERR(phy);
	phy_set_drvdata(phy, priv);
	provider = devm_of_phy_provider_register(dev, of_phy_simple_xlate);
	return PTR_ERR_OR_ZERO(provider);
}

static const struct of_device_id grx500_usb_phy_match[] = {
	{ .compatible = "intel,grx500-usb-phy" },
	{}
};
MODULE_DEVICE_TABLE(of, grx500_usb_phy_match);

static struct platform_driver grx500_usb_phy_driver = {
	.probe = grx500_usb_phy_probe,
	.driver = {
		.name = "grx500-usb-phy",
		.of_match_table = grx500_usb_phy_match,
	},
};
module_platform_driver(grx500_usb_phy_driver);
MODULE_DESCRIPTION("Intel GRX500 USB PHY with VBUS overcurrent protection");
MODULE_LICENSE("GPL");
