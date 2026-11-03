"""
load_protocols.py   (core/opensees_port/)

Pure-Python generators for displacement / load-factor histories used by the OpenSees nonlinear
static cases.  Each returns a list of TARGET values (absolute, not increments); the solver reaches
each target from the previous one (first from zero), exactly how the History Table is consumed.

All values are in SI (metres) for displacements; the UI converts to/from display units.
"""
import math

ACI_374_1_DRIFTS_PCT = [0.25, 0.35, 0.50, 0.75, 1.0, 1.4, 1.75, 2.2, 2.75, 3.5, 4.5]

PROTOCOL_KINDS = ("Monotonic", "Symmetric cycles", "Increasing amplitude", "Drift-based (ACI 374.1)", "One-sided cycles")

def monotonic(target):
    return [float(target)]

def symmetric_cycles(amplitude, n_cycles=3, positive_first=True, return_to_zero=True):
    a = abs(float(amplitude)) * (1.0 if positive_first else -1.0)
    out = []
    for _ in range(int(n_cycles)):
        out += [a, -a]
    if return_to_zero:
        out.append(0.0)
    return out

def increasing_amplitude(amplitudes, cycles_per_amp=3, positive_first=True, return_to_zero=True):
    out = []
    for amp in amplitudes:
        out += symmetric_cycles(amp, cycles_per_amp, positive_first, return_to_zero=False)
    if return_to_zero:
        out.append(0.0)
    return out

def drift_based(height, drifts_pct=None, cycles_per_level=3, positive_first=True, return_to_zero=True):
    """Amplitude = drift% / 100 * height  (height = column/storey height, same length unit as the result)."""
    drifts = list(drifts_pct) if drifts_pct else ACI_374_1_DRIFTS_PCT
    return increasing_amplitude([d / 100.0 * float(height) for d in drifts], cycles_per_level,
                                positive_first, return_to_zero)

def one_sided_cycles(amplitudes, cycles_per_amp=1, return_to_zero=True):
    """0 -> a1 -> 0 -> a1 ... -> a2 -> 0 ... : cyclic pushover that never reverses sign."""
    out = []
    for amp in amplitudes:
        for _ in range(int(cycles_per_amp)):
            out += [float(amp), 0.0]
    if not return_to_zero and out:
        out.pop()
    return out

def generate(kind, **kw):
    if kind == "Monotonic":
        return monotonic(kw["target"])
    if kind == "Symmetric cycles":
        return symmetric_cycles(kw["amplitude"], kw.get("cycles", 3), kw.get("positive_first", True))
    if kind == "Increasing amplitude":
        return increasing_amplitude(kw["amplitudes"], kw.get("cycles", 3), kw.get("positive_first", True))
    if kind == "Drift-based (ACI 374.1)":
        return drift_based(kw["height"], kw.get("drifts_pct"), kw.get("cycles", 3), kw.get("positive_first", True))
    if kind == "One-sided cycles":
        return one_sided_cycles(kw["amplitudes"], kw.get("cycles", 1))
    raise ValueError(f"unknown protocol '{kind}'")

def count_steps(targets, step):
    """Number of increments the solver will take (mirrors OS_OP's path loop)."""
    cur, n = 0.0, 0
    for t in targets:
        d = abs(t - cur)
        if d > 1e-15:
            n += max(1, int(math.ceil(d / step - 1e-9)))
        cur = t
    return n

def parse_list(text):
    """'0.25, 0.5; 1.0' -> [0.25, 0.5, 1.0].  Raises ValueError on a bad token."""
    import re
    return [float(t) for t in re.split(r"[\s,;]+", text.strip()) if t]
