/**
 * Timeline.js - Synchronous Audio Event Processor, VRMA Retargeter, and Array-Based Expression Streamer
 * Support Accumulative Root Motion and Orientation across consecutive timeline steps with smooth animation blending.
 */
export class TimelineManager {
    constructor(stage, actors, opts = {}) {
        this.stage = stage;
        this.actors = actors;
        this._fixRootPosition = opts.fixRootPosition !== false;
        
        this.progEl = document.getElementById("prog-bar");
        this.speakerEl = document.getElementById("speaker");
        this.lineEl = document.getElementById("line");
        this.dumpEl = document.getElementById("tracking-dump");
        
        this._vrmaCache = {};
        this._chainData = [];
        this._currentSeqIdx = 0;
        
        // Store cumulative world transform states for actors, initialized from scene
        this.cumulativeTransforms = {};
        for (const [id, actor] of Object.entries(actors)) {
            // Ensure rotationQuaternion exists for accumulation
            if (!actor.root.rotationQuaternion) {
                actor.root.rotationQuaternion = BABYLON.Quaternion.RotationYawPitchRoll(actor.root.rotation.y, actor.root.rotation.x, actor.root.rotation.z);
            }
            
            // Force Officer to face camera (+Z) if they aren't already
            if (id === 'officer' && Math.abs(actor.root.rotationQuaternion.toEulerAngles().y) < 0.1) {
                console.log("[Timeline] Force-aligning Officer to face camera.");
                BABYLON.Quaternion.RotationYawPitchRollToRef(Math.PI, 0, 0, actor.root.rotationQuaternion);
            }

            this.cumulativeTransforms[id] = {
                position: actor.root.position.clone(),
                rotation: actor.root.rotationQuaternion.clone()
            };
        }

        this._setupGlobalTick();
    }

    _setupGlobalTick() {
        this.stage.scene.onBeforeRenderObservable.add(() => {
            const now = performance.now() / 1000;
            let hudHtml = "";

            for (const actor of Object.values(this.actors)) {
                actor.tickProceduralHead(now, actor.activeExpressions || []);

                if (actor.activeExpressions && actor.activeExpressions.length > 0) {
                    actor.activeExpressions.forEach(e => {
                        hudHtml += `<div class="track-row"><span>${actor.id}.${e.name}</span><span class="track-val">${e.val.toFixed(2)}</span></div>`;
                    });
                }
            }

            if (this.dumpEl) {
                this.dumpEl.innerHTML = hudHtml || "<div style='opacity:0.4'>No active blendshapes</div>";
            }

            // Smooth camera follow for current speaker
            if (this.currentSpeaker && this.actors[this.currentSpeaker]) {
                const actor = this.actors[this.currentSpeaker];
                const hips = actor.mgr.humanoidBone["hips"];
                if (hips) {
                    const worldHips = hips.getAbsolutePosition();
                    const target = new BABYLON.Vector3(worldHips.x * 0.4, 1.1, worldHips.z * 0.4);
                    const cam = this.stage.perspCam || this.stage.camera;
                    if (cam) cam.setTarget(BABYLON.Vector3.Lerp(cam.target, target, 0.05));
                }
            }
        });
    }

    resolveAsset(p) {
        return (p && !p.startsWith("http")) ? "../" + p : p;
    }

