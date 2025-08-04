import os
import csv
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import argparse


def extract_names_row(filepath, name_row_idx=3):
    with open(filepath, newline='') as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i == name_row_idx:
                return row
    raise ValueError(f"Could not find name row at index {name_row_idx}.")


def load_marker_trajectories(df, names_row, marker_prefix):
    seen = set()
    unique_triplets = []
    i = 0

    while i < len(names_row) - 2:
        name = names_row[i]
        if (
            isinstance(name, str)
            and name.startswith(marker_prefix)
            and i + 2 < len(df.columns)
        ):
            marker_id = name
            if marker_id not in seen:
                seen.add(marker_id)
                triplet = [df.columns[i], df.columns[i+1], df.columns[i+2]]
                unique_triplets.append(triplet)
            i += 3
        else:
            i += 1

    marker_trajectories = []
    for triplet in unique_triplets:
        try:
            marker_df = df[triplet].astype(float)
            marker_trajectories.append(marker_df.values)
        except Exception as e:
            print(f"Skipping {triplet}: {e}")

    return np.array(marker_trajectories)


def plot_trajectories(marker_trajectories, centers_of_mass, save_path=None):
    fig = plt.figure(figsize=(12, 6))
    ax = fig.add_subplot(111, projection='3d')

    for i, traj in enumerate(marker_trajectories):
        ax.plot(*traj.T, label=f"Marker {i+1}", alpha=0.6)

    ax.plot(*centers_of_mass.T, color='black', linewidth=2, label="Center of Mass")

    initial_pts = marker_trajectories[:, 0, :]
    final_pts = marker_trajectories[:, -1, :]

    for points, color, label in zip([initial_pts, final_pts], ['green', 'red'], ['Start Shape', 'End Shape']):
        poly = Poly3DCollection([points], alpha=0.3, facecolor=color, edgecolor='k', label=label)
        ax.add_collection3d(poly)

    ax.set_title("Trajectory")
    ax.set_xlabel("X (mm)", labelpad=10)
    ax.set_ylabel("Y (mm)", labelpad=10)
    ax.set_zlabel("Z (mm)", labelpad=10)
    ax.legend()

    # Equal aspect ratio
    xyz = np.concatenate([marker_trajectories.reshape(-1, 3), centers_of_mass])
    center = np.mean(xyz, axis=0)
    max_range = np.ptp(xyz, axis=0).max()

    ax.set_xlim(center[0] - max_range/2, center[0] + max_range/2)
    ax.set_ylim(center[1] - max_range/2, center[1] + max_range/2)
    ax.set_zlim(center[2] - max_range/2, center[2] + max_range/2)

    ax.plot([0], [0], [0], 'ko', label="Origin")
    ax.view_init(elev=30, azim=30, roll=105)

    plt.tight_layout()
    if save_path:
        plt.savefig(save_path, dpi=300)
    plt.show()


def main(datafile, marker_prefix="Heron:Marker", name_row_idx=3):
    if not os.path.exists(datafile):
        raise FileNotFoundError(f"Data file not found: {datafile}")

    names_row = extract_names_row(datafile, name_row_idx=name_row_idx)
    df = pd.read_csv(datafile, skiprows=7)

    time = pd.to_numeric(df["Time (Seconds)"], errors="coerce")
    df = df.dropna(subset=["Time (Seconds)"]).reset_index(drop=True)
    time = time.values - time.values[0]

    marker_trajectories = load_marker_trajectories(df, names_row, marker_prefix)

    if marker_trajectories.size == 0:
        raise ValueError("No valid marker trajectories found.")

    centers_of_mass = np.nanmean(marker_trajectories, axis=0)

    valid_frames = ~np.isnan(centers_of_mass).any(axis=1)
    marker_trajectories = marker_trajectories[:, valid_frames, :]
    centers_of_mass = centers_of_mass[valid_frames]

    plot_trajectories(marker_trajectories, centers_of_mass, save_path="./plots/trajectory_plot.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Plot 3D trajectories from OptiTrack CSV.")
    parser.add_argument("--file", type=str, default="./data/Heron_Test_01.csv", help="Path to CSV data file.")
    parser.add_argument("--prefix", type=str, default="Heron:Marker", help="Prefix for marker names.")
    parser.add_argument("--name_row", type=int, default=3, help="Index of the row with marker names (0-based).")

    args = parser.parse_args()
    main(args.file, marker_prefix=args.prefix, name_row_idx=args.name_row)
