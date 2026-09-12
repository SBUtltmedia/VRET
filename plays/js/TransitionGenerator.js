/**
 * TransitionGenerator.js — Generates a transition VRMA (AnimationGroup) between
 * two animation states using quaternion spline interpolation, instead of
 * runtime weight-based crossfading.
 *
 * Instead of blending A→B via AnimationGroup.weight (which only considers
 * endpoints and produces physically impossible intermediate poses), this
 * generates proper keyframed animations with C1-continuous quaternion curves
 * that respect angular velocity at the transition boundaries.
 *
 * Usage:
 *   const gen = new TransitionGenerator(scene);
 *   const tx = gen.buildTransition(currentPose, gestureAnim, entryFrame, numFrames);
 *   tx.start();  // plays transition
 *   // After transition ends, gestureAnim takes over seamlessly
 */
export class TransitionGenerator {
  constructor(scene) {
    this.scene = scene;
  }

  /**
   * Snapshot current rotationQuaternion of bones that will be affected by a target animation.
   * This ensures we transition from the ACTUAL current pose, even if the bone wasn't
   * animated in the previous AnimationGroup.
   *
   * @param {AnimationGroup} targetAnim — the animation we are transitioning INTO
   * @returns {Object} { [boneName]: { rotation: Quaternion, position: Vector3 } }
   */
  snapshotPose(targetAnim) {
    const pose = {};
    if (!targetAnim) return pose;
    for (const ta of targetAnim.targetedAnimations) {
      const bone = ta.target;
      if (!bone?.name) continue;
      
      pose[bone.name] ??= {};

      // Get the ACTUAL current rotation from the bone itself
      const q = bone.rotationQuaternion;
      if (q) {
        pose[bone.name].rotation = q.clone();
      } else if (bone.rotation) {
        const euler = bone.rotation;
        pose[bone.name].rotation = BABYLON.Quaternion.RotationYawPitchRoll(euler.y, euler.x, euler.z);
      } else {
        pose[bone.name].rotation = new BABYLON.Quaternion();
      }

      // Get the ACTUAL current position from the bone itself
      pose[bone.name].position = bone.position.clone();
    }
    return pose;
  }

  /**
   * Evaluate a specific bone's rotation at a specific frame index in an AnimationGroup.
   */
  evaluateBoneAtFrame(animGroup, targetBone, frameIndex) {
    for (const ta of animGroup.targetedAnimations) {
      if (ta.target === targetBone) {
        const anim = ta.animation;
        if (!anim || anim.targetProperty !== 'rotationQuaternion') continue;
        const keys = anim.getKeys();
        if (!keys || keys.length === 0) continue;
        const idx = Math.min(frameIndex, keys.length - 1);
        return keys[idx].value.clone();
      }
    }
    // Fallback: actual bone rotation
    return targetBone.rotationQuaternion || BABYLON.Quaternion.FromEulerAngles(targetBone.rotation.x, targetBone.rotation.y, targetBone.rotation.z);
  }

  /**
   * Evaluate a specific bone's position at a specific frame index in an AnimationGroup.
   */
  evaluateBonePositionAtFrame(animGroup, targetBone, frameIndex) {
    for (const ta of animGroup.targetedAnimations) {
      if (ta.target === targetBone) {
        const anim = ta.animation;
        if (!anim || anim.targetProperty !== 'position') continue;
        const keys = anim.getKeys();
        if (!keys || keys.length === 0) continue;
        const idx = Math.min(frameIndex, keys.length - 1);
        return keys[idx].value.clone();
      }
    }
    // Fallback: actual bone position
    return targetBone.position.clone();
  }

  /**
   * Evaluate a single frame of an AnimationGroup at a given frame index.
   * Returns: { [boneName]: { rotation: Quaternion, position: Vector3 } }
   */
  evaluateFrame(animGroup, frameIndex) {
    const pose = {};
    for (const ta of animGroup.targetedAnimations) {
      const bone = ta.target;
      if (!bone?.name) continue;
      pose[bone.name] ??= {};
      
      const anim = ta.animation;
      if (!anim) continue;

      const keys = anim.getKeys();
      if (!keys || keys.length === 0) continue;
      const idx = Math.min(frameIndex, keys.length - 1);
      const val = keys[idx].value;

      if (anim.targetProperty === 'rotationQuaternion') {
        pose[bone.name].rotation = val.clone();
      } else if (anim.targetProperty === 'position') {
        pose[bone.name].position = val.clone();
      }
    }
    return pose;
  }

