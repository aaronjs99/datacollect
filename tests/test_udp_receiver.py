import unittest

from scripts.natnet import NatNetFrame, NatNetRigidBody
from scripts.packet import build_heron_packet
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

        self.assertIn("Heron x=1.0000", status)
        self.assertIn("from 127.0.0.1:5005", status)


if __name__ == "__main__":
    unittest.main()
