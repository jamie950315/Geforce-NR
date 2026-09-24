# Geforce-NR

Experimental Windows controls and validation helpers for local Neural Rendering
on a GeForce NOW window, with optional, user-drawn HUD protection.

## Public repository scope

This is a deployment-specific source repository, **not a standalone installer**.
The daily UI and validation scripts depend on existing adjacent Core/Lab projects,
their Python environments, and a separately provisioned native worker and NR
runtime. Those projects and NVIDIA runtime/model binaries are not bundled here.
Cloning this repository alone does not provide a working NR engine.

The deployment examples below describe the tested author's environment. Review
the hard-coded Windows paths and scheduled-task names before using these helpers
on another machine. Screenshots, game/account data, runtime logs, local settings,
user masks, credentials, and generated binaries are excluded from this repository.
This project is unofficial and is not affiliated with or endorsed by NVIDIA.

Before installing the daily desktop shortcut, run the read-only layout check
from the deployment directory:

```powershell
powershell.exe -NoProfile -File .\install_daily_ui.ps1 -Check
```

It lists missing adjacent Core/Lab code, the repaired worker/runtime, or the
on-demand interactive launcher task before changing a shortcut or task. Passing
this presence check does not replace the launcher's binary integrity checks or
prove that a GFN session is available. The diagnostic `launch_run.ps1` and
`remote_desktop.ps1` derive their script paths from their deployment directory;
the adjacent dependencies and scheduled tasks are still required.
The desktop probe restores its neutral on-demand task action even when a probe
fails, and records only GFN-related window metadata. It captures a fresh desktop
image only while a GFN window covers the foreground screen; the JSON result
reports `screenshot_captured`, since an older ignored `desktop.png` may remain.

Windows deployment: `C:\Users\jamie\dev\gfn-codex-live-20260921`.
These helpers use a minimally repaired HUD Guard and the existing Lab controller.
They do not replace Core/Lab binaries or promote a production default.

## Daily desktop app

Open **Geforce NR** from the Windows desktop. Start the GFN game first,
refresh the game list if needed, and click **Start**. HUD Mask is off by default:
NR 1280x720 with NVOFA 1280x720 / G2 / Fast and full 2560x1440 residual output
at the measured source size. **Stop safely** ends only this panel's owned session.

The native panel provides NR and bypass modes plus an optional HUD Mask checkbox; NR height, flow
width, grid, and preset controls; **Save preferences**, **Restore recommended**,
and **Open run folder**. Stop before changing processing settings. Preferences
are stored locally in `daily-settings.json`. No browser or web server is used.

Choose **Draw / edit custom** to capture the selected visible game window and
drag rectangular protection regions. The editor supports selection, deletion,
Undo, Clear, Cancel, and **Save & use** (Ctrl+S). Saving nonempty regions selects
the custom mask and enables it; saving an empty profile disables the mask.
The original Cyberpunk 2077 1440p preset remains a separate read-only option.
The panel reports saved-region count and profile readiness. Enabling an empty
or invalid mask disables Start; leaving the mask off still permits NR.
If the selected game window changes identity or size while the panel is open,
refresh and select it again. Daily launch binds the selected PID, creation
identity, title, and geometry; it cannot silently follow a reused HWND. An
active daily run stops if the game geometry changes, including when HUD Mask
is off. Refresh and select the new size before restarting. Diagnostic CLI runs
retain their separate resize behavior. In one observed Cyberpunk exit, the GFN
window kept its identity while changing from 2560x1440 to 2578x1398 and
showing Steam; this size check prevents daily NR from continuing on that page.
When a daily run ends because the selected GFN window closes or changes size,
the panel clears the stale selection and requires **Refresh** before Start.

Select a rectangle to edit `x0`, `y0`, `x1`, and `y1` in source pixels, then use
**Apply selected**. The lower-right edges are exclusive. This permits single-pixel
boundary adjustments even when the preview is reduced. Valid pending coordinates
are applied before saving, switching selection, or drawing another region;
invalid coordinates are retained with an error and cannot be saved. Delete and
Ctrl+Z in a numeric field do not delete or undo whole regions.

