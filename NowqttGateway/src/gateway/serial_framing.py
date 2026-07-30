import time


FRAME_PREFIX = b"\xff\x13\xab"
FRAME_HEADER_SIZE = 5
MAX_SCAN_CHUNKS = 16


class SerialFrameReader:
    def __init__(self, read_chunk, frame_timeout=2.0, clock=time.monotonic):
        self._read_chunk = read_chunk
        self._frame_timeout = frame_timeout
        self._clock = clock
        self._buffer = bytearray()
        self._candidate_deadline = None

    def read_frame(self):
        while True:
            if not self._align_to_prefix():
                return None

            if self._candidate_expired():
                self._expire_candidate()

            if len(self._buffer) < FRAME_HEADER_SIZE:
                if not self._read_more():
                    return self._handle_incomplete_frame()
                continue

            body_length = self._buffer[4]
            if body_length == 0:
                self._discard_candidate()
                raise ValueError("Serial frame has an empty body")

            frame_size = FRAME_HEADER_SIZE + body_length
            if len(self._buffer) < frame_size:
                if not self._read_more():
                    return self._handle_incomplete_frame()
                continue

            service = self._buffer[3]
            body = bytes(self._buffer[FRAME_HEADER_SIZE:frame_size])
            del self._buffer[:frame_size]
            self._candidate_deadline = None
            return service, body

    def _align_to_prefix(self):
        for _ in range(MAX_SCAN_CHUNKS):
            prefix_position = self._buffer.find(FRAME_PREFIX)
            if prefix_position >= 0:
                if prefix_position:
                    del self._buffer[:prefix_position]
                if self._candidate_deadline is None:
                    self._candidate_deadline = self._clock() + self._frame_timeout
                return True

            self._retain_prefix_suffix()
            if not self._read_more():
                return False
        return False

    def _read_more(self):
        chunk = self._read_chunk(256)
        if not chunk:
            return False
        self._buffer.extend(chunk)
        return True

    def _handle_incomplete_frame(self):
        if not self._candidate_expired():
            return None

        self._expire_candidate()

    def _candidate_expired(self):
        return (
            self._candidate_deadline is not None
            and self._clock() >= self._candidate_deadline
        )

    def _expire_candidate(self):
        expected_length = FRAME_HEADER_SIZE + self._buffer[4] if len(self._buffer) >= 5 else 5
        received_length = len(self._buffer)
        self._discard_candidate()
        raise TimeoutError(
            "Serial frame deadline expired after %d of %d bytes"
            % (received_length, expected_length)
        )

    def _discard_candidate(self):
        next_prefix = self._buffer.find(FRAME_PREFIX, 1)
        if next_prefix >= 0:
            del self._buffer[:next_prefix]
        else:
            del self._buffer[:1]
            self._retain_prefix_suffix()
        self._candidate_deadline = None

    def _retain_prefix_suffix(self):
        keep = 0
        max_suffix = min(len(self._buffer), len(FRAME_PREFIX) - 1)
        for suffix_length in range(1, max_suffix + 1):
            if self._buffer[-suffix_length:] == FRAME_PREFIX[:suffix_length]:
                keep = suffix_length
        if keep:
            del self._buffer[:-keep]
        else:
            self._buffer.clear()
