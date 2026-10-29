import threading
import time


class Busy(RuntimeError):
    pass


_state = {"phase": "idle", "error": "", "warning": "", "source": ""}
_state_lock = threading.Lock()
_job_lock = threading.Lock()
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


def exclusive(function, *args):
    if not _job_lock.acquire(blocking=False):
        raise Busy("another action is running")
    try:
        return function(*args)
    finally:
        _job_lock.release()


def submit(function, *args, report=True, log=print):
    if not _job_lock.acquire(blocking=False):
        raise Busy("another action is running")

    def target():
        try:
            function(*args)
        except Exception as error:
            log(f"{function.__name__} failed: {error}")
            if report:
                set_phase("error", str(error))
        finally:
            _job_lock.release()

    threading.Thread(target=target, daemon=True).start()
