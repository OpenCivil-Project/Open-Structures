"""
app/solver_mesh_remap.py

Bridges solver-meshed runs back to the live (un-meshed) model.

Design
------
A solver-mesh run solves a meshed COPY of the model (see StructuralModel.write_solver_copy).
Instead of rewriting every result file so that split frames / divided shells map back to the
original IDs (lossy: mid-span shell forces can't be folded into one frame), we:

  1. keep the meshed copy (<model dir>/.solver_mesh/<model>.mf + .meshmap.json) after the run,
  2. tag every result file with info["solver_mesh"] = True,
  3. let consumers (force diagrams) load that meshed model and read the *unchanged* result and
     matrices files against it. Segment IDs in the files then match the meshed model exactly.

Node results are left complete on disk, because the meshed model's segment end nodes (new mesh
nodes) need their displacements. strip_to_live_nodes() gives a filtered view for UI tables that
only know the live nodes.
"""
import os
import json
import shutil

MESH_DIR = ".solver_mesh"
_NODE_DICT_KEYS = ("displacements", "_base_displacements", "reactions", "reactions_max", "reactions_min")
_cache = {}                                                      

def solver_mesh_dir(live_path):
    return os.path.join(os.path.dirname(os.path.abspath(live_path)), MESH_DIR)

def solver_mesh_model_path(live_path):
    return os.path.join(solver_mesh_dir(live_path), os.path.basename(live_path))

def clear_mesh_dir(live_path):
    """Remove a stale meshed copy (used when a run did not use a solver mesh)."""
    shutil.rmtree(solver_mesh_dir(live_path), ignore_errors=True)
    _cache.pop(live_path, None)

def finalize_mesh_dir(work_dir, keep_model_path):
    """After results were moved out: keep only the meshed model and its mesh map."""
    keep = {os.path.abspath(keep_model_path), os.path.abspath(keep_model_path) + ".meshmap.json"}
    for name in os.listdir(work_dir):
        full = os.path.abspath(os.path.join(work_dir, name))
        if full in keep:
            continue
        try:
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            else:
                os.remove(full)
        except OSError:
            pass
    _cache.clear()

def remap_results_file(path, live_node_ids, dest_dir=None):
    """
    Tag a result file written inside the solver work dir, and repoint any file paths it
    stores (LTHA history .npz, matrices) from the work dir to dest_dir (default: the model dir).
    The history .npz is moved. Node-keyed data is left complete (see module docstring).
    Returns the number of mesh-only nodes found in the displacements.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    work_dir = os.path.dirname(os.path.abspath(path))
    dest_dir = dest_dir or os.path.dirname(work_dir)

    live = {str(i) for i in live_node_ids}
    disp = data.get("displacements")
    extra = [k for k in disp if str(k) not in live] if isinstance(disp, dict) else []

    info = data.get("info")
    if not isinstance(info, dict):
        info = {}
        data["info"] = info
    info["solver_mesh"] = True
    info["solver_mesh_extra_nodes"] = len(extra)

    for key in ("history_path", "matrices_path", "matrices_file"):
        value = data.get(key)
        if not isinstance(value, str) or not value:
            continue
        if os.path.normcase(os.path.dirname(os.path.abspath(value))) != os.path.normcase(work_dir):
            continue
        new_path = os.path.join(dest_dir, os.path.basename(value))
        if key == "history_path" and os.path.exists(value):
            if os.path.exists(new_path):
                os.remove(new_path)
            shutil.move(value, new_path)
        data[key] = new_path

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return len(extra)

def strip_to_live_nodes(results, live_node_ids):
    """
    Filtered shallow copy of a results dict for UI code that only knows the live nodes.
    The full displacements stay available under results["solver_displacements"].
    """
    live = {str(i) for i in live_node_ids}
    out = dict(results)
    for key in _NODE_DICT_KEYS:
        d = results.get(key)
        if isinstance(d, dict):
            out[key] = {k: v for k, v in d.items() if str(k) in live}
    if isinstance(results.get("displacements"), dict):
        out["solver_displacements"] = results["displacements"]
    rn = results.get("restrained_nodes")
    if isinstance(rn, list):
        out["restrained_nodes"] = [n for n in rn if str(n) in live]
    shapes = results.get("mode_shapes")
    if isinstance(shapes, dict):
        out["mode_shapes"] = {m: ({k: v for k, v in s.items() if str(k) in live} if isinstance(s, dict) else s)
                              for m, s in shapes.items()}
    return out

def load_mesh_context(live_path):
    """
    Returns (meshed_model, mesh_map) for the last solver-meshed run of this project, or None.
    mesh_map = {"area_parent": {child_id: parent_id},
                "frame_split": {orig_id: {"segments": [...], "boundaries": [...]}}}
    The meshed model gets file_path = live_path, so combination / matrices lookups hit the live files.
    Cached by file mtime.
    """
    if not live_path:
        return None
    mf = solver_mesh_model_path(live_path)
    if not os.path.exists(mf):
        return None
    key = (mf, os.path.getmtime(mf))
    hit = _cache.get(live_path)
    if hit and hit[0] == key:
        return hit[1], hit[2]

    from core.model import StructuralModel
    model = StructuralModel("SolverMesh")
    model.load_from_file(mf)
    model.file_path = live_path

    mesh_map = {"area_parent": {}, "frame_split": {}}
    try:
        with open(mf + ".meshmap.json", "r", encoding="utf-8") as f:
            raw = json.load(f)
        mesh_map["area_parent"] = {int(k): v for k, v in raw.get("area_parent", {}).items()}
        mesh_map["frame_split"] = {int(k): v for k, v in raw.get("frame_split", {}).items()}
    except (OSError, ValueError):
        pass

    _cache[live_path] = (key, model, mesh_map)
    return model, mesh_map

def expand_selected_frames(mesh_map, frame_ids):
    """Live frame ids -> live ids plus the segment ids they were split into."""
    out = list(frame_ids or [])
    for fid in frame_ids or []:
        out.extend(mesh_map.get("frame_split", {}).get(fid, {}).get("segments", []))
    return out
