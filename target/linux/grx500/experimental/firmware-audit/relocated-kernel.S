/* SPDX-License-Identifier: GPL-2.0-only */
	.set noreorder
	.set mips32r2
	.section .text.start,"ax",@progbits
	.globl startup
	.ent startup
startup:
	/* Leave U-Boot's arguments, CP0 state and segment mapping intact. */
	move $8, $29
	lui $29, 0xa3ff
	addiu $29, $29, -32
	sw $8, 16($29)
	sw $31, 20($29)
	jal loader_main
	nop
	/* On a decoding failure return to stock bootm and its reset command. */
	lw $31, 20($29)
	lw $29, 16($29)
	jr $31
	nop
	.end startup
