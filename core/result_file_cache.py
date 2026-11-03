"""Reuse unchanged saved JSON without retaining every case in a project.

Returned objects are borrowed, read-only data. Consumers that replace result
fields (for example animation's ``displacements``) must copy the top-level dict.
"""

from collections import OrderedDict
import json
import os
from threading import RLock

_MAX_FILES = 4
_MAX_BYTES = 128 * 1024 * 1024
_cache = OrderedDict()
_lock = RLock()

def json_file_signature(path):
    """Include replacement and sub-second writes when validating a saved file."""
    path = os.path.normcase(os.path.abspath(os.fspath(path)))
    stat = os.stat(path)
    return path, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino

def get_cached_json(path):
    """Return an unchanged cached file, or None; never read/parse its contents."""
    signature = json_file_signature(path)
    with _lock:
        entry = _cache.get(signature[0])
        if entry is None:
            return None
        if entry[0] != signature:
            del _cache[signature[0]]
            return None
        _cache.move_to_end(signature[0])
        return entry[1]

def load_json_cached(path):
    """Read once per file revision. Large cold reads belong on a worker thread."""
    data = get_cached_json(path)
    if data is not None:
        return data
    for attempt in range(2):
        signature = json_file_signature(path)
        with open(path, 'r') as stream:
            data = json.load(stream)
        if json_file_signature(path) == signature:
            break
    else:
                                                                           
        raise OSError(f'Saved result changed while reading: {path}')
    with _lock:
        existing = _cache.get(signature[0])
        if existing is not None and existing[0] == signature:
            return existing[1]
        _cache[signature[0]] = (signature, data)
        _cache.move_to_end(signature[0])
                                                                          
        while len(_cache) > 1:
            sizes = [entry[0][3] for entry in _cache.values()]
            oversized = sum(size > _MAX_BYTES for size in sizes)
            ordinary_bytes = sum(size for size in sizes if size <= _MAX_BYTES)
            if (len(_cache) <= _MAX_FILES and oversized <= 1
                    and ordinary_bytes <= _MAX_BYTES):
                break
            _cache.popitem(last=False)
    return data

def clear_json_cache():
    """Release saved data (also useful when a project closes)."""
    with _lock:
        _cache.clear()
