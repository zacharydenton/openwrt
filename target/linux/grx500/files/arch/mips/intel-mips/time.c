// SPDX-License-Identifier: GPL-2.0
/*
 * Copyright (C) 2016 Intel Corporation.
 */

#include <linux/clk.h>
#include <linux/clk-provider.h>
#include <linux/clocksource.h>
#include <linux/of.h>

#include <asm/time.h>

void __init plat_time_init(void)
{
	unsigned long cpuclk;
	struct device_node *np;
	struct clk *clk;

	of_clk_init(NULL);

	np = of_get_cpu_node(0, NULL);
	if (!np)
		panic("GRX500: missing CPU node");

	clk = of_clk_get(np, 0);
	of_node_put(np);
	if (IS_ERR(clk))
		panic("GRX500: missing CPU clock: %ld", PTR_ERR(clk));

	cpuclk = clk_get_rate(clk);
	if (!cpuclk)
		panic("GRX500: zero CPU clock");
	/* The CP0 counter runs at half the CPU clock frequency. */
	mips_hpt_frequency = cpuclk / 2;
	clk_put(clk);

	write_c0_compare(read_c0_count());
	pr_info("CPU Clock: %ldHz  mips_hpt_frequency %dHz\n",
		cpuclk, mips_hpt_frequency);
	timer_probe();
}
