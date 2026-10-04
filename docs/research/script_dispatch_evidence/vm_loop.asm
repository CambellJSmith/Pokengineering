
guardian_arm9_runtime.bin:     file format binary


Disassembly of section .data:

0206672c <.data+0x6672c>:
 206672c:	e5991004 	ldr	r1, [r9, #4]
 2066730:	e5990008 	ldr	r0, [r9, #8]
 2066734:	e1510000 	cmp	r1, r0
 2066738:	ca000002 	bgt	0x2066748
 206673c:	e59f0030 	ldr	r0, [pc, #48]	@ 0x2066774
 2066740:	e5991018 	ldr	r1, [r9, #24]
 2066744:	ebfffc93 	bl	0x2065998
 2066748:	e3580000 	cmp	r8, #0
 206674c:	e2488001 	sub	r8, r8, #1
 2066750:	1afffcdc 	bne	0x2065ac8
 2066754:	e3a00008 	mov	r0, #8
 2066758:	e8bd8ff8 	pop	{r3, r4, r5, r6, r7, r8, r9, sl, fp, pc}
 206675c:	020c20cc 	andeq	r2, ip, #204	@ 0xcc
 2066760:	020a9650 	andeq	r9, sl, #80, 12	@ 0x5000000
 2066764:	000003ff 	strdeq	r0, [r0], -pc	@ <UNPREDICTABLE>
 2066768:	020a9608 	andeq	r9, sl, #8, 12	@ 0x800000
 206676c:	020a9624 	andeq	r9, sl, #36, 12	@ 0x2400000
 2066770:	020a9674 	andeq	r9, sl, #116, 12	@ 0x7400000
 2066774:	020a968c 	andeq	r9, sl, #140, 12	@ 0x8c00000
