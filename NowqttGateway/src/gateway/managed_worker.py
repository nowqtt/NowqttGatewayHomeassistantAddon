import logging
import threading


class ManagedWorker:
    def __init__(self, name, target, stop_event, args=()):
        self.name = name
        self._target = target
        self._stop_event = stop_event
        self._args = args
        self._failure = None
        self._failure_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run,
            name=name,
            daemon=True,
        )

    def start(self):
        self._thread.start()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def failure(self):
        with self._failure_lock:
            return self._failure

    def is_healthy(self):
        return self._thread.is_alive() and self.failure() is None

    def status(self):
        return {
            "alive": self._thread.is_alive(),
            "failure": self.failure(),
        }

    def _run(self):
        try:
            self._target(*self._args, self._stop_event)
        except Exception as error:
            with self._failure_lock:
                self._failure = "%s: %s" % (type(error).__name__, error)
            logging.exception("Required worker %s failed", self.name)
            self._stop_event.set()
        else:
            if not self._stop_event.is_set():
                with self._failure_lock:
                    self._failure = "worker exited unexpectedly"
                logging.error("Required worker %s exited unexpectedly", self.name)
                self._stop_event.set()
