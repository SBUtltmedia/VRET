/**
 * lifelike-controller.js
 * 
 * A procedural animation controller for Babylon.js VRM models to add 
 * "presence" and "life" through micro-movements, saccades, and natural blinking.
 * Designed to reduce the "uncanny valley" effect in talking-head scenarios.
 */

export class LifelikeController {
  constructor(actor, scene) {
    this.actor = actor; // { mgr, root, morphMap, id }
    this.scene = scene;
    this.enabled = true;

    // --- Configuration ---
    this.config = {
      blink: {
        minInterval: 2.0,
        maxInterval: 6.0,
        duration: 0.15,
        morphNames: ['blink', 'blinkleft', 'blinkright', 'eyeblinkleft', 'eyeblinkright']
      },
      saccade: {
        minInterval: 0.5,
        maxInterval: 3.5,
        strength: 0.08,
        speed: 0.1
      },
      microHead: {
        strength: 0.015,
        frequency: 0.8
      },
      breathing: {
        strength: 0.008,
        frequency: 0.25
      }
    };

    // --- State ---
    this.state = {
      blink: { timer: 0, alpha: 0, active: false },
      saccade: { timer: 0, targetX: 0, targetY: 0, currentX: 0, currentY: 0 },
      breathing: { phase: Math.random() * Math.PI * 2 },
      noisePhase: Math.random() * 1000
    };

    // --- References ---
    const getBone = (name) => {
        if (actor.mgr.humanoid?.getBoneNode) return actor.mgr.humanoid.getBoneNode(name);
        const boneData = actor.mgr.humanoid?.humanBones?.[name];
        if (boneData && boneData.node !== undefined) {
            return actor.mgr.transformNodeCache?.[boneData.node];
        }
        return actor.mgr.humanoidBone?.[name]; // final fallback
    };

    this.bones = {
      head: getBone('head'),
      neck: getBone('neck'),
      leftEye: getBone('leftEye'),
      rightEye: getBone('rightEye'),
      spine: getBone('spine') || getBone('chest')
    };

    // Initialize rotation quaternions if missing
    Object.values(this.bones).forEach(b => {
      if (b) b.rotationQuaternion = b.rotationQuaternion || BABYLON.Quaternion.Identity();
    });

    // Capture base rotations
    this.baseRotations = new Map();
    ['head', 'neck', 'leftEye', 'rightEye', 'spine'].forEach(key => {
      const bone = this.bones[key];
      if (bone) {
        this.baseRotations.set(key, bone.rotationQuaternion?.clone() || BABYLON.Quaternion.Identity());
      }
    });

    // Find blink morph targets (fallback)
    this.blinkTargets = [];
    this.config.blink.morphNames.forEach(name => {
      const mt = actor.morphMap.get(name);
      if (mt) this.blinkTargets.push(mt);
    });

    this._setupTimers();
  }

  _setupTimers() {
    this.state.blink.timer = this.config.blink.minInterval + Math.random() * (this.config.blink.maxInterval - this.config.blink.minInterval);
    this.state.saccade.timer = this.config.saccade.minInterval + Math.random() * (this.config.saccade.maxInterval - this.config.saccade.minInterval);
  }

  update(dt, isSpeaking = false) {
    if (!this.enabled) return;
    const now = performance.now() / 1000;

    this._updateBlinking(dt);
    this._updateSaccades(dt);
    this._updateMicroMovement(now);
    this._updateBreathing(now);
    this._updateIdleState(dt, isSpeaking);
  }

  _updateIdleState(dt, isSpeaking) {
    const em = this.actor.mgr.expressionManager || this.actor.mgr.ext10?.expressionManager;
    if (!em) return;

    // Smoothly transition to "relaxed" when not speaking
    // Reduced intensity to 0.15 to avoid "sleepy" look
    const targetRelaxed = isSpeaking ? 0 : 0.15;
    const current = em.getValue('relaxed') || 0;
    const next = current + (targetRelaxed - current) * 0.04;
    em.setValue('relaxed', next);
  }

