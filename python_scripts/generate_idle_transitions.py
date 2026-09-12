"""
Generate idle-related transition VRMAs for the traffic scene.

Produces:
  - gesture->idle: for each event clip -> the actor's idle clip (12 pairs)
  - idle->gesture: for each event clip EXCEPT the first per actor (10 pairs)
  - Keeps the 2 existing idle->first-gesture transitions

Usage: python generate_idle_transitions.py plays/traffic_scene.json
"""
import json
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))
from generate_transition_vrma import generate_transition

VRMA_DIR = 'vrma'
TRANS_DIR = os.path.join(VRMA_DIR, 'transitions')
THRESHOLD = 15.0

def stem(path):
    return os.path.splitext(os.path.basename(path))[0]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python generate_idle_transitions.py scenes/traffic_scene.json')
        sys.exit(1)

    with open(sys.argv[1], 'r', encoding='utf-8') as f:
        scene = json.load(f)

    actor_idle = {}
    for a in scene.get('actors', []):
        idle_path = a.get('idleClip', '')
        actor_idle[a['id']] = stem(idle_path)

    actor_events = {}
    for evt in scene.get('timeline', []):
        aid = evt['actor']
        clip_path = evt.get('clip', '')
        actor_events.setdefault(aid, []).append(stem(clip_path))

    total = 0
    skipped = 0
    failed = 0

    os.makedirs(TRANS_DIR, exist_ok=True)

    for aid, clips in actor_events.items():
        idle_name = actor_idle.get(aid)
        if not idle_name:
            print(f"WARNING: no idle clip for actor {aid}, skipping")
            continue

        idle_path = os.path.join(VRMA_DIR, f'{idle_name}.vrma')
        if not os.path.exists(idle_path):
            print(f"WARNING: idle file not found: {idle_path}")
            continue

        print(f"\n-- Actor: {aid} (idle={idle_name}) --")

        for cname in clips:
            cpath = os.path.join(VRMA_DIR, f'{cname}.vrma')
            if not os.path.exists(cpath):
                print(f"  [SKIP] clip missing: {cpath}")
                skipped += 1
                continue

            out_name = f'{cname}_to_{idle_name}.vrma'
            out_path = os.path.join(TRANS_DIR, out_name)

            if os.path.exists(out_path):
                print(f"  [SKIP] {out_name} (exists)")
                skipped += 1
                continue

            print(f"  [GEN]  {out_name}")
            ok = generate_transition(cpath, idle_path, out_path, threshold_deg=THRESHOLD)
            if ok:
                total += 1
            else:
                failed += 1

        for i, cname in enumerate(clips):
            if i == 0:
                continue

            clip_path = os.path.join(VRMA_DIR, f'{cname}.vrma')
            if not os.path.exists(clip_path):
                print(f"  [SKIP] clip missing: {clip_path}")
                skipped += 1
                continue

            out_name = f'{idle_name}_to_{cname}.vrma'
            out_path = os.path.join(TRANS_DIR, out_name)

            if os.path.exists(out_path):
                print(f"  [SKIP] {out_name} (exists)")
                skipped += 1
                continue

            print(f"  [GEN]  {out_name}")
            ok = generate_transition(idle_path, clip_path, out_path, threshold_deg=THRESHOLD)
            if ok:
                total += 1
            else:
                failed += 1

    print(f"\nDone: {total} generated, {skipped} skipped, {failed} failed")
