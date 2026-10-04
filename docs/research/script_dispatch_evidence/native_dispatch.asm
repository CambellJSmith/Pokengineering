
guardian_arm9_runtime.bin:     file format binary


Disassembly of section .data:

02065e14 <.data+0x65e14>:
 2065e14:	e1dd00f2 	ldrsh	r0, [sp, #2]
 2065e18:	e5dd7001 	ldrb	r7, [sp, #1]
 2065e1c:	e000200b 	and	r2, r0, fp
 2065e20:	e1a00540 	asr	r0, r0, #10
 2065e24:	e200103f 	and	r1, r0, #63	@ 0x3f
 2065e28:	e79a0101 	ldr	r0, [sl, r1, lsl #2]
 2065e2c:	e3500000 	cmp	r0, #0
 2065e30:	1a000002 	bne	0x2065e40
 2065e34:	e59f092c 	ldr	r0, [pc, #2348]	@ 0x2066768
 2065e38:	ebfffed6 	bl	0x2065998
 2065e3c:	ea000009 	b	0x2065e68
 2065e40:	e7903102 	ldr	r3, [r0, r2, lsl #2]
 2065e44:	e3530000 	cmp	r3, #0
 2065e48:	1a000002 	bne	0x2065e58
 2065e4c:	e59f0918 	ldr	r0, [pc, #2328]	@ 0x206676c
 2065e50:	ebfffed0 	bl	0x2065998
 2065e54:	ea000003 	b	0x2065e68
 2065e58:	e5990004 	ldr	r0, [r9, #4]
 2065e5c:	e1a01007 	mov	r1, r7
 2065e60:	e12fff33 	blx	r3
 2065e64:	e5890010 	str	r0, [r9, #16]
 2065e68:	e5990000 	ldr	r0, [r9]
 2065e6c:	e3500000 	cmp	r0, #0
 2065e70:	0a00022d 	beq	0x206672c
 2065e74:	e5990004 	ldr	r0, [r9, #4]
 2065e78:	e2888001 	add	r8, r8, #1
 2065e7c:	e0800107 	add	r0, r0, r7, lsl #2
 2065e80:	e5890004 	str	r0, [r9, #4]
 2065e84:	ea000228 	b	0x206672c
