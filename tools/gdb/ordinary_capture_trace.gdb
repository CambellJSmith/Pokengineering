# Ordinary (overworld) capture trace for Pokemon Ranger: Guardian Signs (B3RE)
#
# Uses ONLY breakpoints in resident ARM9 code, so the overlay loader can never
# overwrite them (the failure mode of the 2026-10-04 CCaptureScene sweep).
#
# Usage (DeSmuME started with --arm9gdb 3333, see README section 16):
#     gdb -q -x tools/gdb/ordinary_capture_trace.gdb
# then walk into a wild Pokemon on the field. Output is also logged to
# work/gdb/ordinary_capture_trace.log
#
# Expected static chain (docs/scene_system.md):
#   scene 1 CFieldScene (ov2) -> CFieldToCaptureState::Enter 0x020DF760
#   -> scene 0x29 CBossProduceScene (ov22, transition) -> scene 2 CCaptureScene (ov3)
#   -> scene 0x1B CCaptureToFieldScene (ARM9) -> scene 1

set architecture arm
set pagination off
set confirm off
shell mkdir -p work/gdb
set logging file work/gdb/ordinary_capture_trace.log
set logging overwrite on
set logging enabled on
target remote localhost:3333

# --- scene_overlay(sceneId): unload old / load new scene overlay ----------
break *0x0203D9BC
commands
  silent
  printf "[scene_overlay] sceneId=0x%02x lr=0x%08x\n", $r0, $lr
  continue
end

# --- FS_LoadOverlay(0, overlayId) ------------------------------------------
break *0x0207DF7C
commands
  silent
  printf "[FS_LoadOverlay] overlay=%d\n", $r1
  continue
end

# --- capture_setup_clear(setup=0x020B797C) --------------------------------
break *0x020418D4
commands
  silent
  printf "[CAP_CLEAR] setup=0x%08x lr=0x%08x\n", $r0, $lr
  continue
end

# --- capture_setup_add(setup, pokemonId, u32 a, u16 b, u16 c=[sp]) --------
# Called for EVERY capture target: wild contact (ov2 0x020D57D0, lr there)
# and script commands 0x0CA5/0x0CA6 (ov2 0x0211A5E4 / ARM9 0x020419E0).
break *0x02041998
commands
  silent
  printf "[CAP_ADD] dex=%d a=0x%08x b=%d c=%d lr=0x%08x\n", $r1, $r2, $r3, *(unsigned short*)$sp, $lr
  continue
end

# --- scene_create(sceneId): overlay for this scene is already resident -----
break *0x0203DEE0
commands
  silent
  printf "[scene_create] sceneId=0x%02x lr=0x%08x\n", $r0, $lr
  printf "  capture request 0x020B7AB8:\n"
  x/16hx 0x020B7AB8
  printf "  transition block 0x020B7A7C (request = +0x3C):\n"
  x/48hx 0x020B7A7C
  printf "  player/styler block 0x020B79E8:\n"
  x/16wx 0x020B79E8
  continue
end

# Overlay-specific breakpoints are armed from the scene_create stop above.
# To add them interactively once the matching scene is being created:
#   sceneId 1 (field, ov2):   break *0x020DF760   # CFieldToCaptureState::Enter
#                             break *0x020D34C8   # field applies pending state (r5)
#                             break *0x020D5780   # wild-contact capture setup
#                                                 #   (ctx+0x1F28 = touched CFieldWildPokemon)
#   sceneId 2 (capture, ov3): break *0x020D1D38   # CCaptureContext::Init
#                             break *0x020D05C4   # CCaptureScene state switch
# Remove them (delete N) before leaving that scene, because the next overlay
# reuses the same RAM.

continue
