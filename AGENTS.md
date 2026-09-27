# Geforce NR live validation

Public source repository: https://github.com/jamie950315/Geforce-NR .
The public branch is `main`; local `main` tracks `origin/main`. Historical local
commits contain private contact information. Do not publish recovered history
or push all branches or tags. Use the configured GitHub noreply identity for
public commits. Public distribution is source-only and does not include Core/Lab
dependencies or NVIDIA runtime/model binaries; keep the README scope and
artifact exclusions intact.

This workspace holds an isolated daily UI and validation helpers for the Windows deployment.
Target: CyberTitanV3, Windows, RTX 4070 SUPER. SSH alias `ctps` requires
`-o RemoteCommand=none -o RequestTTY=no` for batch commands.

Preserve existing Core, Lab, runtime binaries, and launch defaults. Use a separate
run directory. Do not claim 120 FPS acceptance from requested FPS or GPU pass time.
Bind measurements to actual WGC geometry, source identity, binaries, and masks.
Do not commit screenshots, game/account data, runtime output, or credentials.

Native runs require Windows interactive session 1. SSH session 0 has a different
display/adapter view and fails NGX initialization on this host. Use the on-demand
interactive scheduled launcher. The isolated launcher defaults to `native-repaired`
with the timestamp-contract fix; original Core/Lab/Guard binaries remain intact.
The on-demand diagnostic launcher restores its saved scheduled action to an
inert Python command after dispatch; the running task continues unchanged.
`task_control.ps1` serializes task changes across Windows sessions and tracks
the exact dispatched instance. Queued tasks are preserved; probe JSON requires
the current request ID. Never substitute a previous result or stop a different
instance during cleanup.
Arrival gaps and GFN stream loss still fail throughput gates; do not claim a
completed 120 FPS soak. Never treat the GFN VPN label as proof of exit-node routing.
This restriction concerns live GFN acceptance. A separate 600-second animated
HDR replay passed controlled NR720/1440p-output capacity gates at 119.999 FPS,
with zero dropped PresentMon events on the identified output swap chain.
It is not live PS5/GFN, native-1440p NR, GPU-bound local-game, or physical scanout
acceptance. NR1080 reached only 97.67 FPS in the controlled short comparison.
The runtime was not patched. Do not sweep preset/PerfQuality strings as assumed
speed modes: static inspection of the deployed 310.8.SF.0 found one shipping
weight descriptor and fixed ScalingRatio=1.0 in the inspected paths.
Reject all readback/profiler runs from timing qualification; use the manifest's
`hdr_proof`, `live_pair`, and `timing_evidence` fields.
The 25 Mbps experiment is restored to 100 Mbps. See README.md for measured limits.

After the user's A1-JP switch, observed ping is 74-75 ms, but new bypass/NR/Guard
short runs still have 95-106 ms gaps and fail stable 120. Preserve that route.
The opt-in `--live-pair-worker` records three same-command-list source/pre-HUD/
post-HUD frames with live WGC and NVOFA. Its pixel checks pass; its synchronous
readback runs are visual diagnostics only and are rejected by the timing evaluator.
`native-repaired` remains the default; never promote `native-live-pair` for speed.

The user-selected mainline defaults are NR720 + flow1280/G2/Fast in the isolated
launcher. Resolution tuning still exposes NR 720/900/1080 and explicit flow
width/grid/preset overrides. Five 60-second live samples support this 120-oriented
configuration; NR900/1080 local processing p95 is 8.88/10.48 ms. G2 Medium at NR720
is 7.83 ms versus Fast 7.07 ms. All output 2560x1440 via residual composition.
The flow-width1280 limit is a software allow-list, not a measured hardware cap.
Do not present offline warp error as live perceptual quality or promote a new
default without the corresponding configuration decision.