    async loadAndRetargetVRMA(actor, url, name) { 
        const scene = this.stage.scene;
        const managersBefore = new Set(scene.metadata?.vrmAnimationManagers ?? []);
        
        let container;
        try { 
            container = await BABYLON.LoadAssetContainerAsync(url, scene); 
        } catch (e) { 
            console.error("[Timeline Engine] Failed to load VRMA layer:", url, e); 
            return null; 
        }

        const managersAfter = scene.metadata?.vrmAnimationManagers ?? [];
        const vrmAnimMgr = managersAfter.find(m => !managersBefore.has(m));
        const srcGroup = container.animationGroups[0];

        if (!vrmAnimMgr || !srcGroup) {
            container.dispose();
            return null;
        }

        const mapNodeNames = new Map();
        srcGroup.targetedAnimations.forEach((ta, i) => {
            const boneName = vrmAnimMgr.animationMap.get(i);
            const bone = actor.mgr.humanoidBone[boneName];
            if (bone && ta.target?.name) {
                mapNodeNames.set(ta.target.name, bone.name);
            }
        });

        const remapped = actor.vrmAvatar.retargetAnimationGroup(srcGroup, {
            animationGroupName: `${actor.id}-${name}-${Date.now()}`,
            fixAnimations: true,
            fixRootPosition: false,
            rootNodeName: actor.mgr.humanoidBone["hips"]?.name,
            groundReferenceNodeName: actor.mgr.humanoidBone["leftFoot"]?.name,
            mapNodeNames,
        });

        container.dispose();
        return remapped;
    }

    _getHipsWorldPos(actor) {
        const hips = actor.mgr.humanoidBone["hips"];
        if (!hips) return null;
        hips.computeWorldMatrix(true);
        return hips.getAbsolutePosition().clone();
    }

    _getHipsWorldRotationY(actor) {
        const hips = actor.mgr.humanoidBone["hips"];
        if (!hips) return 0;
        const wm = hips.getWorldMatrix();
        const forward = new BABYLON.Vector3(wm.m[8], wm.m[9], wm.m[10]);
        return Math.atan2(forward.x, forward.z);
    }

    _alignRootToAccumulated(actor) {
        const state = this.cumulativeTransforms[actor.id];
        if (!state) return;
        actor.root.rotationQuaternion = null;
        const hips = actor.mgr.humanoidBone["hips"];
        if (!hips) return;
        const targetRotY = state.rotation.toEulerAngles().y;
        for (let iter = 0; iter < 10; iter++) {
            actor.root.computeWorldMatrix(true);
            hips.computeWorldMatrix(true);
            const actualPos = hips.getAbsolutePosition();
            const dx = state.position.x - actualPos.x;
            const dz = state.position.z - actualPos.z;
            const actualRotY = this._getHipsWorldRotationY(actor);
            let dRot = targetRotY - actualRotY;
            while (dRot < -Math.PI) dRot += Math.PI * 2;
            while (dRot > Math.PI) dRot -= Math.PI * 2;
            if (Math.abs(dx) < 1e-4 && Math.abs(dz) < 1e-4 && Math.abs(dRot) < 1e-4) break;
            actor.root.position.x += dx;
            actor.root.position.z += dz;
            actor.root.rotation.y += dRot;
        }
        actor.root.computeWorldMatrix(true);
    }

    _fadeOutAndDispose(groups, durationMs = 300) {
        if (!groups || groups.length === 0) return;
        groups.forEach(g => {
            let weight = g.weight;
            const step = 0.1;
            const interval = durationMs * step;
            const timer = setInterval(() => {
                weight -= step;
                if (weight <= 0) {
                    g.weight = 0;
                    g.stop();
                    g.dispose();
                    clearInterval(timer);
                } else {
                    g.weight = weight;
                }
            }, interval);
        });
    }

    _fadeInGroups(groups, durationMs = 300) {
        groups.forEach(g => {
            g.weight = 0.0;
            g.start(false, 1.0, g.from, g.to, false);
            let weight = 0.0;
            const step = 0.1;
            const interval = durationMs * step;
            const timer = setInterval(() => {
                weight += step;
                if (weight >= 1.0) {
                    g.weight = 1.0;
                    clearInterval(timer);
                } else {
                    g.weight = weight;
                }
            }, interval);
        });
    }

