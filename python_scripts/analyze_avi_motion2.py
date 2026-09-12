"""
Analyze 105_13.avi: use frame differencing to track character motion.
"""
import cv2
import numpy as np

cap = cv2.VideoCapture("105_13.avi")
fps = cap.get(cv2.CAP_PROP_FPS)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"FPS: {fps}, Total frames: {total}")

ret, prev = cap.read()
if not ret:
    exit(1)
prev_gray = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
prev_gray = cv2.GaussianBlur(prev_gray, (5, 5), 0)

positions = []
frame_idx = 0

# Process every 30th frame (1 per second at 30fps)
while True:
    ret, frame = cap.read()
    if not ret:
        break
    frame_idx += 1

    if frame_idx % 30 != 0:
        continue

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # Difference from first frame
    diff = cv2.absdiff(prev_gray, gray)
    _, thresh = cv2.threshold(diff, 30, 255, cv2.THRESH_BINARY)
    thresh = cv2.erode(thresh, None, iterations=1)
    thresh = cv2.dilate(thresh, None, iterations=2)

    motion_pixels = cv2.countNonZero(thresh)
    M = cv2.moments(thresh)
    if M['m00'] > 500:
        cx = M['m10'] / M['m00']
        cy = M['m01'] / M['m00']
    else:
        cx, cy = 0, 0

    positions.append((frame_idx, cx, cy, motion_pixels))
    print(f"  Frame {frame_idx:3d}: cx={cx:6.0f} cy={cy:6.0f} motion_px={motion_pixels:5d}")

cap.release()

if len(positions) >= 2:
    first = positions[0]
    last = positions[-1]
    dx = last[1] - first[1]
    dy = last[2] - first[2]
    print(f"\nFrame 1 vs {last[0]}:")
    print(f"  cx: {first[1]:.0f} -> {last[1]:.0f}  (dx={dx:.0f}px)")
    print(f"  cy: {first[2]:.0f} -> {last[2]:.0f}  (dy={dy:.0f}px)")