The Windows desktop shortcut `Geforce NR` opens `daily_ui.py` using the
existing Core Python/Tk runtime. `daily_backend.py` owns only its own subprocess
session; stop is bound to a unique owner token and the run/controller records,
not the Windows venv bootstrap PID. Daily runs use `--daily --seconds 0`, disable
per-frame trace logging, and stop if the owning UI PID/creation identity dies.
Ctrl+Alt+F9 raises the owning panel. Normal close waits for safe stop; switching
away from the selected window suspends rendering, including another window in
the same process. Preferences and diagnostic output stay local.
HUD Mask is optional and off by default. Custom rectangle profiles support
selected application windows and are bound to normalized window title plus exact geometry.
Only the built-in Cyberpunk preset requires Cyberpunk 2077 at 2560x1440.
Preserve unrelated active controllers and desktop shortcuts.
The panel and UI-probe scheduled tasks are on-demand only, with no autostart.
The app display name is `Geforce NR`, with `Geforce NR — HUD Mask Editor` and
`Geforce NR — Output` for its auxiliary windows. Desktop/task name migration
preserves the original Core/Lab paths and internal singleton identifiers.
The daily panel rechecks selected PID, process creation identity, title, and
geometry before launch; the child verifies the same contract. A resized game
stops any active daily run; diagnostic CLI runs retain their resize behavior.
Daily selection uses `application_windows.py` for visible, restored top-level
application windows with verifiable process identity. The panel requires explicit
selection and shows executable/title/size/PID. Exclude shell, cloaked, tool, tiny,
and NR-owned windows. The daily child uses the same enumerator; diagnostic CLI
selection and GFN-specific capture tools still use their original restrictions.
Do not relax those diagnostic capture guards when extending daily selection.
Window eligibility does not guarantee WGC/DRM compatibility.
HDR output is opt-in (`hdr` preference / `--hdr`) and uses a separately staged
`native-hdr`; `native-repaired` remains the SDR default. `stage_hdr.py` patches
only a copied, attested repaired source tree. Do not edit Core/Lab or overwrite
existing builds. `hdr_support.py` checks worker/runtime hashes and the selected
monitor's Windows HDR state before launch. The worker reads `GFN_NR_HDR`, not
Core's forced-off `NS_HDR`; it requires FP16 WGC and scRGB presentation and fails
closed when Windows HDR is lost. NR/flow operate on SDR proxies; bounded linear
residual composition preserves the original HDR anchor, including exact bypass
and full-mask cores. The mask preview and ordinary PPM exports remain SDR.
Only `color.json` after successful HDR presentation confirms the active path.
`stage_hdr.py --mapping color-preserving --queued` stages an opt-in queued
HDR tail; `--queued-hdr` selects it only for color-preserving HDR. The final
present fence retires motion/NR/composition; FG and synchronous special paths
are not made asynchronous. `stage_capture_queue.py` separately stages
`native-hdr-color-capture-queued` as the preserved parent for the motion repair.
`stage_motion_repair.py` stages `native-hdr-color-motion-repaired`; additional
`--capture-queued-hdr` and the panel's combined queue option select this repaired
build. The loader requires `motion_repaired=true` and never falls back to the parent.
Swizzle and gray own different descriptor heaps, gray's later fence retires both,
and the D3D11 source-copy wait remains mandatory. Neither changes daily defaults.
The panel's `hdr_queued` boolean selects both optimizations together. It defaults
off and requires HDR plus Color-preserving; switching to SDR/Legacy clears it.
Existing preferences migrate with queue off and a local backup. Start preflight
attests the combined build before saving preferences; no old-worker fallback.
The repaired motion path preserves decoded subpixel vectors instead of applying
the discontinuous 0.5-NR-pixel deadzone; reset still emits zero motion. Gray history
and pre-allocation validation share the worker's bounded 7680x4320 capacity,
so a diagnostic 1600x900 flow frame no longer causes a reset every frame.
The panel/CLI flow allow-list remains unchanged (maximum 1280); higher flow is not
promoted as a 120-FPS setting. Legacy/SDR workers are preserved, not patched in place.
The pre-motion-repair combined variant passed a 600-second animated HDR replay at NR900,
flow1280/G2/Fast and 2560x1440 output: 119.87 fresh FPS, minimum 118/full second,
zero PresentMon dropped frames/ETW gaps. This is higher-resolution processing
capacity, not live-stream acceptance or proof of facial-noise removal.
The motion-repaired build's separate 45-second NR900 replay reached 119.43 fresh
FPS (minimum 117/full second); do not relabel the parent's 600-second soak as a
new soak of this build. Matched face diagnostics show similar static variation,
lower slow-translation residual variation and a slight fast-translation increase,
not universal denoising. Existing settings and NR/flow resolution defaults remain unchanged.
`stage_nr_precision.py` is a file-fed-only FP16 NR work-texture experiment, not
an internal model precision switch or a verified facial-noise fix.
`--hdr-proof` is a one-time same-frame FP16/proxy readback for
`validate_hdr_proof.py`, never timing or physical-display luminance evidence.
`hdr_mapping` selects `legacy` (`native-hdr`) or `color-preserving`
(`native-hdr-color`). Existing preferences migrate to Legacy; new/recommended
preferences choose Color-preserving with HDR still off. Stage the new build with
`stage_hdr.py --mapping color-preserving`; preserve both binaries. It compresses
negative RGB toward neutral with positive luminance preserved, and scales large
NR edits uniformly rather than clipping channels independently. It retains the
existing highlight curve and does not infer engine exposure from screenshots.
Native proof metadata binds the mapping; the new validator checks proxy encoding
as well as FP16 composition. Do not describe this as a universal perceptual-quality
or temporal-stability improvement.
One observed Cyberpunk exit kept the GFN HWND/title but changed geometry from
2560x1440 to 2578x1398 and showed Steam, so HWND identity alone does not mark
the end of a game session. A size change in daily mode now fails closed.
An actual selected-window close ends daily NR with `target_closed`/exit 0 and
no active controller. The panel clears stale target selections after either
`target_closed` or `target_resized` and requires a refresh before Start.
`install_daily_ui.ps1 -Check` is a read-only layout/task presence preflight;
runtime integrity is still checked by the launcher.
`remote_desktop.ps1` restores its neutral on-demand probe action after success
or failure. `desktop_probe.py` binds GFN metadata, input, and screenshots to a
GFN executable and captures a fresh screenshot only with a foreground GFN
window covering the screen. It crops below the GFN window when a taskbar is
exposed; check `screenshot_captured` before using the ignored `desktop.png`.
Clicks must hit the same GFN top-level window. Captures and editor previews
recheck foreground and target identity/geometry before saving or displaying pixels.
The UI probe does not capture a closed or unfocused panel; always check its
`screenshot_captured` result before reading an older `daily-probe.png`.
`probe_daily_ui.ps1` also restores its neutral on-demand action after either
result; a failed probe must not leave a prior click or key as the saved action.
The panel-hotkey probe requires a GFN process window other than the client home
window.