    _snapshotBoneTransforms(actor) {
        const snap = {};
        if (!actor.curGroups?.length) return snap;
        for (const g of actor.curGroups) {
            for (const ta of g.targetedAnimations) {
                const bone = ta.target;
                if (bone?.name) {
                    snap[bone.name] = {
                        pos: bone.position.clone(),
                        rot: bone.rotationQuaternion?.clone() ?? BABYLON.Quaternion.Identity(),
                        scale: bone.scaling.clone(),
                    };
                }
            }
        }
        return snap;
    }

    _logBoneRotationDeltas(actor, stepName) {
        const oldSnapshot = this._snapshotBoneTransforms(actor);
        if (!Object.keys(oldSnapshot).length) return;
        const seen = new Set();
        const deltas = [];
        for (const g of actor.curGroups || []) {
            for (const ta of g.targetedAnimations) {
                const bone = ta.target;
                if (!bone?.name || seen.has(bone.name)) continue;
                seen.add(bone.name);
                const snap = oldSnapshot[bone.name];
                if (!snap || !bone.rotationQuaternion) continue;
                const dot = BABYLON.Quaternion.Dot(snap.rot, bone.rotationQuaternion);
                const angle = 2 * Math.acos(Math.min(1, Math.abs(dot))) * 57.3;
                if (angle > 5) deltas.push({ bone: bone.name, deg: angle });
            }
        }
        deltas.sort((a, b) => b.deg - a.deg);
        if (deltas.length > 0) {
            let line = `[Timeline] Bone rotation deltas at ${stepName}:`;
            const top = deltas.slice(0, 5);
            for (const d of top) line += ` ${d.bone}=${d.deg.toFixed(1)}°`;
            if (deltas.length > 5) line += ` (+${deltas.length - 5} more)`;
            console.log(line);
        }
    }

    async _manualBoneBlend(actor, oldSnapshot, blendMs) {
        if (blendMs <= 0 || !Object.keys(oldSnapshot).length) return;
        const blendStart = performance.now();
        const blendEnd = blendStart + blendMs;
        while (performance.now() < blendEnd) {
            await new Promise(r => requestAnimationFrame(r));
            const raw = Math.min((performance.now() - blendStart) / blendMs, 1);
            const t = raw * raw * (3 - 2 * raw);
            for (const g of actor.curGroups || []) {
                for (const ta of g.targetedAnimations) {
                    const bone = ta.target;
                    if (!bone?.name) continue;
                    const snap = oldSnapshot[bone.name];
                    if (!snap) continue;
                    bone.position = BABYLON.Vector3.Lerp(snap.pos, bone.position, t);
                    if (bone.rotationQuaternion) {
                        bone.rotationQuaternion = BABYLON.Quaternion.Slerp(snap.rot, bone.rotationQuaternion, t);
                    }
                    bone.scaling = BABYLON.Vector3.Lerp(snap.scale, bone.scaling, t);
                }
            }
        }
    }

    _snapshotFrame(actor, clipName) {
        const wp = this._getHipsWorldPos(actor);
        if (!wp) return;
        const wrY = this._getHipsWorldRotationY(actor);
        this._chainData.push({
            clip: clipName,
            px: +wp.x.toFixed(4),
            pz: +wp.z.toFixed(4),
            ry: +(wrY * 57.3).toFixed(2),
        });
    }

    _publishWorldPos(actor) {
        const wp = this._getHipsWorldPos(actor);
        if (!wp) return;
        const wrY = this._getHipsWorldRotationY(actor);
        document.body.setAttribute("data-world-pos",
            `${wp.x.toFixed(3)},${wp.y.toFixed(3)},${wp.z.toFixed(3)},${wrY.toFixed(4)}`
        );
    }