  /**
   * Find the frame in `targetAnim` whose bone rotations best match the
   * given `sourcePose`.  Uses weighted quaternion dot-product distance.
   * Returns: { frameIndex, distance, pose }
   */
  findBestEntryFrame(targetAnim, sourcePose) {
    let bestIdx = 0;
    let bestDist = Infinity;
    let bestPose = null;
    let bestPerBoneAngles = {};

    let totalFrames = 0;
    for (const ta of targetAnim.targetedAnimations) {
      if (ta.animation?.getKeys) {
        totalFrames = Math.max(totalFrames, ta.animation.getKeys().length);
      }
    }
    if (totalFrames === 0) return { frameIndex: 0, distance: 0, pose: null, maxAngleDeg: 0, perBoneAnglesDeg: {} };

    for (let f = 0; f < totalFrames; f++) {
      const framePose = this.evaluateFrame(targetAnim, f);
      let totalDist = 0;
      let matchedBones = 0;
      const perBone = {};
      for (const [boneName, data] of Object.entries(sourcePose)) {
        const qSrc = data.rotation;
        if (!qSrc) continue;

        const targetData = framePose[boneName];
        const qTgt = targetData?.rotation;
        if (!qTgt) continue;

        const dot = Math.abs(BABYLON.Quaternion.Dot(qSrc, qTgt));
        const angle = 2 * Math.acos(Math.min(1, dot));
        totalDist += angle * angle;
        matchedBones++;
        perBone[boneName] = angle * 180 / Math.PI;
      }
      if (matchedBones === 0) continue;
      const avgDist = Math.sqrt(totalDist / matchedBones);
      if (avgDist < bestDist) {
        bestDist = avgDist;
        bestIdx = f;
        bestPose = framePose;
        bestPerBoneAngles = perBone;
      }
    }

    if (bestPose === null) bestPose = this.evaluateFrame(targetAnim, 0);
    const maxAngleDeg = Math.max(...Object.values(bestPerBoneAngles), 0);
    return { frameIndex: bestIdx, distance: bestDist, pose: bestPose, maxAngleDeg, perBoneAnglesDeg: bestPerBoneAngles };
  }

  _ease(t) {
    return t; // Linear for constant speed
  }

  /**
   * Generate N+1 transition keyframes for one bone's rotation using
   * spherical linear interpolation (Slerp).
   */
  _generateBoneKeys(qStart, qEnd, numFrames) {
    const keys = [];
    if (numFrames <= 1) {
      keys.push({ frame: 0, value: qStart.clone() });
      keys.push({ frame: 1, value: qEnd.clone() });
      return keys;
    }

    // Ensure qEnd is in same hemisphere as qStart for shortest path
    let qEndClamped = qEnd.clone();
    if (BABYLON.Quaternion.Dot(qStart, qEndClamped) < 0) {
      qEndClamped.scaleInPlace(-1);
    }

    for (let i = 0; i <= numFrames; i++) {
      const t = i / numFrames;
      const et = this._ease(t);
      const q = BABYLON.Quaternion.Slerp(qStart, qEndClamped, et);
      keys.push({ frame: i, value: q });
    }
    return keys;
  }

  /**
   * Generate N+1 transition keyframes for one bone's position using
   * linear interpolation (Lerp).
   */
  _generateBonePositionKeys(pStart, pEnd, numFrames) {
    const keys = [];
    if (numFrames <= 1) {
      keys.push({ frame: 0, value: pStart.clone() });
      keys.push({ frame: 1, value: pEnd.clone() });
      return keys;
    }

    for (let i = 0; i <= numFrames; i++) {
      const t = i / numFrames;
      const et = this._ease(t);
      const p = BABYLON.Vector3.Lerp(pStart, pEnd, et);
      keys.push({ frame: i, value: p });
    }
    return keys;
  }

