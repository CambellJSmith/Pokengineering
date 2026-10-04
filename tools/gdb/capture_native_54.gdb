# Run from repository root. Create work/script_dispatch first.
# Source while stopped, then continue. Does not reset or continue automatically.
set pagination off
set logging file work/script_dispatch/dispatch_capture.log
set logging overwrite on
set logging redirect off
set logging enabled on
break *0x02065e60 if $r3 == 0x0210360c
commands
  silent
  printf "DISPATCH_VM=0x%08x\n", $r9
  printf "DISPATCH_WORD=0x%08x\n", *(unsigned int *)$sp
  info registers r0 r1 r2 r3 r7 r9 r10 r11 sp pc
  x/9wx $r9
  x/wx (*(unsigned int *)$r9)-4
  x/3wx $r0
  dump binary memory work/script_dispatch/capture_ram.bin 0x02000000 0x02400000
  set logging enabled off
  printf "Capture saved. Game remains paused before the handler.\n"
end
