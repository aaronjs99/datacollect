# DataCollect

DataCollect bridges OptiTrack Motive data into a small LAN-friendly Heron state stream. It can:

- receive live Motive/NatNet frames and broadcast Heron pose/points as UDP JSON
- receive and inspect that UDP JSON stream from another process or machine
- plot marker trajectories from exported Motive CSV files

All implementation code lives in `scripts/`. Use `run.py` from the repo root as the main entrypoint.

## Layout

```text
datacollect/
  run.py              # command dispatcher
  scripts/            # live, receive, NatNet, UDP, packet, and plot code
  tests/              # unit and local UDP integration tests
  README.md
  LICENSE
  requirements.txt
```

The `data/` and `plots/` folders are local working folders and are git-ignored.
The `.runtime/` folder is also ignored; the startup installer writes its launcher and log there.

## Install

```bash
pip install -r requirements.txt
```

The live UDP/NatNet tools use only the Python standard library. CSV plotting uses `numpy`, `pandas`, and `matplotlib`.

## Run

Show the root command menu:

```bash
python run.py --help
```

Start the live Motive broadcaster:

```bash
python run.py live --server-ip 127.0.0.1 --rigid-body Heron
```

The live broadcaster is meant to stay running. It keeps sending heartbeat/status packets even when Motive is off or not streaming.

Listen for Heron packets:

```bash
python run.py receive --bind 0.0.0.0 --port 5005
```

Plot an exported Motive CSV:

```bash
python run.py plot --file ./data/Heron_Test_01.csv --prefix "Heron:Marker"
```

## Motive Setup

Enable Motive streaming before running the live broadcaster:

- Broadcast Frame Data: enabled
- Stream Rigid Bodies: enabled
- Stream Markers / labeled markers: enabled if marker points are needed
- NatNet command port: `1510`
- NatNet data port: `1511`

By default, the broadcaster receives NatNet multicast data and sends one UDP JSON packet per Motive frame to `255.255.255.255:5005`.

Useful live options:

```bash
python run.py live --help
python run.py live --connection-type unicast --local-ip 192.168.1.20 --server-ip 192.168.1.10
python run.py live --rigid-body Heron --rigid-body-id 17
```

Optional receiver JSONL logging:

```bash
python run.py receive --jsonl logs/heron_packets.jsonl
```

## Background Startup

On Windows, install the transmitter as a background scheduled task:

```bash
python run.py startup install -- --server-ip 127.0.0.1 --rigid-body Heron
```

This writes `.runtime/start_heron_broadcaster.cmd`, logs to `.runtime/heron_broadcaster.log`, and creates a Task Scheduler entry named `DataCollectHeronBroadcaster`. The default trigger is `boot` (`ONSTART`), which may require an elevated shell. Use `--trigger logon` for a per-user logon task:

```bash
python run.py startup install --trigger logon -- --server-ip 127.0.0.1 --rigid-body Heron
```

If Task Scheduler is locked down, use the no-admin Startup folder trigger:

```bash
python run.py startup install --trigger startup-folder -- --server-ip 127.0.0.1 --rigid-body Heron
```

Manage the task:

```bash
python run.py startup status
python run.py startup uninstall
```

## UDP Packet Shape

```json
{
  "schema": "datacollect.heron.v1",
  "device": "SRILab-Desktop",
  "frame": 12345,
  "received_at_unix_ns": 0,
  "units": { "position": "m", "orientation": "quaternion_xyzw" },
  "status": {
    "state": "ok",
    "flags": {
      "motive_reachable": true,
      "motive_receiving": true,
      "object_found": true,
      "tracking_valid": true,
      "heartbeat": false
    },
    "message": "Heron rigid body is being tracked.",
    "last_frame_age_ms": null
  },
  "heron": {
    "tracking_valid": true,
    "rigid_body": {
      "name": "Heron",
      "id": 17,
      "position_m": { "x": 0.0, "y": 0.0, "z": 0.0 },
      "orientation_xyzw": { "x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0 }
    },
    "markers": [],
    "potential_objects": []
  }
}
```

Positions are in meters. `markers` contains labeled `Heron:Marker ###` points. `potential_objects` contains unlabeled Motive point-cloud markers.

Status states:

- `ok`: Motive frames are arriving and Heron is tracked.
- `motive_off`: Motive is not reachable over NatNet.
- `no_frame_data`: Motive is reachable, but no NatNet frame data has arrived within `--motive-timeout`.
- `object_not_found`: Motive frames are arriving, but the configured rigid body is missing.
- `tracking_lost`: the configured rigid body exists in the frame but is not valid/tracked.
- `startup_error`: the background/live process could not create or use its NatNet sockets and will retry.

## Tests

```bash
python -m unittest discover -v
```

## License

MIT License. Copyright (c) 2026 Aaron John Sabu.
