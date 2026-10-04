
guardian_overlay_003.bin:     file format binary


Disassembly of section .data:

0210360c <.data+0x3354c>:
 210360c:	e92d4078 	push	{r3, r4, r5, r6, lr}
 2103610:	e24dd014 	sub	sp, sp, #20
 2103614:	e5904000 	ldr	r4, [r0]
 2103618:	e9900006 	ldmib	r0, {r1, r2}
 210361c:	e1a01801 	lsl	r1, r1, #16
 2103620:	e1a02802 	lsl	r2, r2, #16
 2103624:	e1a00004 	mov	r0, r4
 2103628:	e1a05821 	lsr	r5, r1, #16
 210362c:	e1a06822 	lsr	r6, r2, #16
 2103630:	ebfffb11 	bl	0x210227c
 2103634:	e3500000 	cmp	r0, #0
 2103638:	0a000011 	beq	0x2103684
 210363c:	e59011e8 	ldr	r1, [r0, #488]	@ 0x1e8
 2103640:	e3811302 	orr	r1, r1, #134217728	@ 0x8000000
 2103644:	e58011e8 	str	r1, [r0, #488]	@ 0x1e8
 2103648:	e5901000 	ldr	r1, [r0]
 210364c:	e591102c 	ldr	r1, [r1, #44]	@ 0x2c
 2103650:	e12fff31 	blx	r1
 2103654:	e590e000 	ldr	lr, [r0]
 2103658:	e590c004 	ldr	ip, [r0, #4]
 210365c:	e3a00000 	mov	r0, #0
 2103660:	e88d4001 	stm	sp, {r0, lr}
 2103664:	e59f0024 	ldr	r0, [pc, #36]	@ 0x2103690
 2103668:	e1a01005 	mov	r1, r5
 210366c:	e1a02004 	mov	r2, r4
 2103670:	e1a03006 	mov	r3, r6
 2103674:	e58de00c 	str	lr, [sp, #12]
 2103678:	e58dc010 	str	ip, [sp, #16]
 210367c:	e58dc008 	str	ip, [sp, #8]
 2103680:	eb004c3b 	bl	0x2116774
 2103684:	e3a00000 	mov	r0, #0
 2103688:	e28dd014 	add	sp, sp, #20
 210368c:	e8bd8078 	pop	{r3, r4, r5, r6, pc}
 2103690:	02126550 	andseq	r6, r2, #80, 10	@ 0x14000000