Cancel, Esc, and window close ask before discarding unsaved changes, defaulting
to keeping the editor open. Undoing back to the loaded profile clears the dirty
state. Corrupt saved profiles stop the editor from opening rather than silently
becoming an empty, overwriteable mask.
The panel measures its Windows frame decoration and centers its initial size
inside the usable desktop, preventing a taller layout from opening below the taskbar.

Custom regions are stored per normalized game-window title and exact resolution
under `masks/`. Reopening the game does not require redrawing when these match.
Changing resolution requires a matching profile; old masks are never stretched.
Stop processing before editing, keep the entire game visible, and avoid other
overlays during capture. The preview is captured in memory, not saved as a
screenshot. Rectangle cores preserve source pixels with a four-pixel outer
feather; background inside a rectangle is preserved too. This is manual rectangle
selection, not freehand segmentation, automatic detection, or moving-HUD tracking.
HDR is not supported. Re-edit if a game's HUD layout changes.

Existing pre-mask-selector preferences migrate once to mask-off while preserving
processing settings, with a local `daily-settings-before-optional-mask.json`
backup. Subsequent explicit checkbox choices persist. Generated HGM files are
content-addressed, so editing a profile does not overwrite a running mask.

Daily sessions run until stopped, the target closes, or an engine safety check
ends them; the diagnostic 60-second timer is not used. Switching to another app
(including the panel) suspends the overlay. Return to the game to resume.
Ctrl+Alt+F8 toggles NR temporarily, Ctrl+Alt+F9 opens this panel, and Ctrl+Alt+Q
stops processing. Closing an active panel asks to stop, then waits for cleanup.
If the UI process exits unexpectedly, the controller detects the lost owner
and shuts down the GPU worker.

The panel uses the existing Windows Python/Tk runtime. `install_daily_ui.ps1`
creates the desktop shortcut and an on-demand interactive task named
`Geforce-NR-Panel`; it installs no autostart trigger. Existing Core/Lab
entry points and binaries remain intact. `daily_ui_probe.py` and
`probe_daily_ui.ps1` are bounded development-only UI verification helpers.
The UI probe restores its neutral on-demand task action after success or failure.

## Current acceptance

After the user-reported A1-JP route switch, the observed GFN ping is 74–75 ms.
New 60-second runs retain the same repaired worker and 2560x1440 WGC geometry:

| Mode | Fresh surfaces/s | Maximum Present gap | Minimum full second |
| --- | ---: | ---: | ---: |
| Bypass before | 119.47 | 100.15 ms | 108 |
| Guard 720p | 118.57 | 99.58 ms | 106 |
| NR 720p, no mask | 118.55 | 106.27 ms | 103 |
| Bypass after | 119.44 | 94.70 ms | 110 |

Guard source-to-CPU-Present p95/p99 is 5.30/8.53 ms, with no invalid or
future-at-Present timestamps. All four runs still fail the stable-120 gates.
The before/after source-reference difference is 0.03 FPS.
Lower network ping does not eliminate the observed pipeline gaps. These samples
do not identify the cause of those gaps or qualify a 600-second soak.

The isolated launcher defaults to `native-repaired`, which fixes premature
rejection of WGC compositor timestamps. `--original-worker` explicitly selects
the historical worker for comparison. Positive, strictly increasing timestamps
are retained independent of acquisition ordering; signed Present deltas distinguish
`valid`, `future-at-present`, and `invalid` without clamping or substituting latency.

The earlier clean repaired 60-second 720p Guard run records 6,537 steady frames, zero invalid
or future-at-Present timestamps, source-to-CPU-Present p95 4.05 ms / p99 5.81 ms.
Fresh throughput is 116.96 FPS; a 106.02 ms source gap still fails stable 120.
The timing fix does not claim to repair stream loss or increase throughput.

Historical pre-repair measurements:

