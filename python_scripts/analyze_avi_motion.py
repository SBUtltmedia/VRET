"""
Analyze 105_13.avi: track character position via silhouette centroid.
"""
import cv2
import numpy as np

cap = cv2.VideoCapture("105_13.avi")
if not cap.isOpened():
    print("Failed to open AVI")
    exit(1)

fps = cap.get(cv2.CAP_PROP_FPS)
total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"FPS: {fps}, Total frames: {total}")

positions = []
frame_idx = 0

while True:
    ret, frame = cap.read()
    if not ret:
        break
    if frame_idx % 73 == 0:  # sample ~10 frames
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Threshold to find character (darker than background)
        _, thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            # Largest contour = character
            largest = max(contours, key=cv2.contourArea)
            M = cv2.moments(largest)
            if M['m00'] > 0:
                cx = M['m10'] / M['m00']
                cy = M['m01'] / M['m00']
                area = cv2.contourArea(largest)
                positions.append((frame_idx, cx, cy, area))
                print(f"  Frame {frame_idx}: cx={cx:.0f}, cy={cy:.0f}, area={area:.0f}")
            else:
                positions.append((frame_idx, 0, 0, 0))
                print(f"  Frame {frame_idx}: no centroid")
        else:
            positions.append((frame_idx, 0, 0, 0))
            print(f"  Frame {frame_idx}: no contours")
    frame_idx += 1

cap.release()

if len(positions) >= 2:
    first = positions[0]
    last = positions[-1]
    print(f"\nOverall: cx Δ={last[1]-first[1]:.0f}px, cy Δ={last[2]-first[2]:.0f}px")
    print(f"  ({first[1]:.0f}, {first[2]:.0f}) → ({last[1]:.0f}, {last[2]:.0f})")
