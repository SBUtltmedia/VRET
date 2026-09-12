# CMU Mocap → VRMA Dataset

**2,548 normalized VRMA animation clips** converted from the [CMU Graphics Lab Motion Capture Database](https://mocap.cs.cmu.edu/) (CGSpeed BVH release, 113 subjects).

Each clip is a standard `.vrma` file (glTF 2.0 Binary + VRM Animation Extension) ready for use with:

- **Babylon.js** via [babylon-vrm-loader](https://xuhuisheng.github.io/babylonjs-vrm/)
- **Three.js** via [@pixiv/three-vrm](https://github.com/pixiv/three-vrm)
- Any glTF-compatible runtime that supports VRM Animation

## Quick Start (Babylon.js)

```js
await BABYLON.SceneLoader.ImportMeshAsync(null, 'models/Seed-san.vrm', null, scene);

const mgr = scene.metadata.vrmManagers.find(m => m.isVRM1);
const animGroup = await loadAndRetargetVRMA('vrma/13_27.vrma', mgr, scene);
animGroup.start();
```

## Quick Start (Three.js)

```js
const loader = new GLTFLoader();
loader.register(parser => new VRMLoaderPlugin(parser));
loader.register(parser => new VRMAnimationLoaderPlugin(parser));

const gltf = await loader.loadAsync('vrma/13_27.vrma');
const clip = gltf.userData.vrmAnimations[0];
mixer.clipAction(clip).play();
```

## Dataset Features

- **Frame 0 normalized**: Every clip has Hips at world origin (0, 0, 0) with identity rotation
- **Position smoothed**: Single-frame Y-axis discontinuities >5cm (CMU marker artifacts) are interpolated
- **Global scale**: 1 VRMA unit = 1 meter
- **Frame rate**: 30fps (converted from 120fps CMU source)
- **Bone mapping**: CGSpeed MotionBuilder bone names → VRM 1.0 humanoid bones (22 bones mapped)
- **Finger bones**: Zeroed to identity (CMU finger data is procedural filler per [mocap.cs.cmu.edu](https://mocap.cs.cmu.edu/))

## Conversion Pipeline

All VRMAs were generated via the pipeline in `python_scripts/`:

```
bvh_to_vrma.py          # Blender Python: BVH → VRMA conversion
normalize_vrma_origin.py # Frame 0 normalization + position smoothing
cmu_vrma_pipeline.py    # Orchestrator: download → convert → normalize
```

See `python_scripts/cmu_vrma_pipeline.py --help` to regenerate or extend the dataset.

Requirements: Blender 3.6+ (tested on 5.0), Python 3.7+

## File Naming

```
{subject:02d}_{take:02d}.vrma
```

- `13_27.vrma` = Subject 13, Take 27 (direct traffic with waving)
- `16_19.vrma` = Subject 16, Take 19 (walk-turn-90)

For per-subject directories, use the `--output` flag when running the pipeline.

## Content Notes

- **Walking/Gait**: Subjects 02, 05, 07, 16, 35, 36, 55, 56, 69, 79, 83, 90, 91
- **Gestures/Conversation**: Subjects 08, 09, 13, 14, 18, 22, 105, 111
- **Sports/Physical**: Subjects 06, 07, 08, 10, 17, 20, 31, 32, 33, 34, 38, 39, 40, 41
- **Sitting/Stepstool**: Subjects 13 (takes 04-06), 105
- **Dance**: Subjects 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47

## License

**CMU Mocap Data**: Public domain ([CMU Graphics Lab](https://mocap.cs.cmu.edu/)) — no license restrictions.

**Conversion scripts (BVH→VRMA pipeline)**: MIT License.

**VRM model (Seed-san.vrm)**: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — see [VRoid Hub](https://hub.vroid.com/).

## Citation

If you use this dataset, please cite:

```
CMU Graphics Lab Motion Capture Database
http://mocap.cs.cmu.edu/
```
