"""
Analyze 105_13.avi: frame-to-frame differencing + phase-based walking detection.
"""
import cv2
import numpy as np
import json

cap = cv2.VideoCapture("105_13.avi")
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

ret, prev = cap.read()
if not ret:
    exit(1)
prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 0)

per_frame = []
frame_idx = 0
stride_frames = []

while True:
    ret, frame = cap.read()
    if not ret:
        break
    frame_idx += 1

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # Frame-to-frame diff (instantaneous motion)
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
    motion_px = cv2.countNonZero(thresh)
    per_frame.append(motion_px)

    prev_gray = gray

cap.release()

# Detect walking cycles by motion pixel peaks
# Walking has periodic strong motion (legs swinging) vs stationary gestures (arms only)
motion = np.array(per_frame)
mean_motion = float(motion.mean())
max_motion = float(motion.max())
std_motion = float(motion.std())

# Find stride-like peaks (walking steps produce periodic high-motion frames)
from scipy.signal import find_peaks
# Smooth
smoothed = np.convolve(motion, np.ones(5)/5, mode='same')
peaks, props = find_peaks(smoothed, height=mean_motion*1.2, distance=10)

print(f"Total frames: {total}")
print(f"Motion pixels: mean={mean_motion:.0f}, std={std_motion:.0f}, max={max_motion:.0f}")
print(f"Detected {len(peaks)} motion peaks (possible steps)")

if len(peaks) >= 4:
    intervals = np.diff(peaks)
    mean_interval = intervals.mean()
    print(f"Mean peak interval: {mean_interval:.1f} frames ({mean_interval/30:.2f}s)")

    # Walking typically has regular intervals (0.4-0.7s per step)
    step_freq = 30.0 / mean_interval
    print(f"Step frequency: {step_freq:.1f} Hz ({step_freq*60:.0f} steps/min)")
    if 0.4 <= mean_interval/30 <= 1.0:
        print("Walking classification: CONSISTENT WITH WALKING (regular stride)")
    else:
        print("Walking classification: UNCLEAR (irregular)")
elif len(peaks) == 0:
    print("Walking classification: NO WALKING (no motion peaks)")
else:
    print("Walking classification: INCONCLUSIVE (too few peaks)")

# Print all peak values
print(f"\nPeak frames: {peaks.tolist()}")