| Mode | Fresh WGC surfaces/s |
| --- | ---: |
| Bypass before | 117.69 |
| NR 900p | 111.54 |
| Guard 900p | 109.76 |
| Guard 720p | 115.86 |
| Bypass after | 116.97 |

Capture callback instrumentation confirms approximately 100 ms arrival gaps.
Quiet, transparent-overlay, and suspended periodic-telemetry controls do not remove
them. GFN itself records increasing lost-frame/packet counters and 245–250 ms ping.
A temporary 25 Mbps cap does not remove gaps and is restored to 100 Mbps.
These observations do not identify the particular ISP, router, or server fault.
No 600-second qualification or stable-120 production promotion is claimed.

Twelve actual-game screenshots pass paired file-fed composition validation:
protected maximum error 0, unchanged pixels outside the mask, feather-reference
maximum error 1/255. This test uses identical zero-motion history and is not a
live NVOFA same-frame proof. A separate opt-in diagnostic now verifies three actual
live WGC/NVOFA frames in `a1jp-live-pair720`: source, pre-HUD, and post-HUD copies
share each frame's GPU command list and submission fence. Protected error is 0,
outside-mask error is 0, and feather-reference error is at most 1/255. The NR
pre-HUD pixels differ from the source, so this is not a bypass-only equality test.
This is a three-frame composition proof, not broad perceptual or motion coverage.
Moving world-space labels, arbitrary menus, resolution
changes, and HDR are outside the fixed mask contract.

## Run and stop

Run in the existing Windows interactive desktop, not an SSH session's noninteractive
desktop. The `GFN-Codex-Live-Run-20260921` scheduled task has no trigger; it is an
on-demand interactive launcher. Remote batch commands use `ctps` with
`-o RemoteCommand=none -o RequestTTY=no`.
`launch_run.ps1` restores the task's stored action to an inert Python command
after dispatch, without interrupting the current run. Its dispatch message is
not evidence of a successful run; inspect the run outcome.

Enumerate current game HWNDs from the interactive desktop:

```powershell
& C:\Users\jamie\dev\gfn-nr-core\.venv\Scripts\python.exe C:\Users\jamie\dev\gfn-hud-live-20260921-7b03\live_hud.py --list
```

The tested HWND is historical; replace it after restarting a session. Each run name
must be unique. The exact tested launch form is:

```powershell
powershell.exe -NoProfile -File C:\Users\jamie\dev\gfn-codex-live-20260921\launch_run.ps1 -RunArgs "--name my-guard-run --hwnd 855446 --mode guard --mask C:\Users\jamie\dev\gfn-codex-live-20260921\cyberpunk-1440p.hgm --seconds 60 --height 720"
```

```powershell
& C:\Users\jamie\dev\gfn-nr-core\.venv\Scripts\python.exe C:\Users\jamie\dev\gfn-codex-live-20260921\stop_run.py
```

Stop is verified as exit 0 / `stop_requested`, with no remaining worker. Timed runs
stop automatically. Ctrl+Alt+Q is inherited from the controller. Ctrl+Alt+F9 opens
the panel only for daily sessions owned by the UI; it is not a panel entry point
for standalone diagnostic CLI runs.

`runs/<name>` contains the manifest, exact binary/dependency/mask hashes, WGC
geometry, raw native logs, metrics, resources, outcome, and timing assessment.
The final mask SHA-256 is
`2db477e1d2925abdf47fc206d84043d1d58fcb1f1ee1b3f69fc4ddf9661b8b60`.

The interactive display is 2560x1440 at 180 Hz. GFN's expanded overlay confirms
5120x2880 at 120 FPS, H.265 10-bit YUV 4:4:4, HDR off, Japan NP-TYO-01.
The bitrate cap is restored to 100 Mbps. The VPN label alone is not a routing
diagnosis: the earlier control-connection inspection used Ethernet with no
Tailscale exit node; that snapshot predates the user's A1-JP switch. The current
validation preserves the user's route. No model, display mode, or driver is changed.

## Local checks

