// SPDX-License-Identifier: GPL-2.0
/*
 * Copyright (C) 2016 Intel Corporation.
 */
#include <linux/init.h>
#include <linux/irqchip.h>
#include <linux/of_irq.h>
#include <asm/irq.h>
#include <asm/irq_cpu.h>
#include <asm/mips-cps.h>
#include <asm/time.h>

void __init arch_init_irq(void)
{
	struct device_node *intc_node;

	pr_info("EIC is %s\n", cpu_has_veic ? "on" : "off");
	pr_info("VINT is %s\n", cpu_has_vint ? "on" : "off");

	intc_node = of_find_compatible_node(NULL, NULL,
					    "mti,cpu-interrupt-controller");
	if (!cpu_has_veic && !intc_node)
		mips_cpu_irq_init();
	of_node_put(intc_node);

	irqchip_init();
}

asmlinkage void plat_irq_dispatch(void)
{
	unsigned int pending = read_c0_cause() & read_c0_status() & ST0_IM;

	if (pending)
		do_IRQ(MIPS_CPU_IRQ_BASE + fls(pending) - 1 - CAUSEB_IP);
	else
		spurious_interrupt();
}

int get_c0_perfcount_int(void)
{
	return gic_get_c0_perfcount_int();
}
EXPORT_SYMBOL_GPL(get_c0_perfcount_int);

unsigned int get_c0_compare_int(void)
{
	return gic_get_c0_compare_int();
}
