"""
compact_json.py  -  size-aware JSON writer used for the big files (.mf model save,
*_results.json).

Why this exists
---------------
json.dump(obj, f, indent=4) has two costs that explode on large models:
  * with indent set (and with json.dump in general) Python uses the pure-Python
    encoder, not the C one - several times slower;
  * indent=4 puts every number on its own line, so files are 3-4x bigger.

What write_json() does
----------------------
  * n_items <= compact_above  -> EXACTLY the old call: json.dump(obj, f, indent=4).
    Small models produce byte-identical, human-readable files.
  * n_items  > compact_above  -> compact separators, written with the C encoder,
    in chunks (so peak memory is one chunk, not a second copy of the whole file).

Both outputs are plain JSON; any json.load() reader gets the same Python data.
Nothing here changes a value - only whitespace and how it is written.
"""
import json

COMPACT_ABOVE = 20000                                                                         

_SEP = (",", ":")
_CHUNK = 20000                                                                             
_RECURSE_BELOW = 64                                                                          

def json_key(k):
    """The string json itself would emit for a dict key."""
    if isinstance(k, str):
        return k
    if isinstance(k, int) and not isinstance(k, bool):
        return str(k)
    return next(iter(json.loads(json.dumps({k: 0}))))                                                     

def _stream(obj, f):
    if isinstance(obj, dict):
        if len(obj) > _RECURSE_BELOW:
            items = list(obj.items())
            f.write("{")
            for i in range(0, len(items), _CHUNK):
                if i:
                    f.write(",")
                f.write(json.dumps(dict(items[i:i + _CHUNK]), separators=_SEP)[1:-1])
            f.write("}")
        else:
            f.write("{")
            first = True
            for k, v in obj.items():
                if not first:
                    f.write(",")
                first = False
                f.write(json.dumps(json_key(k)))
                f.write(":")
                _stream(v, f)
            f.write("}")
    elif isinstance(obj, (list, tuple)):
        if len(obj) > _RECURSE_BELOW:
            f.write("[")
            for i in range(0, len(obj), _CHUNK):
                if i:
                    f.write(",")
                f.write(json.dumps(list(obj[i:i + _CHUNK]), separators=_SEP)[1:-1])
            f.write("]")
        else:
            f.write("[")
            for i, v in enumerate(obj):
                if i:
                    f.write(",")
                _stream(v, f)
            f.write("]")
    else:
        f.write(json.dumps(obj, separators=_SEP))

def write_json(obj, f, n_items=0, compact_above=None):
    """Write obj to the open text file f. n_items is a cheap size estimate (e.g. nodes+elements)."""
    if compact_above is None:
        compact_above = COMPACT_ABOVE
    if n_items <= compact_above:
        json.dump(obj, f, indent=4)
    else:
        _stream(obj, f)