    async _loadVRMACached(actor, url, name, retargetOpts = {}) {
        const cacheKey = `${actor.id}::${url}`;
        if (this._vrmaCache[cacheKey]) {
            return this._vrmaCache[cacheKey].clone(`${actor.id}-${name}-${Date.now()}`);
        }
        const scene = this.stage.scene;
        const beforeSet = new Set(scene.metadata?.vrmAnimationManagers ?? []);
        const container = await BABYLON.LoadAssetContainerAsync(this.resolveAsset(url), scene);
        const mgrs = scene.metadata?.vrmAnimationManagers ?? [];
        const vrmAnimMgr = mgrs.find(m => !beforeSet.has(m));
        const group = container.animationGroups[0];
        if (!vrmAnimMgr?.animationMap || !group) {
            container.dispose();
            return null;
        }
        const mapNodeNames = new Map();
        group.targetedAnimations.forEach((ta, i) => {
            const boneName = vrmAnimMgr.animationMap.get(i);
            const bone = actor.mgr.humanoidBone[boneName];
            if (bone && ta.target?.name) {
                mapNodeNames.set(ta.target.name, bone.name);
            }
        });
        const remapped = actor.vrmAvatar.retargetAnimationGroup(group, {
            animationGroupName: `${actor.id}-${name}-${Date.now()}`,
            fixAnimations: true,
            fixRootPosition: retargetOpts.fixRootPosition ?? false,
            rootNodeName: actor.mgr.humanoidBone["hips"]?.name,
            groundReferenceNodeName: actor.mgr.humanoidBone["leftFoot"]?.name,
            mapNodeNames,
        });
        container.dispose();
        if (remapped) {
            this._vrmaCache[cacheKey] = remapped;
            return remapped.clone(`${actor.id}-${name}-${Date.now()}`);
        }
        return null;
    }

    async playSequential(actorId, sequence) {
        const actor = this.actors[actorId];
        if (!actor) return;
        if (this._currentSeqIdx >= sequence.length) {
            console.log("[Timeline] Sequence complete.");
            document.body.setAttribute("data-status", "complete");
            return;
        }
        const step = sequence[this._currentSeqIdx];
        this._currentSeqIdx++;
        console.log(`[Timeline] Playing: ${step.name}`);
        document.body.setAttribute("data-current", step.name);
        document.body.setAttribute("data-status", "playing");

        const animGroup = await this._loadVRMACached(actor, step.clip, step.name, { fixRootPosition: this._fixRootPosition });
        if (!animGroup) {
            console.error("[Timeline] Failed to load VRMA.");
            return;
        }

        const fps = 60;
        const playFrom = step.from ?? animGroup.from;
        const playTo = step.to ?? animGroup.to;
        const duration = (playTo - playFrom) / (fps * (animGroup.speedRatio || 1));
        console.log(`[Timeline] Range: ${playFrom}-${playTo} (${duration.toFixed(2)}s)`);
        document.body.setAttribute("data-duration", duration.toFixed(3));

        const oldSnapshot = this._snapshotBoneTransforms(actor);

        let animT = 0;
        const scene = this.stage.scene;
        const onRender = () => { animT += scene.deltaTime / 1000; };
        scene.onBeforeRenderObservable.add(onRender);

        const state = this.cumulativeTransforms[actor.id];
        const hips = actor.mgr.humanoidBone["hips"];
        if (state && this._currentSeqIdx <= 1) {
            state.position.copyFrom(this._getHipsWorldPos(actor) ?? BABYLON.Vector3.Zero());
            const curRotY = this._getHipsWorldRotationY(actor);
            BABYLON.Quaternion.RotationYawPitchRollToRef(curRotY, 0, 0, state.rotation);
        }

        animGroup.start(false);
        animGroup.goToFrame(playFrom);
        if (hips) hips.computeWorldMatrix(true);

        this._alignRootToAccumulated(actor);

        if (this._currentSeqIdx > 1) {
            this._logBoneRotationDeltas(actor, step.name);
        }

        if (actor.curGroups?.length) {
            actor.curGroups.forEach(g => { g.stop(); g.dispose(); });
        }
        actor.curGroups = [animGroup];

        const blendMs = this._currentSeqIdx > 1
            ? (step.blend ?? 200)
            : 0;
        await this._manualBoneBlend(actor, oldSnapshot, blendMs);

        this._publishWorldPos(actor);
        document.body.setAttribute("data-frame", "start");

        while (animT < duration) {
            await new Promise(r => requestAnimationFrame(r));
            this._snapshotFrame(actor, step.name);
        }

        scene.onBeforeRenderObservable.removeCallback(onRender);

        if (hips) hips.computeWorldMatrix(true);
        const endWorldPos = this._getHipsWorldPos(actor);
        const endWorldRotY = this._getHipsWorldRotationY(actor);
        if (state && endWorldPos) {
            state.position.copyFrom(endWorldPos);
            BABYLON.Quaternion.RotationYawPitchRollToRef(endWorldRotY, 0, 0, state.rotation);
        }

        this._publishWorldPos(actor);
        document.body.setAttribute("data-frame", "end");

        this.playSequential(actorId, sequence);
    }

