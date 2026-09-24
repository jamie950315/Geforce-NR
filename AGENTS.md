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
Arrival gaps and GFN stream loss still fail throughput gates; do not claim a
completed 120 FPS soak. Never treat the GFN VPN label as proof of exit-node routing.
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
away from GFN suspends rendering. Preferences and diagnostic output stay local.
HUD Mask is optional and off by default. Custom rectangle profiles support
selected GFN games and are bound to normalized window title plus exact geometry.
Only the built-in Cyberpunk preset requires Cyberpunk 2077 at 2560x1440.
Preserve unrelated active controllers and desktop shortcuts.
The panel and UI-probe scheduled tasks are on-demand only, with no autostart.
The app display name is `Geforce NR`, with `Geforce NR — HUD Mask Editor` and
`Geforce NR — Output` for its auxiliary windows. Desktop/task name migration
preserves the original Core/Lab paths and internal singleton identifiers.
The daily panel rechecks selected PID, process creation identity, title, and
geometry before launch; the child verifies the same contract. A resized game
stops any active daily run; diagnostic CLI runs retain their resize behavior.
One observed Cyberpunk exit kept the GFN HWND/title but changed geometry from
2560x1440 to 2578x1398 and showed Steam, so HWND identity alone does not mark
the end of a game session. A size change in daily mode now fails closed.
An actual selected-window close ends daily NR with `target_closed`/exit 0 and
no active controller. The panel clears stale target selections after either
`target_closed` or `target_resized` and requires a refresh before Start.
`install_daily_ui.ps1 -Check` is a read-only layout/task presence preflight;
runtime integrity is still checked by the launcher.
`remote_desktop.ps1` restores its neutral on-demand probe action after success
or failure and limits console output to GFN-related window metadata; full
screenshots and window inventory remain ignored local diagnostics.
`probe_daily_ui.ps1` also restores its neutral on-demand action after either
result; a failed probe must not leave a prior click or key as the saved action.

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
GDI window capture of the GFN and NR output HWNDs returned black; desktop
composition capture can include unrelated apps unless GFN is verified full-screen
and foreground before and after the bounded capture.
`compare_hud_pairs.py --all-frames` renders all three same-frame variants per
capture under ignored run output only after a passing `live-pair-result.json`;
the validator binds the complete run manifest hash, and comparison checks the
run target, mask, capture identities, and raw-file hashes before output.

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
