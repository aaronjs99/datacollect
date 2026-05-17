import math
import unittest

from scripts.natnet import MarkerSet, NatNetFrame, NatNetMarker, NatNetRigidBody
from scripts.packet import (
    SCHEMA,
    PacketValidationError,
    build_heron_packet,
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
        self.assertIsNone(packet["heron"]["rigid_body"]["position_m"])
        self.assertEqual(packet["heron"]["rigid_body"]["name"], "Heron")

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
