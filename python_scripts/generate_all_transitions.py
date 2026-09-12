"""
generate_all_transitions.py

Batch-generate all transition VRMAs for a scene timeline JSON.

Reads the timeline, identifies consecutive clips by the same actor, and generates
transition VRMAs between each pair (including idle→first and last→idle).

Usage:
  python generate_all_transitions.py plays/traffic_scene.json
"""

import json
import os
import sys
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
TRANSITION_SCRIPT = os.path.join(SCRIPT_DIR, 'generate_transition_vrma.py')
TRANSITION_DIR = os.path.join(PROJECT_ROOT, 'vrma', 'transitions')


def resolve_vrma_path(ref):
    """Resolve a clip reference to an absolute VRMA path."""
    if not ref:
        return None
    if isinstance(ref, dict):
        ref = ref.get('url', '')
    if ref.startswith('http') or ref.startswith('/'):
        return None  # remote URL, skip
    # Relative to plays/scene.html, so prefix with project root
    if ref.startswith('vrma/'):
        return os.path.join(PROJECT_ROOT, ref)
    return os.path.join(PROJECT_ROOT, 'plays', ref)


def transition_filename(clip_a, clip_b):
    """Generate a deterministic filename for the transition between two clips."""
    name_a = os.path.splitext(os.path.basename(clip_a))[0]
    name_b = os.path.splitext(os.path.basename(clip_b))[0]
    return f"{name_a}_to_{name_b}.vrma"


def generate_one(pair_name, path_a, path_b, threshold=15.0):
    """Generate a single transition VRMA."""
    out_path = os.path.join(TRANSITION_DIR, transition_filename(path_a, path_b))
    if os.path.exists(out_path):
        print(f"  [SKIP] {pair_name}: already exists")
        return out_path

    print(f"  [GEN]  {pair_name}")

    result = subprocess.run(
        [sys.executable, TRANSITION_SCRIPT, path_a, path_b,
         '--output', out_path, '--threshold', str(threshold)],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )

    if result.returncode != 0:
        print(f"  [FAIL] {pair_name}: {result.stderr.strip()}")
        return None

    # Print key output lines
    for line in result.stdout.split('\n'):
        if any(kw in line for kw in ['Max angle', 'Transition frames', 'Written', 'Hips']):
            print(f"    {line.strip()}")

    return out_path


def generate_all(scene_json_path, threshold=15.0):
    if not os.path.isfile(scene_json_path):
        print(f"ERROR: Scene file not found: {scene_json_path}")
        return False

    with open(scene_json_path, 'r') as f:
        scene = json.load(f)

    os.makedirs(TRANSITION_DIR, exist_ok=True)

    print(f"Scene: {scene.get('metadata', {}).get('title', os.path.basename(scene_json_path))}")
    print(f"Threshold: {threshold}°")
    print()

    # For each actor, track their clip sequence
    actor_clips = {}  # {actor_id: [clip_path, ...]}

    # Collect idle clips
    for actor_def in scene.get('actors', []):
        aid = actor_def.get('id', '')
        idle = actor_def.get('idleClip')
        if idle:
            resolved = resolve_vrma_path(idle)
            if resolved:
                actor_clips[aid] = [resolved]

    # Collect gesture clips from timeline
    for ev in scene.get('timeline', []):
        aid = ev.get('actor', '')
        clip_def = ev.get('clip') or (ev.get('layers') or {}).get('BODY')
        if clip_def and aid in actor_clips:
            resolved = resolve_vrma_path(clip_def)
            if resolved:
                actor_clips[aid].append(resolved)

    total_generated = 0
    total_skipped = 0
    total_failed = 0

    for aid, clips in actor_clips.items():
        if len(clips) < 2:
            print(f"Actor '{aid}': only {len(clips)} clip(s), no transitions needed")
            continue

        print(f"\n-- Actor: {aid} ({len(clips)} clips) --")

        for i in range(len(clips) - 1):
            path_a = clips[i]
            path_b = clips[i + 1]

            if not os.path.isfile(path_a):
                print(f"  [SKIP] Missing source: {os.path.basename(path_a)}")
                total_skipped += 1
                continue
            if not os.path.isfile(path_b):
                print(f"  [SKIP] Missing target: {os.path.basename(path_b)}")
                total_skipped += 1
                continue

            pair_name = f"{os.path.basename(path_a)} -> {os.path.basename(path_b)}"
            out_path = generate_one(pair_name, path_a, path_b, threshold)

            if out_path:
                total_generated += 1
            else:
                total_failed += 1

    print(f"\n{'='*60}")
    print(f"Done: {total_generated} generated, {total_skipped} skipped, {total_failed} failed")
    print(f"Transitions in: {TRANSITION_DIR}")
    return total_failed == 0


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Batch-generate all transition VRMAs for a scene')
    parser.add_argument('scene_json', nargs='?',
                        default=os.path.join(PROJECT_ROOT, 'plays', 'traffic_scene.json'),
                        help='Path to scene JSON file')
    parser.add_argument('--threshold', type=float, default=15.0,
                        help='Per-frame rotation threshold in degrees')
    args = parser.parse_args()

    success = generate_all(args.scene_json, threshold=args.threshold)
    sys.exit(0 if success else 1)
