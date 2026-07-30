import pathlib
import sys
import unittest
from unittest.mock import patch


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ota.aodv_ota_updater import OtaCommands, OtaSession


class OtaSessionTests(unittest.TestCase):
    @patch("ota.aodv_ota_updater.time.sleep", return_value=None)
    @patch("ota.aodv_ota_updater.send_ota_data_serial_message", return_value=True)
    def test_packet_boundaries_never_send_empty_payload(self, send_packet, _):
        for firmware_size, expected_count in ((1, 1), (231, 1), (232, 1), (233, 2)):
            with self.subTest(firmware_size=firmware_size):
                send_packet.reset_mock()
                session = OtaSession(
                    b"x" * firmware_size,
                    "aabbccddeeff",
                    lambda _: None,
                    30,
                )
                self.assertEqual(session.packet_count, expected_count)
                for packet_number in range(session.packet_count):
                    session._send_packet(packet_number)

                payloads = [call.args[-1] for call in send_packet.call_args_list]
                self.assertEqual(len(payloads), expected_count)
                self.assertTrue(all(payloads))
                self.assertEqual(sum(map(len, payloads)), firmware_size)

    def test_retransmit_uses_all_four_packet_number_bytes(self):
        session = OtaSession(b"x", "aabbccddeeff", lambda _: None, 30)
        session.packet_count = 0x01020305
        packet_number = 0x01020304
        payload = bytes([OtaCommands.OTA_RETRANSMIT]) + packet_number.to_bytes(4, "little")
        self.assertTrue(session.handle_serial_message(payload))
        self.assertIn(packet_number, session._retransmit_packets)


if __name__ == "__main__":
    unittest.main()