```sh
rtk proxy python3 -m unittest test_evaluate_run -v
rtk proxy python3 -m unittest test_daily_backend -v
rtk proxy python3 -m unittest test_daily_ui -v
rtk proxy python3 -m unittest test_mask_profiles test_mask_editor -v
rtk proxy c++ -std=c++17 -Wall -Wextra -Wpedantic -Werror test_native_timing.cpp -o /tmp/gfn-native-timing-test
rtk proxy /tmp/gfn-native-timing-test
```

Screenshots, game data, binaries, and evidence are excluded from Git. Historical
offline results remain attached to their original build and scope.

`stage_repaired.py` builds the minimal repair from the original Guard source;
the patched code changes timing only, not HUD, NR, capture, or presentation logic.
`stage_probe.py` and `stage_fixed.py` reproduce diagnostic builds, not deployment
defaults. Opacity/sampler experiments are opt-in and not adopted as fixes.

## NVOFA and NR resolution controls

The isolated launcher exposes `--height 720|900|1080`,
`--flow-width 320|640|960|1280`, `--flow-grid 2|4`, and
`--flow-preset fast|medium|slow`. The selected mainline defaults are NR height 720,
flow width 1280, grid 2, Fast. These are deployment allow-lists, not statements
of the GPU's maximum optical-flow resolution or every supported hardware grid.

For the measured 2560x1440 WGC source, flow width 1280 gives 1280x720 luminance
input. Grid 4 produces a 320x180 vector lattice; grid 2 produces 640x360.
The lattice is bilinearly reconstructed to the NR work size with vector
magnitudes scaled by work/flow dimensions. Increasing NR resolution alone does
not increase the number of independently estimated optical-flow vectors.

NR height 720/900/1080 gives 1280x720, 1600x900, or 1920x1080 color processing.
All three output 2560x1440: the original full-resolution source is retained and
the upsampled NR residual is added before HUD protection. This is not a simple
upscale of a low-resolution NR image. The original GFN stream resolution is
distinct from the actual WGC surface fed into this pipeline.

Five 60-second Guard runs on RTX 4070 SUPER use the same repaired worker,
1280x720 flow input, mask, source HWND, and appearance. Steady profile results:

| NR work | NVOFA | Fresh output FPS | NR GPU mean (ms) | Acquired-to-Present p95 (ms) |
| --- | --- | ---: | ---: | ---: |
| 1280x720 | G4 Fast | 118.64 | 4.14 | 6.84 |
| 1280x720 | G2 Fast | 118.19 | 4.03 | 7.07 |
| 1280x720 | G2 Medium | 118.32 | 4.05 | 7.83 |
| 1600x900 | G2 Fast | 115.41 | 5.35 | 8.88 |
| 1920x1080 | G2 Fast | 97.79 | 7.09 | 10.48 |

GPU means are means of native report-window means, not end-to-end latency.
Acquired-to-Present includes local copy/flow/NR/presentation work but excludes
waiting for a new capture and physical scanout. FPS still depends on the source.
These sequential short samples are not a stable-120 qualification or paired
perceptual quality comparison. All five confirm hardware flow, NR, correct
geometry, and exit 0; no original Core/Lab worker, runtime, or launch default is replaced.

The user-selected mainline is `--height 720 --flow-width 1280 --flow-grid 2 --flow-preset fast`;
these arguments can be omitted because they are now the isolated launcher's defaults.
At the measured 2560x1440 source geometry, NVOFA and NR both use 1280x720,
with 2560x1440 residual/HUD output. This configuration selection is not a
stable-120 qualification or a replacement of the original Core/Lab entry points.
G2 Medium uses more of the 8.33 ms frame budget; its earlier
offline warp-error advantage is not proof of better live NR perceptual quality.
Higher NR budgets do not automatically yield a sharper final 1440p image.

## Opt-in live same-frame pixel proof

`stage_live_pair.py` builds `native-live-pair` from the existing `native-repaired`
source and build command. It refuses to replace an existing diagnostic build.
For a unique short Guard run, add `--live-pair-worker` to the launch arguments
above and use `--seconds 10`. The launcher creates `runs/<name>/live-pairs` and
samples frame indexes 30, 60, and 90. Guard mode and a maximum 30-second duration
are mandatory. The ordinary launcher still selects `native-repaired`.