  _updateBlinking(dt) {
    const s = this.state.blink;
    const em = this.actor.mgr.expressionManager || this.actor.mgr.ext10?.expressionManager;

    if (s.active) {
      s.alpha += dt / this.config.blink.duration;
      if (s.alpha >= 1.0) {
        s.alpha = 0;
        s.active = false;
        s.timer = this.config.blink.minInterval + Math.random() * (this.config.blink.maxInterval - this.config.blink.minInterval);
        
        // Explicitly clear blink values when done
        if (em) {
          em.setValue('blink', 0);
        } else {
          this.blinkTargets.forEach(mt => mt.influence = 0);
        }
      } else {
        const influence = Math.sin(s.alpha * Math.PI);
        if (em) {
          // Drive standard VRM blink presets
          const current = em.getValue('blink') || 0;
          em.setValue('blink', Math.max(current, influence));
        } else {
          this.blinkTargets.forEach(mt => {
            mt.influence = Math.max(mt.influence, influence);
          });
        }
      }
    } else {
      s.timer -= dt;
      if (s.timer <= 0) {
        s.active = true;
        s.alpha = 0;
      }
    }
  }

  _updateSaccades(dt) {
    const s = this.state.saccade;
    s.timer -= dt;
    if (s.timer <= 0) {
      s.targetX = (Math.random() - 0.5) * this.config.saccade.strength;
      s.targetY = (Math.random() - 0.5) * this.config.saccade.strength;
      s.timer = this.config.saccade.minInterval + Math.random() * (this.config.saccade.maxInterval - this.config.saccade.minInterval);
    }

    // Smooth lerp to target saccade
    s.currentX += (s.targetX - s.currentX) * this.config.saccade.speed;
    s.currentY += (s.targetY - s.currentY) * this.config.saccade.speed;

    if (this.bones.leftEye && this.bones.rightEye) {
      const rot = BABYLON.Quaternion.RotationYawPitchRoll(s.currentX, s.currentY, 0);
      
      const baseL = this.baseRotations.get('leftEye');
      const baseR = this.baseRotations.get('rightEye');
      
      this.bones.leftEye.rotationQuaternion = rot.multiply(baseL);
      this.bones.rightEye.rotationQuaternion = rot.multiply(baseR);
    }
  }

  _updateMicroMovement(now) {
    if (!this.bones.head) return;

    const p = this.state.noisePhase + now * this.config.microHead.frequency;
    
    // Multi-layered sine waves to simulate noise
    const noiseX = Math.sin(p) * 0.5 + Math.sin(p * 2.1) * 0.3 + Math.sin(p * 0.4) * 0.2;
    const noiseZ = Math.cos(p * 0.9) * 0.5 + Math.cos(p * 1.7) * 0.3 + Math.cos(p * 0.5) * 0.2;
    
    const tiltX = noiseX * this.config.microHead.strength;
    const tiltZ = noiseZ * this.config.microHead.strength;

    const rot = BABYLON.Quaternion.FromEulerAngles(tiltX, 0, tiltZ);
    const baseHead = this.baseRotations.get('head');
    this.bones.head.rotationQuaternion = baseHead.multiply(rot);

    if (this.bones.neck) {
        const baseNeck = this.baseRotations.get('neck');
        this.bones.neck.rotationQuaternion = baseNeck.multiply(BABYLON.Quaternion.FromEulerAngles(tiltX * 0.5, 0, tiltZ * 0.5));
    }
  }

  _updateBreathing(now) {
    if (!this.bones.spine) return;

    const p = now * this.config.breathing.frequency + this.state.breathing.phase;
    const breath = (Math.sin(p) * 0.5 + 0.5) * this.config.breathing.strength;

    // Breathing usually tilts the spine slightly back and expands the chest
    const rot = BABYLON.Quaternion.FromEulerAngles(-breath, 0, 0);
    const baseSpine = this.baseRotations.get('spine');
    this.bones.spine.rotationQuaternion = baseSpine.multiply(rot);
  }
}
