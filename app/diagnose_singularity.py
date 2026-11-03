"""
diagnose_singularity.py  -  finds the unsupported / floppy parts of the model.

Assembles K exactly like the solver, then
  1) splits the model into physically connected parts and flags every part that has NO support
     (no restraint, no spring) - a floating body has 6 free rigid-body motions,
  2) computes the 12 smallest eigenvalues of the free-DOF stiffness matrix. An eigenvalue ~0 is a
     motion that costs no energy (rigid-body mode or mechanism): the solver's answer on those DOFs is
     arbitrary, and changes with rounding,
  3) shows which nodes / DOFs take part in each such mode.

    python -u diagnose_singularity.py "E:\\OpenCivil\\SimpleModel\\Full_Model_DoNotRun_JustForShow.mf" DEAD

Takes ~20-60 s on a 46k-DOF model. Writes only to your temp folder.
"""
import contextlib, io, os, sys, tempfile, time
import numpy as np
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import eigsh

DOF = ["UX", "UY", "UZ", "RX", "RY", "RZ"]

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return 2
    mf = os.path.abspath(args[0]); case = args[1] if len(args) > 1 else "DEAD"
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "app"), here):
        if p not in sys.path:
            sys.path.insert(0, p)
    import core.solver.linear_static.main_engine as ME

    t0 = time.perf_counter()
    spy_path = os.path.join(tempfile.gettempdir(), "oc_diag_matrices.json")
    with contextlib.redirect_stdout(io.StringIO()):
        dm = ME.DataManager(mf)
        dm.process_all(case_name=case)
        asm = ME.GlobalAssembler(dm, export_path=spy_path)
        K, P = asm.assemble_system()
    try:
        os.remove(spy_path)
    except OSError:
        pass
    print(f"assembled in {time.perf_counter() - t0:.1f}s:  {len(dm.nodes)} nodes, {dm.total_dofs} DOFs")
    if getattr(asm, "T", None) is not None:
        print("This model uses rigid diaphragms (T matrix); this script does not handle that case yet."); return 1

    K = sp.csc_matrix(K)
    n = dm.total_dofs
    nn = n // 6
    node_by_idx = {nd["idx"]: nd for nd in dm.nodes}

    is_free = np.ones(n, bool)
    for nd in dm.nodes:
        s = nd["idx"] * 6
        for i in range(6):
            if nd["restraints"][i] or not dm.active_dofs[i]:
                is_free[s + i] = False
    spring_nodes = [nd for nd in dm.nodes if nd.get("spring_matrix") is not None]
    cnt = np.zeros(6, int)
    for nd in spring_nodes:
        d = np.abs(np.diag(np.asarray(nd["spring_matrix"], float)))
        cnt += (d > 0).astype(int)
    print(f"\nSUPPORTS: restrained DOFs = {int((~is_free).sum())}   nodes with springs = {len(spring_nodes)}")
    print("  spring stiffness present on:  " + "   ".join(f"{DOF[i]}: {cnt[i]} nodes" for i in range(6)))

    def supported(nd):
        return any(nd["restraints"]) or (nd.get("spring_matrix") is not None and np.abs(np.asarray(nd["spring_matrix"])).max() > 0)

    C = K.tocoo()
    r, c = C.row // 6, C.col // 6
    m = r != c
    A = sp.coo_matrix((np.ones(int(m.sum())), (r[m], c[m])), shape=(nn, nn))
    ncomp, labels = connected_components(A, directed=False)
    print(f"\nCONNECTED PARTS: {ncomp}")
    comps = []
    for k in range(ncomp):
        idxs = np.flatnonzero(labels == k)
        sup = any(supported(node_by_idx[i]) for i in idxs if i in node_by_idx)
        comps.append((len(idxs), k, sup, idxs))
    comps.sort(reverse=True)
    for size, k, sup, idxs in comps[:15]:
        tag = "supported" if sup else "NO SUPPORT  <-- floating body"
        print(f"  part {k:>4}: {size:>6} nodes   {tag}")
        if not sup:
            sample = [node_by_idx[i] for i in idxs[:5] if i in node_by_idx]
            print("      e.g. " + ", ".join(f"node {s['id']} @({s['coords'][0]:.2f},{s['coords'][1]:.2f},{s['coords'][2]:.2f})" for s in sample))
    if ncomp > 15:
        print(f"  ... {ncomp - 15} smaller parts not shown (unsupported ones among them: {sum(1 for x in comps[15:] if not x[2])})")

    free_idx = np.flatnonzero(is_free)
    Kff = K[free_idx, :][:, free_idx].tocsc()
    asym = abs(Kff - Kff.T).max() / max(abs(Kff).max(), 1e-300)
    dref = float(np.median(np.abs(Kff.diagonal())))
    print(f"\nFREE system: {Kff.shape[0]} equations, asymmetry {asym:.1e}, median diagonal {dref:.3e}")
    t1 = time.perf_counter()
    k = max(1, min(12, Kff.shape[0] - 2))
    vals, vecs = eigsh(Kff, k=k, sigma=-1.0, which="LM")
    o = np.argsort(vals); vals, vecs = vals[o], vecs[:, o]
    print(f"12 smallest eigenvalues ({time.perf_counter() - t1:.1f}s):   lambda / median-diagonal")
    n_null = 0
    for i, v in enumerate(vals):
        ratio = v / dref
        kind = "NULL (free motion)" if ratio < 1e-9 else ("very soft" if ratio < 1e-5 else "ok")
        n_null += ratio < 1e-9
        print(f"  {i + 1:>2}. {v:>12.4e}   {ratio:>10.2e}   {kind}")

    if n_null > 1:
        print("\n(Several null modes form a group: the individual mode shapes below are arbitrary mixtures of the same\n free motions. The CONNECTED PARTS list above is the reliable place to look.)")
    for i in range(min(int(n_null), 3)):
        full = np.zeros(n); full[free_idx] = vecs[:, i]
        V = full.reshape(nn, 6)
        part = np.linalg.norm(V, axis=1)
        share = (V ** 2).sum(axis=0) / (V ** 2).sum()
        n_part = int((part > 0.1 * part.max()).sum())
        top = np.argsort(-part)[:5]
        print(f"\nNULL MODE {i + 1}: involves {n_part} of {nn} nodes;  energy by DOF: " + " ".join(f"{DOF[j]} {100 * share[j]:.0f}%" for j in range(6) if share[j] > 0.005))
        for t in top:
            nd = node_by_idx.get(int(t))
            if nd is None:
                continue
            comp = V[t] / max(np.abs(V[t]).max(), 1e-300)
            print(f"    node {nd['id']:>7} @({nd['coords'][0]:.2f},{nd['coords'][1]:.2f},{nd['coords'][2]:.2f})  mode shape (normalised): " + " ".join(f"{x:+.2f}" for x in comp))

    print("\nVERDICT:")
    n_float = sum(1 for x in comps if not x[2])
    if n_null == 0:
        print("  No zero-energy modes. The model is properly supported; the difference has another cause - send me this output.")
    else:
        print(f"  {int(n_null)} zero-energy mode(s) found; {n_float} part(s) have no support at all.\n"
              "  Displacements on those DOFs are ARBITRARY (they change with rounding and with solver details).\n"
              "  Fix the model's supports (or connect the floating parts) and the answers become unique.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
