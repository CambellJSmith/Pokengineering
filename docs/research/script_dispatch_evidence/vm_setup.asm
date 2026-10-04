
guardian_arm9_runtime.bin:     file format binary


Disassembly of section .data:

02065930 <.data+0x65930>:
 2065930:	e59f2004 	ldr	r2, [pc, #4]	@ 0x206593c
 2065934:	e7821100 	str	r1, [r2, r0, lsl #2]
 2065938:	e12fff1e 	bx	lr
 206593c:	020c20cc 	andeq	r2, ip, #204	@ 0xcc
 2065940:	e3a03000 	mov	r3, #0
 2065944:	e5803004 	str	r3, [r0, #4]
 2065948:	e5803008 	str	r3, [r0, #8]
 206594c:	e580300c 	str	r3, [r0, #12]
 2065950:	e5803010 	str	r3, [r0, #16]
 2065954:	e5803014 	str	r3, [r0, #20]
 2065958:	e5803020 	str	r3, [r0, #32]
 206595c:	e5802018 	str	r2, [r0, #24]
 2065960:	e59fc004 	ldr	ip, [pc, #4]	@ 0x206596c
 2065964:	e580101c 	str	r1, [r0, #28]
 2065968:	e12fff1c 	bx	ip
 206596c:	02065970 	andeq	r5, r6, #112, 18	@ 0x1c0000
 2065970:	e3a03000 	mov	r3, #0
 2065974:	e5803000 	str	r3, [r0]
 2065978:	e590201c 	ldr	r2, [r0, #28]
 206597c:	e5901018 	ldr	r1, [r0, #24]
 2065980:	e0821101 	add	r1, r2, r1, lsl #2
 2065984:	e5801004 	str	r1, [r0, #4]
 2065988:	e590101c 	ldr	r1, [r0, #28]
 206598c:	e5801008 	str	r1, [r0, #8]
 2065990:	e5803020 	str	r3, [r0, #32]
 2065994:	e12fff1e 	bx	lr
