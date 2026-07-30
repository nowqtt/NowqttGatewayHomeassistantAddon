import pathlib
import sys
import unittest


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from gateway.serial_framing import SerialFrameReader


class ChunkReader:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __call__(self, size):
        if not self.chunks:
            return b""
        return self.chunks.pop(0)


class SerialFrameReaderTests(unittest.TestCase):
    def test_fragmented_frame_is_reassembled(self):
        reader = SerialFrameReader(
            ChunkReader([b"noise\xff", b"\x13\xab\x01\x03a", b"bc"])
        )
        self.assertEqual(reader.read_frame(), (1, b"abc"))

    def test_corrupt_length_recovers_following_valid_frame(self):
        now = [0.0]
        valid_frame = b"\xff\x13\xab\x01\x03abc"
        chunks = ChunkReader([b"\xff\x13\xab\x01\x64bad" + valid_frame, b""])
        reader = SerialFrameReader(chunks, frame_timeout=1.0, clock=lambda: now[0])

        self.assertIsNone(reader.read_frame())
        now[0] = 2.0
        with self.assertRaises(TimeoutError):
            reader.read_frame()
        self.assertEqual(reader.read_frame(), (1, b"abc"))

    def test_continuous_noise_does_not_recurse(self):
        chunks = [b"x" * 256 for _ in range(2000)] + [b""]
        reader = SerialFrameReader(ChunkReader(chunks))
        self.assertIsNone(reader.read_frame())

    def test_complete_frame_after_deadline_is_rejected(self):
        now = [0.0]
        chunks = ChunkReader([b"\xff\x13\xab\x01\x03", b""])
        reader = SerialFrameReader(chunks, frame_timeout=1.0, clock=lambda: now[0])
        self.assertIsNone(reader.read_frame())
        chunks.chunks.insert(0, b"abc")
        now[0] = 2.0
        with self.assertRaises(TimeoutError):
            reader.read_frame()


if __name__ == "__main__":
    unittest.main()
