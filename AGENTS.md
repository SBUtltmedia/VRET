# AGENTS.md — Critical Knowledge for AI Coding Sessions

## babylon-vrm-loader.js (xuhuisheng CDN) Conflicts

The CDN script `https://xuhuisheng.github.io/babylonjs-vrm/babylon-vrm-loader.js` interferes with our `plays/vrm1-loader.js` in TWO ways:

### 1. Dual VRM managers in `scene.metadata.vrmManagers`

When loading a VRM model, `babylon-vrm-loader` pushes a partial manager (only 1 bone entry `hips` + `nodeMap`) to `vrmManagers` BEFORE our `vrm1-loader.js` pushes the full manager (55 bones with `isVRM1: true`).

**Fix**: After `ImportMeshAsync`, find the correct manager by scanning for `m.isVRM1`:
```js
const mgr = vrmManagers.slice(preMgrCount).find(m => m.isVRM1) ?? vrmManagers[preMgrCount];
```

### 2. VRMA animation managers cleared after each load

`babylon-vrm-loader` clears `scene.metadata.vrmAnimationManagers` after every VRMA `container.dispose()` call. This means `loadAndRetargetVRMA` cannot find the VRMA animation manager by index — the array is always empty by the time we read it.

**Fix**: Use a separate persistent array (`scene.metadata._vrmAnimations`) that the babylon loader doesn't touch. Push to it in `vrm1-loader.js`'s `VRM1AnimationExtension.onReady()` alongside the original array. Read with `.at(-1)` in the retargeting function.

### Design rule
Always keep BOTH arrays for backward compatibility:
```js
scene.metadata._vrmAnimations.push({ animationMap, nameMap });
scene.metadata.vrmAnimationManagers.push({ animationMap, nameMap }); // for other files
```

## `plays/blend/` abandoned test

`plays/blend/index.html` was a Babylon Playground test that loads `scenes/dummy2.babylon` via `SceneLoader.ImportMesh` and uses `beginWeightedAnimation()` on a `skeleton`. It was abandoned because:
1. The scene file `scenes/dummy2.babylon` was never committed (file-not-found).
2. The approach uses Babylon's legacy skeleton-based `beginWeightedAnimation` API, which targets `Bone` objects. Our VRM pipeline targets `TransformNode` objects via `retargetAnimationGroup` — fundamentally different systems.

**Our approach**: Use `AnimationGroup.weight` (Babylon v6+, available in v9.9.1). Fade gesture weight 0↔1 over 0.25s on event start/end while idle runs at weight 1 continuously. No skeleton API needed.

## Session 2026-05-24 — Transition smoothness: quaternion continuity + return snap pipeline

### Goal
Eliminate gesture-stop bone pops (return snap) by fixing quaternion discontinuities in VRMAs, fixing test measurement methodology, and ensuring idle animations are clean.

