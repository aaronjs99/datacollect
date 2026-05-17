import unittest

from scripts.natnet import NatNetFrame, NatNetRigidBody
from scripts.packet import STATE_MOTIVE_OFF, STATE_NO_FRAME_DATA, build_heron_packet, build_status_packet
from scripts.receiver import format_status
from scripts.udp import UdpHeronReceiver, UdpJsonBroadcaster


class UdpReceiverTests(unittest.TestCase):
    def test_broadcaster_and_receiver_round_trip_on_loopback(self):
        frame = NatNetFrame(
            frame_number=33,
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
        )
        packet = build_heron_packet(frame, device="test-device", received_at_unix_ns=100)

        with UdpHeronReceiver(bind="127.0.0.1", port=0, timeout=1.0) as receiver:
            with UdpJsonBroadcaster("127.0.0.1", receiver.port) as broadcaster:
                broadcaster.send_packet(packet)
            received, address = receiver.recv_packet(timeout=1.0)

        self.assertEqual(received["frame"], 33)
        self.assertEqual(address[0], "127.0.0.1")

    def test_status_line_reports_position(self):
        frame = NatNetFrame(
            frame_number=34,
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
        )
        packet = build_heron_packet(frame)

        status = format_status(packet, ("127.0.0.1", 5005))

        self.assertIn("state=ok Heron x=1.0000", status)
        self.assertIn("from 127.0.0.1:5005", status)

    def test_status_line_reports_motive_off(self):
        packet = build_status_packet(
            state=STATE_MOTIVE_OFF,
            message="No NatNet frame data is being received from Motive.",
            frame=34,
            last_frame_age_ms=2001,
        )

        status = format_status(packet, ("127.0.0.1", 5005))

        self.assertIn("state=motive_off", status)
        self.assertIn("last_age_ms=2001", status)

    def test_status_line_reports_reachable_motive_without_frames(self):
        packet = build_status_packet(
            state=STATE_NO_FRAME_DATA,
            message="Motive is reachable, but no frame data is being received.",
            motive_reachable=True,
        )

        status = format_status(packet, ("127.0.0.1", 5005))

        self.assertIn("state=no_frame_data", status)
        self.assertIn("Motive is reachable", status)


if __name__ == "__main__":
    unittest.main()