Validate the captured files with the existing Windows Python environment:

```powershell
python validate_live_pairs.py runs/<name>/live-pairs --mask cyberpunk-1440p.hgm --output runs/<name>/live-pair-result.json
```

The validator requires three fresh WGC/NVOFA identities, one HWND, increasing
capture/source/fence identifiers, matching geometry, and exact/intermediate/zero
mask regions. The GPU readbacks perturb sampled frames: `evaluate_run.py` rejects
these runs as timing qualification. Evidence remains local and excluded from Git.

## Unprotected HUD comparison

`compare_hud_pairs.py` renders source / pre-HUD NR / post-HUD Guard crops from
three verified fresh WGC/NVOFA pairs. It requires NumPy and Pillow, used only by
this offline analysis helper, not the desktop app. `--regions <json>` accepts a
mapping from safe region names to `[left, top, right, bottom]` pixel coordinates.
The helper rejects empty captures and non-paired metadata. Output is written
inside the run's `hud-comparison` directory; color subsets are measurement
proxies, not automatic HUD detection or perceptual-quality scores.
Run `validate_live_pairs.py` with `--output runs/<name>/live-pair-result.json`
first. The comparison helper requires that passing result and checks the run's
target HWND, mask digest, capture identities, and current raw-frame hashes
against it before writing images or metrics. Validation also binds the complete
run manifest hash, so changed settings or worker records require revalidation.
Use the existing overlay Python environment for NumPy and Pillow. Add
`--all-frames` to render each of the three same-frame source / NR / Guard PNGs
under `hud-comparison/frames/`. The tool rejects reused capture identities,
changed HWND/geometry, and incomplete frame files before writing review output.
Keep rendered game images and metrics under the ignored local `runs/` directory.

Nine mainline G2/Fast/NR720 samples across gameplay, startup prompt, and main
menu show visible HUD tone/contrast changes without a mask, but no severe
legibility failure in the inspected text/icons. Protected gameplay regions
remain exact. Main-menu text is outside the fixed mask and is not protected.
Reviewing the first gameplay, menu, and caption pairs found visible rectangular
tone boundaries from the fixed Cyberpunk mask. The three inspected gameplay
frames are nearly static, so they cannot establish moving-edge or ghosting
quality.
A later three-pair Cyberpunk gameplay sample includes visible NPC movement.
Its same-frame pixel validation passes: protected and outside-mask maximum
errors are 0, and feather error is at most 1/255. The reviewed stills do not
show severe HUD legibility loss, but the fixed mask tone boundary remains
visible. Three sparse frames cannot establish temporal ghosting quality.
An additional three-second, 85-frame composed-output diagnostic at 2560x1440
shows NPC motion with unmasked NR720 / flow1280 / G2 / Fast. The inspected
consecutive frames show no severe ghost trails or HUD legibility failure.
This is one lossy, source-unpaired scene capture; recording overhead and sparse
inspection prevent timing or general perceptual-quality claims.
In a separate PC Building Simulator 2 session, 20- and 30-second NR-only runs
both ended normally with confirmed NR and hardware optical flow. WGC was
2560x1440, NR and flow were 1280x720, and output was 2560x1440; host exchange
rates were 58.77 and 58.58/s. The GFN preflight for this session measured more
than 100 Mbps, 9.7% packet loss, and 93 ms latency. A bounded three-second,
79-frame desktop-composition recording during camera motion shows visible
blockiness in inspected frames. It is lossy and not paired to source frames,
so the blockiness cannot be assigned to NR, the stream, or the recorder. Keep
the recording in ignored local run output; these runs do not qualify 120 FPS.
This limited sample is not a multi-game or long-sequence guarantee. NR-only is
the mask-free default; no adaptive HUD mode is deployed. Manual custom masks
are optional. A source session that ended due to
inactivity produced no pairs and is explicitly excluded from evidence.
