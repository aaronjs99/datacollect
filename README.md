# Data Collection from OptiTrack Motion Capture Cameras

This repository provides tools for visualizing the motion of a rigid body tracked by an optical motion capture system. It reads CSV data exported from Motive, extracts `robot_link` marker trajectories, computes the center of mass (CoM), and renders a 3D plot with initial and final configurations outlined.

## Structure

```
datacollect/
├── data/
├── main.py                              # Main visualization script
├── LICENSE
└── README.md
```

## Usage

Make sure your CSV file is placed in the `./data/` directory. Then run:

```bash
python main.py
```

## Features

- Parses and filters only `robot_link:Marker` columns
- Removes duplicated markers
- Computes center of mass across frames
- Visualizes:
  - Marker trajectories
  - Center of Mass trajectory
  - Polygon mesh at the initial and final marker positions

## Dependencies

Make sure the following Python libraries are installed:

```bash
pip install pandas numpy matplotlib
```

## Output Example

- Each marker trajectory is drawn in a light color.
- The CoM is shown in black.
- Start shape (polygon): green
- End shape (polygon): red

## Notes

- CSV format must follow Motive’s export style with metadata in the first few rows.
- Only `robot_link:Marker` entries are used to compute rigid body motion.

## License

MIT License (2025) – Aaron John Sabu
