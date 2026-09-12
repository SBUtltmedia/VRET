"""Batch test: generate transition VRMA for multiple pairs and test each."""
import subprocess, sys, os, random

vrma_dir = 'vrma'
gen_script = 'python_scripts/generate_transition_vrma.py'
test_script = 'python_scripts/test_transition.py'
temp_transition = 'vrma/test_batch_transition.vrma'

# Gesture clips (from pool_gesture.txt)
gesture_files = []
with open('pool_gesture.txt') as f:
    gesture_files = [line.strip() for line in f if line.strip()]

if len(gesture_files) < 20:
    print(f"WARNING: only {len(gesture_files)} gesture clips found")
    sys.exit(1)

# Pick 10 random pairs
random.seed(42)
pairs = []
for _ in range(10):
    a = random.choice(gesture_files)
    b = random.choice(gesture_files)
    if a != b:
        pairs.append((a, b))

print(f"Testing {len(pairs)} random gesture->gesture pairs")
pass_count = 0
for i, (a, b) in enumerate(pairs):
    a_path = os.path.join(vrma_dir, a)
    b_path = os.path.join(vrma_dir, b)
    print(f"\n[{i+1}/{len(pairs)}] {a} -> {b}")
    
    # Generate transition
    gen_cmd = f'python {gen_script} "{a_path}" "{b_path}" -o "{temp_transition}" --threshold 15 --fps 60'
    r1 = subprocess.run(gen_cmd, shell=True, capture_output=True, text=True)
    if r1.returncode != 0:
        print(f"  GENERATE FAILED: {r1.stderr}")
        continue
    
    # Test
    test_cmd = f'python {test_script} "{a_path}" "{temp_transition}" "{b_path}" --rot-threshold 15 --pos-threshold 0.05'
    r2 = subprocess.run(test_cmd, shell=True, capture_output=True, text=True)
    
    # Show first few lines of output
    out_lines = r2.stdout.strip().split('\n')
    for line in out_lines:
        if 'PASS' in line or 'FAIL' in line or 'max boundary' in line or 'Worst internal' in line:
            print(f"  {line.strip()}")
        elif 'B=' in line and '<<<' in line:
            print(f"  {line.strip()}")
    
    if r2.returncode == 0:
        pass_count += 1

print(f"\n{'='*50}")
print(f"Passed: {pass_count}/{len(pairs)}")
print(f"{'='*50}")

# Cleanup
if os.path.exists(temp_transition):
    os.remove(temp_transition)
