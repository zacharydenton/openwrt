// SPDX-License-Identifier: GPL-2.0
/*
 * GRX500 GPIO and per-pin GPIO mux selection.
 * Register operations derived from gpio-xrx500.c and pinctrl-xrx500.c:
 * Copyright (C) 2012 Thomas Langer, John Crispin
 * Copyright (C) 2014 Kavitha Subramanian
 */
#include <linux/gpio/driver.h>
#include <linux/io.h>
#include <linux/platform_device.h>
#include <linux/property.h>

#define GPIO_OUT 0x00
#define GPIO_IN 0x04
#define GPIO_DIR 0x08
#define GPIO_OUTSET 0x40
#define GPIO_OUTCLR 0x44
#define GPIO_DIRSET 0x48
#define GPIO_DIRCLR 0x4c

struct grx500_gpio {
	struct gpio_chip chip;
	void __iomem *regs;
	void __iomem *pads;
};

static int grx500_gpio_request(struct gpio_chip *chip, unsigned int pin)
{
	struct grx500_gpio *gpio = gpiochip_get_data(chip);

	/* Each bank has a separate 0x100-byte pinpad resource. GPIO is mux 0. */
	__raw_writel(0, gpio->pads + pin * 4);
	return 0;
}

static int grx500_gpio_set(struct gpio_chip *chip, unsigned int pin, int value)
{
	struct grx500_gpio *gpio = gpiochip_get_data(chip);

	__raw_writel(BIT(pin), gpio->regs + (value ? GPIO_OUTSET : GPIO_OUTCLR));
	return 0;
}

static int grx500_gpio_get(struct gpio_chip *chip, unsigned int pin)
{
	struct grx500_gpio *gpio = gpiochip_get_data(chip);
	u32 reg = (__raw_readl(gpio->regs + GPIO_DIR) & BIT(pin)) ? GPIO_OUT : GPIO_IN;

	return !!(__raw_readl(gpio->regs + reg) & BIT(pin));
}

static int grx500_gpio_direction(struct gpio_chip *chip, unsigned int pin)
{
	struct grx500_gpio *gpio = gpiochip_get_data(chip);

	return (__raw_readl(gpio->regs + GPIO_DIR) & BIT(pin)) ?
		GPIO_LINE_DIRECTION_OUT : GPIO_LINE_DIRECTION_IN;
}

static int grx500_gpio_input(struct gpio_chip *chip, unsigned int pin)
{
	struct grx500_gpio *gpio = gpiochip_get_data(chip);

	__raw_writel(BIT(pin), gpio->regs + GPIO_DIRCLR);
	return 0;
}

static int grx500_gpio_output(struct gpio_chip *chip, unsigned int pin, int value)
{
	struct grx500_gpio *gpio = gpiochip_get_data(chip);

	grx500_gpio_set(chip, pin, value);
	__raw_writel(BIT(pin), gpio->regs + GPIO_DIRSET);
	return 0;
}

static int grx500_gpio_probe(struct platform_device *pdev)
{
	struct grx500_gpio *gpio;
	u32 ngpios = 32;

	gpio = devm_kzalloc(&pdev->dev, sizeof(*gpio), GFP_KERNEL);
	if (!gpio)
		return -ENOMEM;
	gpio->regs = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(gpio->regs))
		return PTR_ERR(gpio->regs);
	gpio->pads = devm_platform_ioremap_resource(pdev, 1);
	if (IS_ERR(gpio->pads))
		return PTR_ERR(gpio->pads);
	device_property_read_u32(&pdev->dev, "ngpios", &ngpios);
	if (!ngpios || ngpios > 32)
		return -EINVAL;
	gpio->chip.label = dev_name(&pdev->dev);
	gpio->chip.parent = &pdev->dev;
	gpio->chip.base = -1;
	gpio->chip.ngpio = ngpios;
	gpio->chip.request = grx500_gpio_request;
	gpio->chip.set = grx500_gpio_set;
	gpio->chip.get = grx500_gpio_get;
	gpio->chip.get_direction = grx500_gpio_direction;
	gpio->chip.direction_input = grx500_gpio_input;
	gpio->chip.direction_output = grx500_gpio_output;
	return devm_gpiochip_add_data(&pdev->dev, &gpio->chip, gpio);
}

static const struct of_device_id grx500_gpio_match[] = {
	{ .compatible = "intel,grx500-gpio" },
	{}
};
static struct platform_driver grx500_gpio_driver = {
	.probe = grx500_gpio_probe,
	.driver = { .name = "grx500-gpio", .of_match_table = grx500_gpio_match },
};
builtin_platform_driver(grx500_gpio_driver);
