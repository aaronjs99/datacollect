import struct
import unittest

from scripts.natnet import (
    NAT_FRAMEOFDATA,
    NAT_MODELDEF,
    parse_natnet_message,
    pack_natnet_message,
)


def cstr(value: str) -> bytes:
    return value.encode("utf-8") + b"\0"


def bundle(payload: bytes) -> bytes:
    return struct.pack("<i", len(payload)) + payload


class NatNetParserTests(unittest.TestCase):
    def test_parses_model_definition_and_frame_data(self):
        rigid_body_description = b"".join(
            [
                cstr("Heron"),
                struct.pack("<ii", 17, -1),
                struct.pack("<fff", 0.0, 0.0, 0.0),
                struct.pack("<i", 0),
            ]
        )
        model_payload = b"".join(
            [
                struct.pack("<i", 1),
                struct.pack("<i", 1),
                bundle(rigid_body_description),
            ]
        )
        message_id, model_defs = parse_natnet_message(pack_natnet_message(NAT_MODELDEF, model_payload))

        self.assertEqual(message_id, NAT_MODELDEF)
        self.assertEqual(model_defs.rigid_body_names[17], "Heron")

        labeled_id = (17 << 16) | 1
        unlabeled_markers = struct.pack("<fff", 4.0, 5.0, 6.0)
        rigid_bodies = b"".join(
            [
                struct.pack("<i", 17),
                struct.pack("<fff", 1.0, 2.0, 3.0),
                struct.pack("<ffff", 0.0, 0.0, 0.0, 1.0),
                struct.pack("<f", 0.001),
                struct.pack("<h", 1),
            ]
        )
        labeled_markers = b"".join(
            [
                struct.pack("<i", labeled_id),
                struct.pack("<fff", 1.1, 2.1, 3.1),
                struct.pack("<f", 0.014),
                struct.pack("<h", 5),
                struct.pack("<f", 0.2),
            ]
        )
        frame_payload = b"".join(
            [
                struct.pack("<i", 42),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 1),
                bundle(unlabeled_markers),
                struct.pack("<i", 1),
                bundle(rigid_bodies),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 1),
                bundle(labeled_markers),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
            ]
        )

        message_id, frame = parse_natnet_message(
            pack_natnet_message(NAT_FRAMEOFDATA, frame_payload),
            rigid_body_names=model_defs.rigid_body_names,
        )

        self.assertEqual(message_id, NAT_FRAMEOFDATA)
        self.assertEqual(frame.frame_number, 42)
        self.assertEqual(frame.rigid_bodies[0].name, "Heron")
        self.assertTrue(frame.rigid_bodies[0].tracking_valid)
        self.assertEqual(frame.labeled_markers[0].label, "Heron:Marker 001")
        self.assertEqual(frame.unlabeled_markers[0].position, (4.0, 5.0, 6.0))

    def test_parses_natnet4_frame_bundle_sizes(self):
        marker_sets = b"".join(
            [
                cstr("Heron"),
                struct.pack("<i", 2),
                struct.pack("<fff", 1.0, 2.0, 3.0),
                struct.pack("<fff", 4.0, 5.0, 6.0),
            ]
        )
        frame_payload = b"".join(
            [
                struct.pack("<i", 43),
                struct.pack("<i", 1),
                bundle(marker_sets),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
                struct.pack("<i", 0),
            ]
        )

        message_id, frame = parse_natnet_message(pack_natnet_message(NAT_FRAMEOFDATA, frame_payload))

        self.assertEqual(message_id, NAT_FRAMEOFDATA)
        self.assertEqual(frame.frame_number, 43)
        self.assertEqual(frame.marker_sets[0].name, "Heron")
        self.assertEqual(frame.marker_sets[0].markers[1], (4.0, 5.0, 6.0))


if __name__ == "__main__":
    unittest.main()
