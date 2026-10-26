"""Opt-in, bounded independent source evidence; no routine report TXT sink."""
import copy
import json
import queue
import struct
import threading

from subscription import owned_size


class SourceEvidence:
    def __init__(self, path, limit=100000):
        self.file = path.open("x", encoding="utf-8")
        self.queue = queue.Queue(maxsize=256)
        self.lock = threading.Lock()
        self.bytes = 0
        self.accepted = 0
        self.written = 0
        self.limit = limit
        self.error = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, name="kpm-source-evidence", daemon=True)
        self.thread.start()

    def offer(self, record, callback, ready, until, admitted):
        snapshot = copy.deepcopy(record)
        item = dict(report=snapshot, callback_at_mono_us=str(callback), report_ready_at_mono_us=str(ready),
                    valid_until_mono_us=str(until), ingress_admitted=admitted,
                    real_bits={name: struct.pack(">d", value["value"]).hex()
                               for name, value in record["row"]["metrics"].items() if value["type"] == "real"})
        size = owned_size(item)
        with self.lock:
            if self.error:
                raise RuntimeError("source evidence writer failed") from self.error
            if self.accepted >= self.limit or size > 4194304 - self.bytes:
                raise RuntimeError("source evidence bound exceeded")
            try:
                self.queue.put_nowait((item, size))
            except queue.Full as exc:
                raise RuntimeError("source evidence queue overflow") from exc
            self.bytes += size
            self.accepted += 1

    def _run(self):
        try:
            while not self.stop.is_set() or not self.queue.empty():
                try:
                    item, size = self.queue.get(timeout=0.02)
                except queue.Empty:
                    continue
                try:
                    self.file.write(json.dumps(item, allow_nan=False, separators=(",", ":")) + "\n")
                    self.file.flush()
                    self.written += 1
                finally:
                    with self.lock:
                        self.bytes -= size
        except Exception as exc:
            self.error = exc
        finally:
            try:
                self.file.close()
            except Exception as exc:
                self.error = exc

    def close(self):
        self.stop.set()
        self.thread.join(5)
        if self.thread.is_alive() or self.error or self.accepted != self.written:
            raise RuntimeError("source evidence did not drain completely") from self.error