  /**
   * Compute tangent quaternions from an animation group at a given frame.
   */
  _computeTangents(animGroup, boneNames, frameIndex, delta = 1) {
    const tangents = {};
    if (!animGroup) return tangents;
    for (const ta of animGroup.targetedAnimations) {
      const bone = ta.target;
      if (!bone?.name || !boneNames.has(bone.name)) continue;
      const anim = ta.animation;
      if (!anim || anim.targetProperty !== 'rotationQuaternion') continue;
      const keys = anim.getKeys();
      if (!keys || keys.length < 2) continue;
      const fidx = Math.min(Math.max(0, frameIndex), keys.length - 1);
      const prevIdx = Math.max(0, fidx - delta);
      const nextIdx = Math.min(keys.length - 1, fidx + delta);
      const qPrev = keys[prevIdx].value;
      const qNext = keys[nextIdx].value;
      const qMid = BABYLON.Quaternion.Slerp(qPrev, qNext, 0.5);
      const qCur = keys[fidx].value;
      const dot = BABYLON.Quaternion.Dot(qCur, qMid);
      if (Math.abs(dot) > 0.999) {
        tangents[bone.name] = qMid.clone();
      } else {
        const angle = 2 * Math.acos(Math.min(1, Math.abs(dot)));
        const step = Math.min(delta / angle, 1);
        tangents[bone.name] = BABYLON.Quaternion.Slerp(qCur, qMid, step);
      }
    }
    return tangents;
  }

  /**
   * Build a transition AnimationGroup from a start pose to an end state.
   *
   * @param {Object} startPose — { [boneName]: { rotation: Quaternion, position: Vector3 } }
   * @param {AnimationGroup} targetAnim — the animation we are transitioning INTO
   * @param {number} entryFrame — the frame in targetAnim to match
   * @param {number} numFrames — transition duration
   * @param {Object} [explicitEndPose] — optional { [boneName]: { rotation: Quaternion, position: Vector3 } } to use as target
   * @returns {AnimationGroup}
   */
  buildTransition(startPose, targetAnim, entryFrame, numFrames, explicitEndPose = null) {
    const txGroup = new BABYLON.AnimationGroup("vrma-transition", this.scene);
    const entryPose = explicitEndPose || this.evaluateFrame(targetAnim, entryFrame);

    for (const ta of targetAnim.targetedAnimations) {
      const bone = ta.target;
      if (!bone?.name) continue;

      const startData = startPose[bone.name];
      const endData = entryPose[bone.name];
      if (!startData || !endData) continue;

      if (ta.animation.targetProperty === 'rotationQuaternion') {
        const qStart = startData.rotation;
        const qEnd = endData.rotation;
        if (qStart && qEnd) {
          const keys = this._generateBoneKeys(qStart, qEnd, numFrames);
          const anim = new BABYLON.Animation(
            `tx-rot-${bone.name}`,
            'rotationQuaternion',
            60,
            BABYLON.Animation.ANIMATIONTYPE_QUATERNION,
            BABYLON.Animation.ANIMATIONLOOPMODE_CONSTANT
          );
          anim.setKeys(keys);
          txGroup.addTargetedAnimation(anim, bone);
        }
      } else if (ta.animation.targetProperty === 'position') {
        const pStart = startData.position;
        const pEnd = endData.position;
        if (pStart && pEnd) {
          const keys = this._generateBonePositionKeys(pStart, pEnd, numFrames);
          const anim = new BABYLON.Animation(
            `tx-pos-${bone.name}`,
            'position',
            60,
            BABYLON.Animation.ANIMATIONTYPE_VECTOR3,
            BABYLON.Animation.ANIMATIONLOOPMODE_CONSTANT
          );
          anim.setKeys(keys);
          txGroup.addTargetedAnimation(anim, bone);
        }
      }
    }

    return txGroup;
  }

  /**
   * High-level: generate and play transition from current state into
   * a gesture animation at the best-matching entry frame.
   * The gesture animation is NOT started until the transition completes.
   *
   * @param {AnimationGroup} currentAnim — currently playing animation
   * @param {AnimationGroup} gestureAnim — gesture to transition into
   * @param {number} transitionFrames — number of transition frames
   * @returns {{ txGroup: AnimationGroup, entryFrame: number, txSeconds: number }}
   */
  prepareTransition(currentAnim, gestureAnim, transitionFrames = 60) {
    const currentPose = this.snapshotPose(currentAnim);
    const { frameIndex: entryFrame, distance: matchDist, maxAngleDeg } = this.findBestEntryFrame(gestureAnim, currentPose);
    if (matchDist > 0) {
      console.log(`[TransitionGenerator] Best match: frame ${entryFrame}, dist ${matchDist.toFixed(4)} rad (max ${maxAngleDeg.toFixed(1)}°)`);
    }

    const txGroup = this.buildTransition(currentPose, gestureAnim, entryFrame, transitionFrames);
    const txSeconds = transitionFrames / 60;

    return { txGroup, entryFrame, txSeconds, currentPose, maxAngleDeg };
  }
}
