# Freestanding 32-bit Linux fixture executing the pinned EXE's RNG instructions.
# Build/run only from repository root; no Wine or libc is involved.
.section .text
.global _start, capture_ready
_start:
    mov $123, %eax
    call seed
capture_ready:
    mov $1000, %ebp
draw_loop:
    call next_rand
    dec %ebp
    jnz draw_loop
    mov $1, %eax
    xor %ebx, %ebx
    int $0x80

.section .engine,"ax"
seed:
    .incbin "runtime/deluxe-modded/BookwormAdventures.exe", 0x1ab440, 82
    .org 0x70
next_rand:
    .incbin "runtime/deluxe-modded/BookwormAdventures.exe", 0x1ab4b0, 257

.section .twist,"a"
    .long 0, 0x9908b0df
.section .rng,"aw",@nobits
    .zero 2500
