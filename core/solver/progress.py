
def make_callback(signal_emit_fn=None):
    """
    Returns a progress_callback(stage: str, percent: int) function.
    If a Qt signal emit function is provided, it fires that signal.
    Always prints to terminal too — so CLI / headless runs still get logs.
    """
    def callback(stage: str, percent: int):
        print(f"  [{percent:3d}%] {stage}")
        if signal_emit_fn is not None:
            try:
                signal_emit_fn(stage, percent)
            except Exception:
                pass                                              
    return callback

def noop_callback(stage: str, percent: int):
    """A no-op callback for when no signal is connected."""
    print(f"  [{percent:3d}%] {stage}")