HUD-impact comparison uses same-command-list source/pre-HUD/post-HUD readbacks,
not separate-time screenshots. Nine current G2/NR720 samples show tone/contrast
changes but no severe observed legibility failure; do not generalize to every
game or long-motion sequence. Color-selected ROI metrics include possible
background and are not a HUD detector or damage percentage. No adaptive mode
is deployed. The user selected mask-free NR as the daily default, with manual
mask selection available when desired.
The fixed Cyberpunk mask can expose visible rectangular tone boundaries and
leave menu/caption text outside its protected regions. Three inspected gameplay
frames are nearly static and do not establish moving-edge or ghosting quality.
A newer three-pair Cyberpunk sample includes NPC movement and passes protected/
outside error 0 and feather error at most 1/255; sparse pairs still do not
establish temporal ghosting quality.
A separate three-second, 85-frame composed-output diagnostic with unmasked
NR720/flow1280/G2/Fast shows no severe ghost trails in inspected NPC-motion
frames; it is lossy, source-unpaired, and unsuitable for timing acceptance or
broad perceptual claims. Keep this game video only in ignored local run output.
Two PC Building Simulator 2 NR-only runs (20 and 30 seconds) confirm NR,
hardware flow, and 2560x1440 WGC/output with 1280x720 processing, but have
only about 59 host exchanges/s. The session preflight reported 9.7% packet loss
and 93 ms latency. A separate three-second, 79-frame view/object-motion composition
clip has visible blockiness whose source is unresolved; keep it in ignored run
output and do not use it for timing or general image-quality acceptance.
The right-button interaction picked up the case (the placement prompt is visible);
this sequence is not a camera-only test.
GDI window capture of the GFN and NR output HWNDs returned black; desktop
composition capture can include unrelated apps unless GFN is verified full-screen
and foreground before and after the bounded capture.
`capture_game.py` also requires a GFN executable and a full-screen game window
before recording each raw desktop sample.
`compare_hud_pairs.py --all-frames` renders all three same-frame variants per
capture under ignored run output only after a passing `live-pair-result.json`;
the validator binds the complete run manifest hash, and comparison checks the
run target, mask, capture identities, and raw-file hashes before output.
The validator requires strictly typed, positive capture/fence identities and
distinct frame files. Render comparisons from the verified byte snapshots;
re-reading changed files after hash validation invalidates that guarantee.

`mask_editor.py` captures an in-memory, visible-window SDR preview only while
renderers are stopped. Integer subsampling uses exact source-pixel coordinates.
`mask_profiles.py` validates up to 64 rectangles, saves JSON under ignored
`masks/`, and emits immutable content-addressed HGM files with 4px outer feather.
Empty-save clears the selected profile and disables masking. Cancel confirms
before discarding unsaved changes. Geometry/title mismatch never silently reuses another profile.
Legacy preferences are backed up and migrated once to mask-off; user opt-in
choices persist thereafter. Never commit user profiles or captured previews.

The editor supports exact source-pixel coordinate edits with validation and Undo.
Pending valid fields apply on save/selection switch/new drag; invalid input stays
visible and blocks those actions. Text-field Delete/Ctrl+Z never affect regions.
Malformed profiles fail closed without overwrite. The main panel shows mask
readiness/count and prevents enabled-empty/invalid Start while keeping NR-only
usable. Preferences are committed by backend start only after preflight succeeds.
