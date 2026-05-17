import math
import unittest

from scripts.natnet import MarkerSet, NatNetFrame, NatNetMarker, NatNetRigidBody
from scripts.packet import (
    SCHEMA,
    PacketValidationError,
    STATE_MOTIVE_OFF,
    build_heron_packet,
    build_status_packet,
    decode_packet,
    validate_packet,
)


class PacketTests(unittest.TestCase):
    def test_builds_pose_markers_and_potential_objects(self):
        frame = NatNetFrame(
            frame_number=12,
            rigid_bodies=[
                NatNetRigidBody(
                    id=17,
                    name="Heron",
                    position=(1.0, 2.0, 3.0),
                    orientation=(0.0, 0.0, 0.0, 1.0),
                    tracking_valid=True,
                    mean_error=0.001,
                )
            ],
            labeled_markers=[
                NatNetMarker(
                    id=(17 << 16) | 1,
                    model_id=17,
                    marker_id=1,
                    label="Heron:Marker 001",
                    position=(1.1, 2.1, 3.1),
                    size=0.014,
                    residual=0.2,
                ),
                NatNetMarker(
                    id=(99 << 16) | 1,
                    model_id=99,
                    marker_id=1,
                    label="Other:Marker 001",
                    position=(9.0, 9.0, 9.0),
                ),
            ],
            unlabeled_markers=[
                NatNetMarker(id=0, position=(4.0, 5.0, 6.0)),
                NatNetMarker(id=1, position=(math.nan, 5.0, 6.0)),
            ],
        )

        packet = build_heron_packet(frame, device="test-device", received_at_unix_ns=100)

        self.assertEqual(packet["schema"], SCHEMA)
        self.assertEqual(packet["device"], "test-device")
        self.assertEqual(packet["frame"], 12)
        self.assertEqual(packet["status"]["state"], "ok")
        self.assertTrue(packet["status"]["flags"]["motive_receiving"])
        self.assertTrue(packet["status"]["flags"]["object_found"])
        self.assertTrue(packet["heron"]["tracking_valid"])
        self.assertEqual(packet["heron"]["rigid_body"]["position_m"]["x"], 1.0)
        self.assertEqual(len(packet["heron"]["markers"]), 1)
        self.assertEqual(packet["heron"]["markers"][0]["label"], "Heron:Marker 001")
        self.assertEqual(len(packet["heron"]["potential_objects"]), 1)

    def test_missing_rigid_body_marks_tracking_invalid(self):
        frame = NatNetFrame(
            frame_number=13,
            rigid_bodies=[],
            labeled_markers=[],
            unlabeled_markers=[],
        )

        packet = build_heron_packet(frame, device="test-device", received_at_unix_ns=100)

        self.assertFalse(packet["heron"]["tracking_valid"])
        self.assertEqual(packet["status"]["state"], "object_not_found")
        self.assertFalse(packet["status"]["flags"]["object_found"])
        self.assertIsNone(packet["heron"]["rigid_body"]["position_m"])
        self.assertEqual(packet["heron"]["rigid_body"]["name"], "Heron")

    def test_untracked_rigid_body_marks_tracking_lost(self):
        frame = NatNetFrame(
            frame_number=15,
            rigid_bodies=[
                NatNetRigidBody(
                    id=17,
                    name="Heron",
                    position=(1.0, 2.0, 3.0),
                    orientation=(0.0, 0.0, 0.0, 1.0),
                    tracking_valid=False,
                )
            ],
            labeled_markers=[],
            unlabeled_markers=[],
        )

        packet = build_heron_packet(frame)

        self.assertEqual(packet["status"]["state"], "tracking_lost")
        self.assertTrue(packet["status"]["flags"]["object_found"])
        self.assertFalse(packet["status"]["flags"]["tracking_valid"])

    def test_status_packet_distinguishes_motive_off(self):
        packet = build_status_packet(
            state=STATE_MOTIVE_OFF,
            message="No NatNet frame data is being received from Motive.",
            rigid_body_name="Heron",
            device="test-device",
            frame=12,
            received_at_unix_ns=100,
            last_frame_age_ms=2500,
        )

        validate_packet(packet)
        self.assertEqual(packet["status"]["state"], "motive_off")
        self.assertFalse(packet["status"]["flags"]["motive_receiving"])
        self.assertTrue(packet["status"]["flags"]["heartbeat"])
        self.assertEqual(packet["status"]["last_frame_age_ms"], 2500)
        self.assertFalse(packet["heron"]["tracking_valid"])

    def test_marker_set_fallback_when_labeled_markers_are_missing(self):
        frame = NatNetFrame(
            frame_number=14,
            rigid_bodies=[
                NatNetRigidBody(
                    id=17,
                    name="Heron",
                    position=(1.0, 2.0, 3.0),
                    orientation=(0.0, 0.0, 0.0, 1.0),
                    tracking_valid=True,
                )
            ],
            labeled_markers=[],
            unlabeled_markers=[],
            marker_sets=[MarkerSet(name="Heron", markers=[(1.1, 2.1, 3.1)])],
        )

        packet = build_heron_packet(frame)

        self.assertEqual(len(packet["heron"]["markers"]), 1)
        self.assertEqual(packet["heron"]["markers"][0]["label"], "Heron:Marker 001")

    def test_validate_accepts_unknown_extra_fields(self):
        frame = NatNetFrame(frame_number=1, rigid_bodies=[], labeled_markers=[], unlabeled_markers=[])
        packet = build_heron_packet(frame)
        packet["future"] = {"anything": True}

        self.assertIs(validate_packet(packet), packet)

    def test_decode_rejects_malformed_json_and_wrong_schema(self):
        with self.assertRaises(PacketValidationError):
            decode_packet(b"{nope")

        frame = NatNetFrame(frame_number=1, rigid_bodies=[], labeled_markers=[], unlabeled_markers=[])
        bad_packet = build_heron_packet(frame)
        bad_packet["schema"] = "wrong"

        with self.assertRaises(PacketValidationError):
            validate_packet(bad_packet)


if __name__ == "__main__":
    unittest.main()
