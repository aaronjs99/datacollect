import csv
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

DATAFILE = "./data/Take 2025-05-14 05.25.51 PM.csv"

# Extract 'Name' row using csv.reader
with open(DATAFILE, newline='') as f:
    reader = csv.reader(f)
    for i in range(4):
        row = next(reader)
        if i == 3:
            names_row = row  # This row contains marker names like "robot_link:Marker 001"

# Load numeric data
df = pd.read_csv(DATAFILE, skiprows=7)

# Parse time
time = pd.to_numeric(df["Time (Seconds)"], errors="coerce")
df = df.dropna(subset=["Time (Seconds)"]).reset_index(drop=True)
time = time.values - time.values[0]  # Normalize to start at 0

# Filter robot_link marker columns and remove duplicates
seen = set()
unique_triplets = []
i = 0

while i < len(names_row) - 2:
    name = names_row[i]
    if (
        isinstance(name, str)
        and name.startswith("robot_link:Marker")
        and i + 2 < len(df.columns)
    ):
        marker_id = name  # full identifier (e.g. "robot_link:Marker 001")
        if marker_id not in seen:
            seen.add(marker_id)
            triplet = [df.columns[i], df.columns[i+1], df.columns[i+2]]
            unique_triplets.append(triplet)
        i += 3  # Skip next 2 since it's part of the triplet
    else:
        i += 1  # Continue searching

# Extract marker trajectories
marker_trajectories = []
for triplet in unique_triplets:
    try:
        marker_df = df[triplet].astype(float)
        marker_trajectories.append(marker_df.values)
    except Exception as e:
        print(f"Skipping {triplet}: {e}")

marker_trajectories = np.array(marker_trajectories)  # Shape: (N_markers, N_frames, 3)

# Compute center of mass per frame
centers_of_mass = np.nanmean(marker_trajectories, axis=0)

# Mask invalid frames
valid_frames = ~np.isnan(centers_of_mass).any(axis=1)
marker_trajectories = marker_trajectories[:, valid_frames, :]
centers_of_mass = centers_of_mass[valid_frames]
time = time[valid_frames]

# Plot each marker + CoM
fig = plt.figure(figsize=(12, 6))
ax = fig.add_subplot(111, projection='3d')

for i, traj in enumerate(marker_trajectories):
    ax.plot(*traj.T, label=f"Marker {i+1}", alpha=0.6)

ax.plot(*centers_of_mass.T, color='black', linewidth=2, label="Center of Mass")

# Add polygon at initial and final positions
initial_pts = marker_trajectories[:, 0, :]
final_pts = marker_trajectories[:, -1, :]

for points, color, label in zip([initial_pts, final_pts], ['green', 'red'], ['Start Shape', 'End Shape']):
    poly = Poly3DCollection([points], alpha=0.3, facecolor=color, edgecolor='k', label=label)
    ax.add_collection3d(poly)

ax.set_title("Trajectory")
ax.set_xlabel("X (mm)")
ax.set_ylabel("Y (mm)")
ax.set_zlabel("Z (mm)")
ax.legend()
plt.tight_layout()
plt.show()
