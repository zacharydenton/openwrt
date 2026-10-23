OUTPUT_ARCH(mips)
ENTRY(startup)
SECTIONS
{
 . = 0xa4000000;
 .text : { KEEP(*(.text.start)) *(.text*) *(.rodata*) }
 .data : { *(.data*) *(.sdata*) }
 . = ALIGN(16);
 .payload : { payload_start = .; KEEP(*(.payload)) payload_end = .; }
 . = ALIGN(16);
 .bss (NOLOAD) : { *(.bss*) *(.sbss*) *(COMMON) }
 loader_end = .;
 /DISCARD/ : { *(.comment) *(.note*) *(.reginfo) *(.MIPS.abiflags) *(.pdr) }
 ASSERT(loader_end < 0xa6000000, "Relocated loader exceeds its 32 MiB region")
}