    async playEvent(event) {
        const actor = this.actors[event.actor];
        if (!actor) return;

        this.currentSpeaker = event.actor;
        this.speakerEl.textContent = event.actor.toUpperCase();
        this.lineEl.textContent = event.description ?? "";

        const state = this.cumulativeTransforms[event.actor];
        const hips = actor.mgr.humanoidBone["hips"];

        // Capture accumulated Hips world position from previous clips
        if (actor.curGroups.length > 0 && hips) {
            const curPos = this._getHipsWorldPos(actor);
            state.position.copyFrom(curPos);
            const curRotY = this._getHipsWorldRotationY(actor);
            BABYLON.Quaternion.RotationYawPitchRollToRef(curRotY, 0, 0, state.rotation);
        }

        // Align root so Hips world matches accumulated state (iterative convergence)
        this._alignRootToAccumulated(actor);

        Object.values(this.actors).forEach(a => a.resetFace());

        // C. Load new layers SEQUENTIALLY
        const layers = event.layers || {};
        if (event.clip && !layers.BODY) layers.BODY = event.clip;

        const newGroups = [];
        for (const [name, url] of Object.entries(layers)) {
            if (name === "FACE") continue; 
            const g = await this.loadAndRetargetVRMA(actor, this.resolveAsset(url), name);
            if (g) newGroups.push(g);
        }
        
        // D. Cross-fade between clips
        this._fadeOutAndDispose(actor.curGroups, 300);
        actor.curGroups = newGroups;
        this._fadeInGroups(newGroups, 300);

        if (event.audio) {
            const audio = new Audio(this.resolveAsset(event.audio));
            let trackingData = null;

            if (event.lipSync) {
                try { 
                    trackingData = await fetch(this.resolveAsset(event.lipSync)).then(r => r.json()); 
                } catch(e) { }
            }

            let renderObs = this.stage.scene.onBeforeRenderObservable.add(() => {
                const clock = audio.currentTime;
                const ratio = audio.duration > 0 ? clock / audio.duration : 0;
                this.progEl.style.width = (ratio * 100).toFixed(1) + "%";

                if (trackingData && trackingData.frames && trackingData.names) {
                    actor.activeExpressions = actor.face.evaluateInterpolated(trackingData.names, trackingData.frames, clock);
                } 
            });

            await new Promise(res => {
                audio.onended = () => { 
                    this.stage.scene.onBeforeRenderObservable.remove(renderObs); 
                    res(); 
                };
                audio.onerror = () => {
                    this.stage.scene.onBeforeRenderObservable.remove(renderObs);
                    res();
                };
                audio.play().catch(res);
            });
        }
        this.progEl.style.width = "0%";
    }

    async run(timeline) {
        for (let i = 0; i < timeline.length; i++) {
            await this.playEvent(timeline[i]);
            await new Promise(r => setTimeout(r, 400));
        }
        this.speakerEl.textContent = "";
        this.lineEl.textContent = "— end —";
    }
}
