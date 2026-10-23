#!/usr/bin/env python3
"""Reproduce the Intel 4.9 GRX500 host adaptation, without modifying sources."""
from pathlib import Path
base=Path(__file__).resolve().parent
src=base.parent/'intel-linux/drivers/pci/host/pcie-intel.c'
s=src.read_text()
s=s.replace('#include <linux/property.h>', '#include <linux/property.h>\n#include <linux/pm_runtime.h>')
s=s.replace('\tstruct pci_bus\t*root_bus;', '\tstruct pci_bus\t*root_bus;\n\tbool clocks_enabled;\n\tbool phy_initialized;\n\tbool runtime_active;\n\tbool irq_requested;')
s=s.replace('static int intel_pcie_remove(struct platform_device *pdev)', 'static void intel_pcie_remove(struct platform_device *pdev)')
s=s.replace('\t__intel_pcie_remove(lpp);\n\n\treturn 0;\n}', '\t__intel_pcie_remove(lpp);\n}')
s=s.replace('devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_LOW)', 'devm_gpiod_get_optional(dev, "reset", GPIOD_OUT_HIGH)')
s=s.replace('if (IS_ERR(lpp->cfg0_base)) {', 'if (!lpp->cfg0_base) {').replace('if (IS_ERR(lpp->cfg1_base)) {', 'if (!lpp->cfg1_base) {')
s=s.replace('\tu32 prop;\n\tstruct resource *res;', '\tu32 prop = 0;\n\tstruct resource *res;')
s=s.replace('if (unlikely(((size - 1) & where))) {', 'if (unlikely((size != 1 && size != 2 && size != 4) || ((size - 1) & where) || where < 0 || where + size > 4096)) {')
# No 8th downstream bus: the fixed GRX500 ECAM window only has 3 bus bits.
s=s.replace('if (bus->primary == lpp->root_bus_nr && dev > 0)', 'if ((!lpp->has_iatu && bus->number > 7) ||\n\t    (bus->primary == lpp->root_bus_nr && dev > 0))')
start=s.index('static int intel_pcie_host_setup(')
end=s.index('\nstatic ssize_t',start)
s=s[:start]+'''static int intel_pcie_host_setup(struct intel_pcie_port *lpp)
{
	int ret;

	pm_runtime_enable(lpp->dev);
	ret = pm_runtime_resume_and_get(lpp->dev);
	if (ret < 0) {
		pm_runtime_disable(lpp->dev);
		return ret;
	}
	lpp->runtime_active = true;
	intel_pcie_core_rst_assert(lpp);
	intel_pcie_device_rst_assert(lpp);
	intel_pcie_core_rst_deassert(lpp);
	ret = intel_pcie_enable_clks(lpp);
	if (ret)
		return ret;
	lpp->clocks_enabled = true;
	ret = phy_init(lpp->phy);
	if (ret)
		return ret;
	lpp->phy_initialized = true;
	intel_pcie_rc_setup(lpp);
	ret = intel_pcie_app_loigc_setup(lpp);
	if (ret)
		return ret;
	ret = intel_pcie_setup_irq(lpp);
	if (!ret)
		lpp->irq_requested = true;
	return ret;
}
''' + s[end:]
start=s.index('static void __intel_pcie_remove(')
end=s.index('\nstatic void intel_pcie_remove(',start)
s=s[:start]+'''static void __intel_pcie_remove(struct intel_pcie_port *lpp)
{
	if (lpp->clocks_enabled) {
		intel_pcie_core_irq_disable(lpp);
		if (lpp->irq_requested) {
			devm_free_irq(lpp->dev, lpp->plat_irq, lpp);
			lpp->irq_requested = false;
		}
		intel_pcie_turn_off(lpp);
	}
	if (lpp->phy_initialized) {
		intel_pcie_deinit_phy(lpp);
		lpp->phy_initialized = false;
	}
	if (lpp->clocks_enabled) {
		intel_pcie_disable_clks(lpp);
		lpp->clocks_enabled = false;
	}
	intel_pcie_core_rst_assert(lpp);
	intel_pcie_sysfs_deinit(lpp);
	if (lpp->runtime_active) {
		pm_runtime_put_sync(lpp->dev);
		pm_runtime_disable(lpp->dev);
		lpp->runtime_active = false;
	}
	intel_pcie_remove_controller(lpp);
}
''' + s[end:]
start=s.index('static int intel_pcie_probe(')
end=s.index('\nstatic const struct dev_pm_ops',start)
s=s[:start]+'''static int intel_pcie_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct pci_host_bridge *bridge;
	struct intel_pcie_port *lpp;
	struct resource_entry *win;
	int ret;

	bridge = devm_pci_alloc_host_bridge(dev, sizeof(*lpp));
	if (!bridge)
		return -ENOMEM;
	lpp = pci_host_bridge_priv(bridge);
	lpp->id = of_alias_get_id(dev->of_node, "pcie");
	if (lpp->id < 0 || lpp->id > 2)
		return -EINVAL;
	lpp->dev = dev;
	spin_lock_init(&lpp->lock);
	INIT_LIST_HEAD(&lpp->list);
	platform_set_drvdata(pdev, lpp);
	ret = intel_pcie_get_resources(pdev);
	if (ret)
		return ret;
	/* GRX500 has fixed windows; other SoCs need separate validation. */
	if (lpp->has_iatu)
		return -EINVAL;
	intel_pcie_endian_setup(lpp);
	ret = intel_pcie_ep_rst_init(lpp);
	if (ret)
		return ret;
	resource_list_for_each_entry(win, &bridge->windows) {
		if (resource_type(win->res) == IORESOURCE_BUS)
			lpp->root_bus_nr = win->res->start;
	}
	if (lpp->root_bus_nr != 0)
		return -EINVAL;
	intel_pcie_add_controller(lpp);
	ret = intel_pcie_host_setup(lpp);
	if (ret)
		goto err_host;
	bridge->sysdata = lpp;
	bridge->ops = &intel_pcie_ops;
	bridge->map_irq = intel_pcie_bios_map_irq;
	bridge->swizzle_irq = pci_common_swizzle;
	ret = pci_host_probe(bridge);
	if (ret)
		goto err_host;
	lpp->root_bus = bridge->bus;
	ret = intel_pcie_sysfs_init(lpp);
	if (ret)
		dev_warn(dev, "link status attributes unavailable: %d\\n", ret);
	dev_info(dev, "GRX500 PCIe port %d initialized (INTx)\\n", lpp->id);
	return 0;
err_host:
	__intel_pcie_remove(lpp);
	return ret;
}
''' + s[end:]
s=s.replace('\t{ .compatible = "intel,prx300-pcie" },\n','')
# Avoid unused legacy MSI APIs and obsolete speculative support in the export.
def strip_ifdef(text, macro):
    result=[]; stack=[]; enabled=True
    for line in text.splitlines(True):
        directive=line.strip()
        if directive in ('#ifdef '+macro, '#if defined('+macro+')'):
            stack.append((enabled, True)); enabled=False
        elif directive.startswith(('#if ', '#ifdef ', '#ifndef ')):
            stack.append((enabled, False))
            if enabled:result.append(line)
        elif directive.startswith('#endif') and stack:
            outer, ours=stack.pop()
            if not ours and enabled:result.append(line)
            enabled=outer
        elif directive.startswith('#else') and stack and stack[-1][1]:
            enabled=stack[-1][0]
        elif enabled:result.append(line)
    return ''.join(result)
s=strip_ifdef(s,'CONFIG_PCIE_INTEL_MSI_PIC')
(base/'files/drivers/pci/controller/pcie-grx500.c').write_text(s)