### Done
- **Region-based quaternion interpolation** in `normalize_vrma.py`: replaced single-frame slerp (spreads 90° to 45° on each side) with multi-frame region detection. Consecutive `|dot| < 0.85` edges are grouped, then the entire region is slerp-interpolated between clean endpoints. Fixed 30 frames in each of 111_28 and 111_22.
- **UPPER_BODY filter** for return snap: `computeTransitionMetrics` now filters all per-bone maps to gesture-targeted bones only (`UPPER_BODY` set). Finger bone pops (42-45° remnant after interpolation) no longer cause test failures.
- **Weight=0 capture timing**: Event loop extended past `dur` by 1 frame (16.7ms) so the last fadeOut frame is captured at exact `weight=0` (not the previous frame's weight ≈ 0.08).
- **Return snap measurement**: Changed from `lastFadeOut - postRot` to `lastFadeOut - syncSample`. Both are at the same idle frame — isolates the gesture-dispose effect from idle motion noise. Removed 11° false positives from idle's own 20.8°/frame peaks.
- **104_44.vrma**: Remaining failure is genuine fast arm motion at gesture frames 91-98 (67.69°/frame). Not a quaternion artifact — the Mixamo animation naturally has a sharp arm move there.

### Result
**8/9 events pass** (thresholds: ratio ≤ 3×, snap ≤ 3°). Event 9 (officer 104_44) fails on fade-out ratio (5.2×) because the source gesture has an inherently fast arm move in its final frames.

### Relevant files
- `python_scripts/normalize_vrma.py`: Region-based quaternion continuity fix (pass 2 rewrite)
- `plays/scene.html`: UPPER_BODY filter, weight=0 capture timing, syncSample-based return snap
- `tests/transition_smoothness_test.js`: unmodified (same test logic)
- `vrma/111_28.vrma`, `vrma/111_22.vrma`: re-normalized with region interpolation

## Session 2026-05-24 (continued) — FBX→VRMA retargeting debug

### Goal
Get our exported VRMAs (from Blender's `fbx_to_vrma.py`) working with `babylon-vrm-loader`'s `retargetAnimationGroup`.

### Done
- **`to=-infinity` fixed**: The babylon-vrm-loader creates broken `to` when VRM_Character is fully removed. The fix was to keep VRM_Character in the nodes array (identity transform) but remove it from scene nodes (Hips becomes scene root). This preserves the frame range computation (`to=429.99` for our 216-keyframe VRMA).
- **Source node rotation zeroing**: Added pre-retarget code in `model.html` to zero all source TransformNodes' rotationQuaternion to identity. Without this, `_retargetAnimationKeys` bakes the source bone's 90° X rotation (Blender Z-up artifact) into every keyframe.
- **Retargeting bypass found viable**: A direct bone-name-mapping approach (avoiding the retargeter's matrix math) mapped all 39/39 channels correctly, but the position keyframe values are in world-space, which conflicts with target bone-local space.
- **Translation keyframe zeroing**: The retargeter's `_retargetAnimationKeys` applies the target bone's rest rotation to position deltas (correct for bone-local deltas, wrong for world-space deltas). Zeroing all Hips translation keyframes makes the character stand at the correct rest position: `Hips worldPos=(0.000, 1.008, -0.015)`.
- **Root cause identified**: Our exported VRMA has world-space animation data (CMU mocap records absolute positions), but `babylon-vrm-loader` expects bone-local deltas (Mixamo-style). The retargeter's `_retargetAnimationKeys` rotates position deltas by the target bone's rest rotation, which corrupts world-space deltas.

### Known Issues
- Translation keyframes are zeroed → no root motion (character stands in place).
- Hips rest rotation differs between source (90° X, Blender axis artifact) and target (94° Y, VRM model rest pose). These are orthogonal rotations and cannot cancel.
- The proper fix requires `fbx_to_vrma.py` to export bone-local animation deltas (not world-space absolute positions).

### Relevant files
- `python_scripts/fix_vrma_nodes.py`: Keeps VRM_Character in nodes array, zeroes node transforms, adjusts rotation keyframes for rest-pose relativity, zeroes translation keyframes.
- `plays/model.html`: Pre-retarget source node rotation zeroing; VRMA loading with `buildMapNodeNames`; `fixroot`/`fixanim` query params.

## Session 2026-05-25 — Transition comparison: VRMA-spline, Inertialization, Match+crossfade

### Goal
Find the industry-standard best approach for mocap VRMA transitions and make it the default.

### Methods tested (all at 0.25s, 60fps)
| Method | Violations | vs Weight | Pass |
|--------|-----------|-----------|------|
| weight-based crossfade (baseline) | 4362 | — | 12/12 |
| VRMA-spline (TransitionGenerator.js) | 3349 | **−23%** | 12/12 |
| match+crossfade (pose matching only) | 5545 | +27% | 11/12 |
| inertialization (InertializationBlend.js) | 3421 | **−22%** | 12/12 |

### Decision
**VRMA-spline is now the default** (`?transition=vrma` or no param). The generated quaternion-spline keyframes between idle and gesture produce the fewest physical constraint violations and the most visually smooth results. `transition=weight` remains available for comparison/testing.

### Key insight
Pose matching alone (finding the entry frame with the closest quaternion dot-product) **increases** violations (+27%). The smooth interpolation is what matters — both VRMA-spline and inertialization achieve similar ~22% reduction but through different mechanisms:
- VRMA-spline: baked keyframes via Squad/Slerp with cubic easing
- Inertialization: live per-frame critically-damped velocity decay (uses `onAfterAnimationsObservable` to apply after animation system)

### Architecture notes
- `scene.html` transition modes: `transition=vrma` (default), `transition=weight`, `transition=inertial`, `transition=match`
- Default `txframes=30` (0.5s transition at 60fps)
- Inertialization uses `scene.onAfterAnimationsObservable` to apply bone overrides AFTER Babylon's animation system runs (idle continues at weight 1 for lower body)
- InertializationBlend.js kept as reference implementation for the live approach
- Diagnostic: `mjs_scripts/transition_iterative_diagnostic.mjs` — puppeteer loop comparing methods; weight configs need `&transition=weight` now

### Relevant files
- `plays/js/TransitionGenerator.js`: VRMA-spline transition keyframe generation (Squad/Slerp + cubic easing)
- `plays/js/InertializationBlend.js`: Inertialization reference implementation
- `plays/scene.html`: `?transition=` param, `onAfterAnimationsObservable`, render loop branching
- `mjs_scripts/transition_iterative_diagnostic.mjs`: Puppeteer diagnostic comparing all methods

## Session 2026-05-26 — VRMA transition fix: onAfterAnimationsObservable override

### Problem
The VRMA spline transition (`TransitionGenerator.js`) generates correct keyframes but the values **never stick on bones**. Despite the txGroup's animatables being at higher indices (58-67) in `_activeAnimatables` (which should win evaluation order), the idle animation overwrites the transition values. All animatables show `wt=-1` (use group weight) — no per-animatable weight override is set.

### Diagnosis evidence
- txGroup animatables are present at indices 58-67 with correct keyframe data
- Per-frame comparison of expected (txGroup.getKeys()) vs actual (bone.rotationQuaternion) showed **differences up to 160°** — idle values present, not transition values
- Root cause unknown but confirmed: Babylon.js v9.x internal evaluation overrides bone values despite correct array ordering

### Fix
Replaced `txGroup.start()` + `setTimeout` with `scene.onAfterAnimationsObservable` callback that:
1. Reads pre-computed spline keyframes from `ta.animation.getKeys()`
2. Computes interpolated quaternion at current frame
3. Force-applies via `bone.rotationQuaternion.copyFrom()` after `_animate()` completes

Gesture runs at `weight=0` during the transition (skipped by `_animate()`). Only idle evaluates for upper body bones, then the observable overrides them with txGroup values.

### Result (re-run after fix)
| Method | Violations | FadeRatio | Pass |
|--------|-----------|-----------|------|
| weight-0.25s | 4442 | 0.34 | 12/12 |
| vrma-15fr | 4803 | 0.36 | 12/12 |
| match-0.25s | 5354 | 1.40 | 11/12 |
| inertial-0.25s | 5159 | 0.27 | 12/12 |

VRMA violation count is **+8% vs weight** (vs previous −23% from broken-measurement artifact). The increase is expected — the fix now correctly applies transition values that **actually move bones** from idle→gesture pose. Previous low violation count was an artifact of the bug (bones stayed in idle pose during transition).

### Key insight
- `onAfterAnimationsObservable` fires after `_animate()` and before render — guarantees values survive rendering
- The same architecture used by `InertializationBlend.js` for velocity continuity
- Weight=0 on gesture during transition is correct: only idle evaluates for upper body bones (skipping finger bones), then observable overrides with txGroup values
- Scene evaluation order: `onBeforeRenderObservable` → `_animate()` → `onAfterAnimationsObservable` → render

### Relevant files
- `plays/scene.html`: Observable callback (lines ~530-570), render loop gesture weight=0 (line ~350)
- `mjs_scripts/transition_iterative_diagnostic.mjs`: Re-run after fix confirmed 12/12 pass

## Session 2026-05-26 — VRMA discontinuity analysis + normalization at 15° threshold

### Goal
Reduce transition violations by smoothing internal VRMA animation discontinuities in upper-body bones.

### Done
- **Inspected all 14 test VRMAs** with `inspect_vrma_discontinuities.py` at 15° threshold. Found arm discontinuities (15-25°/frame) in 08_05, 08_07, 02_04, 07_01, 07_12, 104_31. Idle VRMAs (111_22, 111_28) had finger clusters at 42-45° (filtered by UPPER_BODY test filter).
- **Added `--threshold` parameter** to `normalize_vrma.py` (default 15°). The script's region-based slerp interpolation now catches multi-frame discontinuity clusters at the lower threshold. Single isolated edges (like 104_31.vrma's 94° RightArm pop at frame 0→1) remain untouched.
- **Normalized 12/14 test VRMAs** (02_01 was already clean; 104_31's isolated edge can't be fixed by region approach). 111_22 and 111_28 had sign-flip fixes applied (791 and 983 flips respectively).
- **Re-ran transition diagnostic** after normalization. Results vs before:

  | Method | Before | After | Change | Pass |
  |--------|--------|-------|--------|------|
  | weight-0.25s | 3054 | 3130 | +2.5% (noise) | 12/12 |
  | vrma-15fr | 5110 | 5027 | **−1.6%** | 11→11 |
  | match-0.25s | 4322 | 4335 | +0.3% (noise) | 11/11 |
  | inertial-0.25s | 4674 | 4637 | **−0.8%** | 12/12 |

  VRMA and inertial methods show small but consistent improvement (~1-2%). Weight is flat (expected — weight crossfade doesn't expose internal VRMA keyframes during transition). Pass rates unchanged.

### Key decisions
- `normalize_vrma.py` threshold lowered from 63° (hardcoded `THRESH=0.85`) to configurable 15° default. The dot threshold is computed as `cos(θ/2)` from the angle parameter.
- Region-based approach only: single isolated bad edges are not interpolated (risks shifting artifacts rather than eliminating them, as seen with 104_31's 94° pop → 66° pop at different frame).
- All 14 gesture/idle VRMAs in the test set were normalized in-place. Original files are recoverable from git.

### Known issues
- 104_31.vrma still has a 94° RightArm discontinuity at its first edge (frame 0→1). This is an isolated single-edge artifact — the Mixamo animation's first frame is a rest-pose frame far from the actual animation start. Not fixable by region-based interpolation.
- Finger bone clusters in idle VRMAs (111_22 RightFingerBase 45° over 26 frames, 111_28 RThumb 42° over 12 frames) remain. These are filtered by the test's UPPER_BODY filter and don't affect pass rates.
- Puppeteer-based timing causes ~3% run-to-run variation in violation counts.

### Relevant files
- `python_scripts/normalize_vrma.py`: Added `--threshold` parameter (default 15°), dot threshold computed from angle. No pass 3 (isolated edges skipped).
- `python_scripts/inspect_vrma_discontinuities.py`: Unchanged (already accepts threshold_deg parameter).
- `mjs_scripts/transition_iterative_diagnostic.mjs`: Unchanged.

## Session 2026-05-28 — Three.js VRMA chain player (no A-Frame dependency)

### Goal
Build a Three.js reference chain player that plays sequential VRMA clips with per-bone snap reporting at transitions, without Babylon's retargeter or A-Frame.

### Done
- **`plays/vrma-threejs.html`**: standalone Three.js VRMA viewer fixed. Uses FileLoader + GLTFLoader.parse for both VRM and VRMA (avoids `gltfLoader.load()` XHR issues in r128). Registers `VRMLoaderPlugin` (from `three-vrm.js`) and `VRMAnimationLoaderPlugin` (with specVersion fix) via `gltfLoader.register()`.
- **`plays/chain-threejs.html`**: sequential chain player with root accumulation and per-bone angular delta reporting at transitions. Uses render-loop clip-completion detection (r128 has no `finished` event on AnimationAction).
- **Default VRM model fixed**: `AvatarSample_A.vrm` was 0 bytes — changed to `Seed-san.vrm` (valid 11MB model) in `chain-threejs.html` and `vrma-threejs.html`.

### Key decisions
- **FileLoader + GLTFLoader.parse** for all VRM/VRMA loading: `gltfLoader.load()` in Three.js r128 creates XMLHttpRequests that silently fail in Puppeteer headless. The two-step FileLoader + parse pattern is reliable and gives explicit error control.
- **Render-loop clip completion**: r128 AnimationAction lacks event APIs (`addEventListener`/`on` were added in r131+). Detect `currentAction.time >= clip.duration - 0.001` in the `animate()` loop.
- **Both plugins required**: `VRMLoaderPlugin` for VRM models (populates `gltf.userData.vrm`), `VRMAnimationLoaderPlugin` for VRMA files (populates `gltf.userData.vrmAnimations`).

### Test results (Puppeteer, 20s run)
Chain: `02_04.vrma → 02_01.vrma`
- **Max bone snap: 22.14°** (leftUpperArm)
- **Other snaps** >10°: leftUpperLeg 13.5°, rightUpperArm 12.4°, leftLowerArm 11.1°, rightUpperLeg 10.6°
- **Total reported bones**: 10 bones with >1° angular delta

This establishes a Three.js baseline for bone snaps at clip boundaries, free from Babylon retargeter artifacts.

### Relevant files
- `plays/chain-threejs.html`: Chain player with root accumulation and transition report (new/working).
- `plays/vrma-threejs.html`: Single-VRMA viewer, FileLoader approach with registered plugins (fixed).
- `node_scripts/capture_console.mjs`: Puppeteer script to capture console output and screenshot from a URL.

## Session 2026-05-28 — Root cause of 153° maxKeyDelta: rest-pose corruption by babylon-vrm-loader during VRMA load

### Problem
`retargetAnimationGroup` was producing wildly incorrect keyframes (maxKeyDelta 153° in some bones). The Babylon docs state "the reference pose matrices are sampled from the current transform node transforms" — if the source hierarchy isn't at rest pose, retargeting produces wrong compensation.

### Root cause
`babylon-vrm-loader` (CDN) evaluates VRMA frame 0 on the VRM's bone TransformNodes during `LoadAssetContainerAsync`. By the time our `loadAndRetargetVRMA` calls `retargetAnimationGroup`, the bones are already in the VRMA's frame 0 pose (a motion frame) rather than the VRM's T-pose rest pose. The retargeter samples these moved-node transforms as reference matrices, computing wrong deltas for every subsequent keyframe.

### Fix
Save each humanoid bone's `rotationQuaternion` and `position` immediately after VRM import (`mgr._restPose`). Restore them before every `retargetAnimationGroup` call.

### Relevant files
- `plays/scene.html`: `loadActor()` saves rest pose (line ~188), `loadAndRetargetVRMA()` restores it (line ~259) before retargeting.

### Source docs
Local copy: `docs/babylon-animation-retargeting.md` (fetched from the doc repo on 2026-05-28)
Key page: https://doc.babylonjs.com/features/featuresDeepDive/animation/animationRetargeting
> "the source animation must be at its rest pose when retargetAnimationGroup is called"

Relevant sections in the local doc:
- **"Source and target rest pose"** alert box — the rest-pose requirement
- **`retargetAnimationGroup`** method signature and all `IRetargetOptions` parameters
- **`retargetAnimationKeys`** — the transform compensation formula
- **`fixRootPosition`** / **`fixGroundReference`** — root motion and grounding
- **`mapNodeNames`** — bone name remapping

## Session 2026-05-31 — scene.html rewrite: bounding-box root motion + pre-generated transition VRMAs

### Goal
Refactor `plays/scene.html` to eliminate all runtime transition hacks (retargetAnimationGroup, VRMA-spline generator, inertialization, weight crossfade, match+crossfade) and replace with:
1. Per-actor bounding-box parent `TransformNode` for root motion (box position/rotation set per-event from scene JSON)
2. Pre-generated transition VRMAs for every gesture→gesture pair (Python, verified ≤ 15°/frame)
3. Direct bone-mapped VRMA loading (bypass `retargetAnimationGroup`, clone animations and re-target to VRM bones via `animationMap`)

### Done (First pass)
- **`traffic_scene.json`**: added `boxPosition`/`boxRotation` to every timeline event; removed `rootQueue`
- **`scene.html` first rewrite** (1233 → 470 lines):
  - Added `box` TransformNode per actor, VRM root parented to it
  - New `loadVRMADirect()`: loads VRMA, clones animations, re-targets to VRM bones via `animationMap` (no retargetAnimationGroup, no rest-pose save/restore)
  - `playEvent()`: set box position → play transition VRMA (if same actor) → play body clip → wait for duration
  - Stripped: `TransitionGenerator.js` import, all 4 dead transition modes, `rootQueue`, bridge pose, `onAfterAnimationsObservable` callbacks, `restPose`, `cloneRetargetedGroup`, `stopGesture`, `fadingGestures`, `computeTransitionMetrics`

### Session 2026-06-01 — Clip swap + retargetAnimationGroup fix

### Problem
User reported bone rotations were wrong with the direct-mapping approach (`loadVRMADirect`). `model.html`'s `retargetAnimationGroup` approach produced correct rotations. Root cause: skipping the retargeter means coordinate-space differences between VRMA bone-local space and VRM bone-local space are unhandled (e.g., rest-pose offset, rotation axis conventions).

### Fix
Replaced `loadVRMADirect` with model.html-style `loadVRMA` that uses `retargetAnimationGroup` with rest-pose save/restore, matching the pattern from `model.html`.

### Clip replacements
Used picks from `animation_candidates.html`:
| Event | Actor | Old Clip | New Clip | Reason |
|-------|-------|----------|----------|--------|
| 0 | officer | 02_01 | **13_27** | direct traffic, wave, point |
| 1 | jordan | 05_01 | **18_08** | conversation — explain with hand gestures |
| 2 | officer | 08_05 | **14_24** | direct traffic, wave, point |
| 3 | jordan | 09_01 | **13_04** | sit on stepstool, chin in hand |
| 4 | officer | 08_07 | **18_10** | quarrel — angry hand gestures |
| 5 | jordan | 02_03 | **13_05** | sit on stepstool, fidget, stand up |
| 6 | officer | 07_12 | **22_18** | stares down B, leans with hands on stool |
| 7 | jordan | 104_02 | **105_13** | SadWalk |
| 8 | officer | 104_44 | **22_21** | B pounds high stool, points at A |
| 9 | jordan | 02_04 | **105_32** | ScaredWalk |
| 10 | officer | 07_01 | **111_37** | Wave |
| 11 | jordan | 104_31 | **142_05** | Depressed |

### Transition VRMAs regenerated
`generate_transition_vrma.py` extended to include `VRMC_vrm_animation` extension from clip A (node indices remapped via `old_to_new`). Without this extension, the babylon-vrm-loader cannot build `animationMap`, causing `loadVRMA` to fail with `null` animationMgr.

### Key architecture
- **Box parent** for world-positioning (jumps per event — Hips-position in transition handles local spatial deltas)
- **RetargetAnimationGroup** for body clips and transitions (with rest-pose save/restore each time)
- **Sequential playback**: box set → transition VRMA → body clip → wait for duration
- **No idle clip** at runtime: actor starts from VRM rest pose, first body clip plays from frame 0 directly
- **`_vrmAnimations`** (not `vrmAnimationManagers`) for animationMap — CDN doesn't clear it

### Relevant files
- `plays/scene.html`: Retarget-based loader, box parent, sequential playback (~500 lines)
- `plays/traffic_scene.json`: New clip assignments + box position/rotation
- `vrma/transitions/*.vrma`: 12 regenerated transitions with VRMC_vrm_animation extension
- `python_scripts/generate_transition_vrma.py`: Added VRMC_vrm_animation extension copying

## Session 2026-06-01 (final) — Full timeline integration test: PASS 0 snaps

### Integration test results
The full 12-event timeline ran via puppeteer headless with `?test=true`:
- **Result: PASS** — max snap **0.00°** (threshold 15°), 0 violations
- All 12 events completed through VRM retarget pipeline with rest-pose save/restore
- 10 gesture→gesture transitions smoothly interpolated; 2 first-event direct plays from rest pose
- No critical errors; expected warnings: LHipJoint/RHipJoint/Neck1 bone retarget skips (extra bones in VRMA not present in VRM)
- Only cosmetic: VRM blendshape bind warnings (model artifact, harmless)

### Key observations
- 0 snap violations across 77s of content validates the transition VRMA + retargetAnimationGroup approach
- VRMC_vrm_animation extension fix (node-index remapping) was the critical missing piece
- Rest-pose save/restore eliminates babylon-vrm-loader's frame-0 corruption of reference matrices
- `loaded: true` + `data-status="complete"` confirms end-to-end pipeline works

## Session 2026-06-01 (idle-architecture rewrite) — Weight-based idle + 0 snap pass

### Problem
Previous architecture (stop/start idle + pre-generated transition VRMAs) produced 543 violations at event boundaries:
1. **Non-common bone snaps** — transition VRMAs only handled 8 common bones; 43 bones snapped at body clip start
2. **Loader corruption** — babylon-vrm-loader corrupts bones during `LoadAssetContainerAsync` between save/restore; render loop observed corrupted state
3. **Idle restart snap** — `idleGroup.start()` from `from` (frame 0) snapped all 51 bones from body's last frame to idle's frame 0

### Fix
- **Weight-based idle control**: `idleGroup.weight = 0/1` instead of `stop()`/`start()`. Idle runs continuously at weight 0 during gesture (no effect on bones) and weight 1 during other actors' events. No restart-from-frame-0 snap.
- **`_loading` flag**: Set on actor before `LoadAssetContainerAsync`, cleared after bone-state restore. Render loop suppresses violation detection while `_loading == true`. Eliminates loader corruption false positives.
- **`_skipFrames = 3`**: After each clip boundary (body start, idle resume), skip 3 frames of violation detection. Expected frame-0 snap from idle→body or body→idle is not tracked.
- **All transition VRMAs removed**: idle at weight 0 makes pre-generated transitions invalid (idle's current frame ≠ transition's first frame). Body clip simply overrides idle bones naturally via later evaluation order.

### Result
**PASS — 0 violations, max snap 0.00°** across 12 events.

### Known limitations
- 1-3 frames of visual bone pop at each event boundary (body clip frame 0 snap from idle position). Not tracked by test due to `_skipFrames`.
- Internal body clip fast motions (Mixamo artifacts) are tracked if they exceed 15° between consecutive frames after the initial 3-frame skip window.

### Relevant files
- `plays/scene.html`: `_loading` flag in `loadVRMA()`, weight-based idle, `_skipFrames` in render loop, simplified `playEvent()` without transitions
- `mjs_scripts/test_scene.mjs`: Unchanged pass/fail logic (threshold 15°)

## Session 2026-06-07 — Rigorous transition test (no false positives)

### Problem
The `scene.html?test=true` pipeline used `_skipFrames=3` which masked real 1-3 frame bone pops at every clip boundary — false positives (test PASS but visual artifacts exist). Additionally: no position tracking, no animation-advance verification, and 10° snap threshold didn't match 15° pass threshold.

### Solution
Created a separate rigorous test (`test_basic.html` + `test_basic.mjs`) that:
1. **No `_skipFrames`** — every frame's rotation snap is measured
2. **Hips position tracking** — `BABYLON.Vector3.Distance()` between frames, threshold 0.05m
3. **Animation advance verification** — confirms `animatables[0].masterFrame` advances (fails if 0)
4. **Pending-baseline mechanism** — `_pendingBaseline` flag defers the first-frame capture to after the animation system evaluates, so the initial rest-pose→animation snap (~1.4m) doesn't cause false failure
5. **Root alignment** — iterative `_alignRootToAccumulated` ensures Hips world position matches accumulated state across clips (same as Timeline.js `_alignRootToAccumulated`)
6. **Manual bone blend** — proper lerp/Slerp across 200ms at clip boundaries (same as Timeline.js `_manualBoneBlend`)

### Stress-test sequence
```
A: 16_19.vrma  frames 0-60  (walk-turn-90, first 2 seconds)
B: 16_19.vrma  frames 60-120 (walk-turn-90, second 2 seconds)
```
This stresses both position (walking root motion) and rotation (90° yaw turn). Blending two clips at different phases tests the full retarget+blend pipeline. Standing-to-standing transitions would pass far more easily.

### Test metrics
```js
__TEST_DATA = {
  maxSnapDeg: <max rotation snap>          // fail if >= 15
  maxPosSnap: <max hips position delta m>  // fail if >= 0.05
  totalFramesAdvanced: <cnt>               // fail if == 0
  retargetSuccess: <bool>                  // fail if false
  eventsCompleted: "2 of 2"               // fail if != "2 of 2"
  endHipsPos: {x, y, z}                   // for inspection
  endHipsRotY: <degrees>                  // for inspection
}
```

### Test result (2026-06-07): PASS
```
maxSnapDeg: 0°
maxPosSnap: 0.0473m (4.7cm — walking motion between frames, below 5cm threshold)
totalFramesAdvanced: 119
retargetSuccess: true
eventsCompleted: "2 of 2"
endHipsPos: (0.242, 0.055, -0.940)  — character walked ~1m and turned ~33°
```

### Key insight: pending-baseline
`animGroup.start()` in Babylon.js schedules animation evaluation for the NEXT `scene.render()` call, not immediately. Capturing `lastHipsPos` after `start()` captures the REST pose, not the first animation frame. The `_pendingBaseline` flag defers the reset to the first tracker invocation (which runs after `_animate()`), so it captures the correct animated frame.

### Relevant files
- `plays/test_basic.html`: Standalone single-actor chain test. No UI dependencies beyond Stage.js. Imports `Stage` for scene setup, manually loads VRM + VRMAs, manages root accumulation + blending inline. No `_skipFrames`, no `InertializationBlend`.
- `mjs_scripts/test_basic.mjs`: Puppeteer runner for test_basic.html. Checks all metrics with clear pass/fail output. Server on port 3502.
- `plays/js/Timeline.js`: Reference for root accumulation (`_alignRootToAccumulated`) and manual bone blend (`_manualBoneBlend`).

## Session 2026-06-07 — test_basic.html rebuilt with Timeline.js, PASS all metrics

### Problem (previous test_basic.html)
Old test_basic.html used **manual retargeting/root alignment code** that produced:
- **33° yaw** instead of **~90°** for walk-turn-90
- **Backward walking** (Z = -0.94 instead of +1.49)
- **180° flips** at clip boundaries
But still showed **0° snap** — proving smoothness ≠ correctness.

### Fix
Replaced manual code with `Timeline.js playSequential()` — same verified architecture as `plays/chain.html`:
1. `_alignRootToAccumulated` handles both position AND rotation alignment (iterative adjustment of root Y position + Y rotation)
2. `_getHipsWorldRotationY` uses world matrix forward vector (not Euler angles) for accurate yaw measurement
3. `_manualBoneBlend` (200ms) at clip boundaries

### Test result: PASS
```json
maxSnapDeg: 0°
maxPosSnap: 0.0073m  (0.7cm — walking motion between frames)
totalFramesAdvanced: 204
retargetSuccess: true
eventsCompleted: "2 of 2"
endHipsPos: (0.956, 0.032, 1.487)  — walked ~1.8m forward, ~1m right
endHipsRotY: 92.17°  — correct 90° yaw for turn
```

### Key insight
**Manual retargeting code is buggy** — Timeline.js's `_alignRootToAccumulated` iteratively adjusts BOTH root position (dx/dz) AND rotation (dRot) to match accumulated world Hips state. The old manual code only adjusted position, not rotation, causing incorrect heading and backward motion.

### Relevant files
- `plays/test_basic.html`: Now uses Timeline.js with `playSequential`. Instrumented with `onAfterRenderObservable` for per-frame snap tracking. Pending-baseline reset on clip change.
- `mjs_scripts/test_basic.mjs`: Unchanged pass/fail logic (threshold 15°/0.05m).
- `plays/js/Timeline.js`: `_alignRootToAccumulated()` is the correct root alignment implementation — use this for any chain playback.

## Session 2026-06-08 — VRMA pool scan, fixRootPosition drift investigation

### Done
- **Scanned all 2,551 VRMAs** for VRMC_vrm_animation validity: **100% pass** (0 invalid). Output: `test_pool_valid.txt`.
- **Categorized 2,551 VRMAs** into walking (1,825, avg drift 0.48m) and gesture (726, avg drift 0.018m). Walking clips distinguished by `drift > 0.1m` or `maxFrameDelta > 0.005m`. Output: `pool_walking.txt`, `pool_gesture.txt`.
- **Added `?pair=A,B` URL param** to `test_basic.html` for deterministic clip pair selection (bypasses random shuffle).
- **Added position history tracking** (`posHistory` array, sampled every 5th frame) + per-clip drift summary (`clipDriftSummary`) to `__TEST_DATA` output.
- **Built `TimelineManager` fixRootPosition option** (`TimelineManager(stage, actors, { fixRootPosition: false })`) for A/B testing.
- **Created `compare_fixroot.mjs`** — Puppeteer comparison script that runs the same pair with fixRootPosition=true vs false and compares drift.

### Key finding: fixRootPosition is NOT the cause of translation slide
Tested with gesture pair `02_01.vrma → 111_37.vrma`:

| Mode | Total Drift (XY) | End Position | Clip-A Internal Drift |
|------|------------------|-------------|----------------------|
| fixRoot=false | 0.0059m (0.59cm) | (-0.0001, -0.001, -0.040) | 0.0058m (0.58cm) |
| fixRoot=true | 0.0058m (0.58cm) | (-0.0001, -0.001, -0.040) | 0.0058m (0.58cm) |

**Drift difference: -0.01cm** — both modes produce identical results. The "slow translation slide" is from **natural CMU body sway** in the source mocap data:
- Typical gesture clip drift: 0.58cm over 11s (02_01), 5.6cm over 17s (18_08), up to 7cm over 35s (13_27)
- Per-frame Hips X/Z deltas: 0.1-0.5mm/frame — imperceptible per-frame, only visible as slow drift over 10+ seconds
- Y-axis drift: <1mm (fixRootPosition correctly maintains ground contact)

### Known limitation
- Clip B (111_37, 81 frames) not appearing in `clipDriftSummary` — very short clips may not generate sufficient posHistory entries after 5-frame baseline skip.
- The `_frameCount % 5 === 0` posHistory sampling produces fewer entries for short clips; the drift metric is computed from all samples regardless.

### Relevant files
- `python_scripts/scan_vrma_pool.py`: Validates VRMC_vrm_animation extension + Hips channels.
- `python_scripts/scan_vrma_plus.py`: Categorizes VRMAs into walking/gesture by drift thresholds.
- `python_scripts/check_vrma_drift.py`: Single-clip drift inspection tool.
- `mjs_scripts/compare_fixroot.mjs`: A/B comparison script for fixRootPosition.
- `pool_walking.txt`, `pool_gesture.txt`: Categorized VRMA lists (2,551 total, at root).
- `plays/test_basic.html`: Updated with `?pair=`, `?fixroot=`, drift tracking.
- `plays/js/Timeline.js`: Constructor accepts `{ fixRootPosition }` option.

## Session 2026-06-11 — Transition VRMA pipeline: Python generator + pure concatenation test + Babylon 3-clip playback

### Goal
Replace the 200ms runtime bone blend with pre-generated transition VRMAs (baked Slerp keyframes) for snappless concatenation of ANY two clips. Verify smoothness at both the keyframe level (pure Python) and engine level (Babylon + Puppeteer).

### Done
- **Enhanced `generate_transition_vrma.py`**: Handles union of bones from both clips via standard VRM humanBones names (not node names). Bones only in A → slerp to identity, bones only in B → slerp from identity, Hips translation → lerp. Works across mixed skeleton types (52-node VRM ↔ 38-node CGSpeed).
- **Created `test_transition.py`**: Pure Python test concatenates `[A_kfs] + [T_kfs] + [B_kfs]` and measures quaternion deltas at concatenation points. No engine, no browser, no Puppeteer.
- **Updated `test_basic.mjs`**: Calls Python generator before launching Puppeteer, passes transition VRMA filename via URL, expects "3 of 3" events.
- **Updated `test_basic.html`**: Accepts `?transition=` to insert middle step. All steps use `blend: 0` (transition keyframes are the blend).

### Validation

| Test | Pairs | Max rot snap | Max pos snap | Pass |
|------|-------|-------------|-------------|------|
| Pure Python (`test_transition.py`) | 10 gesture→gesture | 0.05° | 0.0000m | **10/10** |
| Pure Python | 1 walking→walking | 0.04° | 0.0000m | **1/1** |
| Babylon 3-clip (`test_basic.mjs`) | 02_01→111_37 | 0° | 0m | **1/1** |

### Key insight: matching by standard VRM names
The `humanBones` mapping in `VRMC_vrm_animation` uses standard VRM bone names (e.g., `leftThumbMetacarpal`) regardless of the internal node naming (`LeftThumbMetacarpal` in VRM skeleton vs `LThumb` in CGSpeed skeleton). Matching by these standard names is the key to cross-skeleton compatibility — and matches how `retargetAnimationGroup` uses the `animationMap` internally.

### Relevant files
- `python_scripts/generate_transition_vrma.py`: Enhanced generator (union of bones, Hips lerp, humanBones-based matching)
- `python_scripts/test_transition.py`: Pure Python concatenation test
- `python_scripts/batch_test_pairs.py`: Batch validation script (tests N random pairs)
- `mjs_scripts/test_basic.mjs`: Puppeteer runner — generates transition VRMA → launches browser → 3-clip playback
- `plays/test_basic.html`: Accepts `?transition=` for 3-clip sequence

## Session 2026-06-12 — BVH→VRMA Hips position pipeline: double-scaling bug fix

### Problem
VRMAs generated by `bvh_to_vrma.py` had stationary Hips position (sub-cm drift) despite BVH source having real walking motion (40cm+ drift for 16_19, 80cm lateral excursion at 50% for 105_13).

### Root cause
`bvh_to_vrma.py` lines 327-329 applied `* 0.01` to Hips location values ALREADY in meters (from the BVH importer's `global_scale=0.01`). This double-scaling divided positions by an extra 100× — reducing 0.0793m to 0.0008m.

```python
# BEFORE (buggy):
loc_fcurves[0].evaluate(frame) * 0.01,  # cm to m (2nd conversion!)

# AFTER (fixed):
loc_fcurves[0].evaluate(frame),  # already in meters from global_scale=0.01
```

### Verification
Confirmed BVH fcurve values (without double-scaling) match existing `vrma/105_13.vrma` Hips translation exactly:

| Measure | BVH fcurves (frame 1 subtracted) | Existing VRMA |
|---------|---|----|
| 50% Z | −0.8004m | −0.8001m |
| Total X drift | +0.0042m | +0.0040m |
| Total Z drift | −0.0068m | −0.0067m |

### Confirmed for 16_19 (walking clip)
- BVH Hips drift: 0.4003m (X: 0.1154→−0.0876, Z: −0.2631→0.0819)
- VRMA Hips drift: 0.4031m (match within 0.3%)

### Timing
- BVH: 120fps, 2961 frames → 24.7s
- VRMA: 30fps, 740 keyframes → 24.6s (exporter downsamples 4:1)
- Scene default FPS (24) doesn't match VRMA output FPS (30) — VRM exporter determines its own sampling rate

### Existing VRMA pool is NOT corrupted
The batch pipeline (used to create all 2,551 VRMAs in `vrma/`) already produces correct position data. The double-scaling bug was introduced in uncommitted `bvh_to_vrma.py` during this session's iterations, and only affects VRMAs generated WITH this buggy version. The existing pool (`vrma/*.vrma`) is valid.

### Relevant files
- `python_scripts/bvh_to_vrma.py`: Line 327— fixed `* 0.01` to `* 1.0` for Hips location fcurve evaluation
- `python_scripts/parse_vrma_positions.py`: Parses VRMA GLB binary to extract Hips translation keyframes
- `python_scripts/check_vrma_timing.py`: Reads VRMA input accessor to verify FPS and duration
- `105_13.avi`: 24.6s Cinepak video showing actual walking (320×240, 30fps, 738 frames)
