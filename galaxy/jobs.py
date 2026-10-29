import threading
import time

from .log import log

LOCK_WAIT = 150


class Busy(RuntimeError):
    pass


class Cancelled(RuntimeError):
    pass


_state = {"phase": "idle", "error": "", "warning": "", "source": "", "intent": "down", "request": {}}
_state_lock = threading.Lock()
_job_lock = threading.Lock()
_cancel = threading.Event()
_cache = {}


def update(**values):
    with _state_lock:
        _state.update(values)


def snapshot():
    with _state_lock:
        return dict(_state)


def set_phase(phase, error=""):
    update(phase=phase, error=error)


def busy():
    return _job_lock.locked()


def request_cancel():
    _cancel.set()


def clear_cancel():
    _cancel.clear()


def cancelled():
    return _cancel.is_set()


def check_cancel():
    if _cancel.is_set():
        raise Cancelled("cancelled")


def cached(key, ttl, producer):
    now = time.time()
    entry = _cache.get(key)
    if entry and now - entry[0] < ttl:
        return entry[1]
    value = producer()
    _cache[key] = (now, value)
    return value


def invalidate(key):
    _cache.pop(key, None)


def submit(function, *args, report=True, wait=False):
    if wait:
        acquired = _job_lock.acquire(timeout=LOCK_WAIT)
    else:
        acquired = _job_lock.acquire(blocking=False)
    if not acquired:
        raise Busy("another action is running")

    def target():
        try:
            function(*args)
        except Cancelled:
            pass
        except Exception as error:
            log(f"{function.__name__} failed: {error}")
            if report:
                set_phase("error", str(error))
        finally:
            _job_lock.release()

    threading.Thread(target=target, daemon=True).start()
