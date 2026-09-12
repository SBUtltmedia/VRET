# Pair-by-Pair Transition Validation Plan

## Goal
Iteratively validate each clip pair (A → B) using a pre-generated transition VRMA (T) through the full pipeline: Python generation → Pure Python validation → Puppeteer capture → Visual review.

## Per-Pair Workflow

### Step 1: Generate Transition VRMA
```bash
python python_scripts/generate_transition_vrma.py vrma/A.vrma vrma/B.vrma \
  -o vrma/tx_A_to_B.vrma --threshold 15 --fps 60
```
- Union of all bones from both clips (standard VRM humanBones names)
- Bones only in A → slerp to identity; only in B → slerp from identity
- Hips translation: lerp from A's last frame to B's frame 0 (this may cause foot-slide — known issue)

### Step 2: Pure Python Validation
```bash
python python_scripts/test_transition.py vrma/A.vrma vrma/tx_A_to_B.vrma vrma/B.vrma \
  --rot-threshold 15 --pos-threshold 0.05
```
- Concatenates keyframes at the binary level (no engine)
- Checks **both** concatenation boundaries (A→T, T→B) for:
  - Per-bone quaternion angular delta (< 15°)
  - Hips position delta (< 0.05m)
- If this fails → the transition has keyframe-level discontinuities (fix generator)

### Step 3: Puppeteer Capture + Test
```bash
node mjs_scripts/capture_console.mjs \
  "http://127.0.0.1:5503/plays/test_basic.html?test=true&pair=A,B" \
  --timeout=30000
```
- Runs full 3-clip Babylon sequence: A → T → B
- Reports: `__TEST_DATA` JSON with maxSnapDeg, maxPosSnap, eventsCompleted, etc.
- Detects HTTP 4xx/5xx errors (capture_console.mjs) — catches missing files
- Detects PASS/FAIL in console output

### Step 4: Evaluate Results
- **Pure Python FAIL** → fix generator (keyframe continuity issue)
- **Babylon test FAIL** → fix pipeline (retarget, root alignment, bone mapping)
- **Both PASS but visuals wrong** → tighten test criteria (e.g., higher-order continuity, Hips velocity preservation, foot-plant detection)

### Step 5: Visual Review
User loads:
```
http://127.0.0.1:5503/plays/test_basic.html?pair=A,B
```
Click to start. Watch for:
- Bone pops at transitions
- Hips position / rotation discontinuities
- Foot sliding during transition
- Overall motion quality

### Step 6: Iterate
- If visual issues found → improve generator or pipeline
- Then add new test criteria to detect the issue automatically
- Repeat until the pair passes both automated and visual inspection

## Files
| File | Role |
|------|------|
| `python_scripts/generate_transition_vrma.py` | Generate T from A + B |
| `python_scripts/test_transition.py` | Pure Python concatenation test |
| `plays/test_basic.html` | Babylon sequence player + test metrics |
| `mjs_scripts/capture_console.mjs` | Puppeteer capture + 404 detection |
| `vrma/tx_A_to_B.vrma` | Generated transition VRMA (in git? TBD) |
