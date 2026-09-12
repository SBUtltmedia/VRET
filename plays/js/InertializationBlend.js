/**
 * InertializationBlend.js — Industry-standard inertialized animation blending.
 *
 * Uses scene.onAfterAnimationsObservable to apply inertial blend AFTER
 * Babylon's animation system runs (so idle continues for lower body).
 *
 * Reference: Neall Ver Hoef, "Inertialization: High-Performance
 * Animation Transitions" (GDC 2017)
 *
 * Usage:
 *   const blend = new InertializationBlend(scene);
 *   blend.captureInertia(currentAnim);     // record pose + velocity (3+ frames)
 *   blend.startTransition(gestureAnim, entryFrame);
 *   // After transition completes:
 *   gestureAnim.weight = 1;
 */
export class InertializationBlend {
  constructor(scene) {
    this.scene = scene;
    this._active = false;
    this._halfLife = 0.15;
    this._blendDuration = 0.5;
    this._elapsed = 0;
    this._inertia = {};
    this._targetPose = {};
    this._prevCaptureTime = null;
    this._prevTime = 0;
    this._removeObs = null;
  }

  /**
   * Capture current bone rotations AND angular velocities.
   * Must be called every frame for at least 2 frames before transition.
   */
  captureInertia(animGroup) {
    if (!animGroup) return;
    const now = performance.now();
    const dt = this._prevCaptureTime ? Math.min((now - this._prevCaptureTime) / 1000, 0.1) : 0.016;
    this._prevCaptureTime = now;

    for (const ta of animGroup.targetedAnimations) {
      const bone = ta.target;
      if (!bone?.name) continue;
      let q;
      if (bone.rotationQuaternion) q = bone.rotationQuaternion.clone();
      else q = BABYLON.Quaternion.RotationYawPitchRoll(bone.rotation.y, bone.rotation.x, bone.rotation.z);

      const prev = this._inertia[bone.name];
      if (prev && dt > 0.001) {
        const diff = prev.q.conjugate().multiply(q);
        const angle = 2 * Math.acos(Math.min(1, Math.abs(diff.w)));
        if (angle > 0.0001) {
          const s = Math.sin(angle / 2);
          if (Math.abs(s) > 0.0001) {
            const speed = angle / dt;
            prev.omega = {
              x: (diff.x / s) * speed,
              y: (diff.y / s) * speed,
              z: (diff.z / s) * speed,
              scalarSpeed: speed
            };
          }
        }
        prev.q = q;
        prev.omega = prev.omega || { x: 0, y: 0, z: 0, scalarSpeed: 0 };
      } else {
        this._inertia[bone.name] = { bone, q, omega: null };
      }
    }
  }

  /**
   * Start inertialized transition toward the target animation.
   * Registers an onAfterAnimationsObservable to apply the blend AFTER
   * the animation system has run, so idle continues for non-targeted bones.
   */
  startTransition(targetAnim, entryFrame, halfLife = 0.15, blendDuration = 0.5) {
    this._halfLife = halfLife;
    this._blendDuration = blendDuration;
    this._elapsed = 0;
    this._active = true;
    this._targetAnim = targetAnim;
    this._entryFrame = entryFrame;
    this._prevTime = performance.now();

    if (this._removeObs) {
      this.scene.onAfterAnimationsObservable.remove(this._removeObs);
      this._removeObs = null;
    }

    // Evaluate target poses at entry frame
    this._targetPose = {};
    for (const ta of targetAnim.targetedAnimations) {
      const bone = ta.target;
      if (!bone?.name) continue;
      const anim = ta.animation;
      if (!anim || anim.targetProperty !== 'rotationQuaternion') continue;
      const keys = anim.getKeys();
      if (!keys || keys.length === 0) continue;
      const idx = Math.min(entryFrame, keys.length - 1);
      this._targetPose[bone.name] = keys[idx].value.clone();
    }

    for (const data of Object.values(this._inertia)) {
      if (!data.omega) data.omega = { x: 0, y: 0, z: 0, scalarSpeed: 0 };
    }

    // Register after-animations callback
    const self = this;
    this._removeObs = this.scene.onAfterAnimationsObservable.add(() => {
      if (!self._active) return;
      const now = performance.now();
      const dt = Math.min((now - self._prevTime) / 1000, 0.1);
      self._prevTime = now;
      self._tickImpl(dt);
    });

    console.log(`[InertializationBlend] Started: halfLife=${halfLife}s, blend=${blendDuration}s, entry=${entryFrame}`);
  }

  /** Core tick — called from after-animations observable */
  _tickImpl(dt) {
    this._elapsed += dt;
    const t = this._elapsed;
    const lambda = Math.LN2 / this._halfLife;
    const damping = Math.exp(-lambda * t);
    const rawBlend = Math.min(t / this._blendDuration, 1);
    const blendW = rawBlend * rawBlend * (3 - 2 * rawBlend);

    for (const [boneName, data] of Object.entries(this._inertia)) {
      const targetQ = this._targetPose[boneName];
      if (!targetQ) continue;
      const bone = data.bone;
      if (!bone) continue;

      const omega = data.omega;
      if (!omega) continue;

      // Coast: extrapolate current pose by damped velocity
      let coastQ = data.q;
      if (omega.scalarSpeed > 0.001 && damping > 0.001) {
        const halfAngle = omega.scalarSpeed * damping * dt * 0.5;
        if (Math.abs(halfAngle) > 1e-10) {
          const s = Math.sin(halfAngle);
          const deltaQ = new BABYLON.Quaternion(
            omega.x * s / omega.scalarSpeed,
            omega.y * s / omega.scalarSpeed,
            omega.z * s / omega.scalarSpeed,
            Math.cos(halfAngle)
          );
          coastQ = data.q.multiply(deltaQ);
        }
      }

      // Blend coast → target
      const resultQ = BABYLON.Quaternion.Slerp(coastQ, targetQ, blendW);
      if (bone.rotationQuaternion) {
        bone.rotationQuaternion.copyFrom(resultQ);
      } else {
        const euler = resultQ.toEulerAngles();
        bone.rotation.set(euler.x, euler.y, euler.z);
      }
    }

    if (t >= this._blendDuration) {
      this._active = false;
      console.log(`[InertializationBlend] Complete at ${t.toFixed(3)}s`);
    }
  }

  get isActive() { return this._active; }
}
