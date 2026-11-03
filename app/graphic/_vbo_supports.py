import numpy as np
import pyqtgraph.opengl as gl

def build_ltha_spring_plates(nodes_dict, links_dict=None, link_props=None, scale=1.0):
    """
    LTHA-mode companion to build_boundary_visuals(): emits ONLY the fixed
    anchor/ground plate meshes for nodal springs and 1-joint links (the ends
    that never move). Build this once when LTHA playback starts and never
    touch it again -- VectorizedLTHAEngine.compute_all_springs() handles the
    moving coil lines every frame. 2-joint links have no fixed end, so they
    contribute nothing here.
    """
    mesh_verts, mesh_faces, mesh_colors = [], [], []
    mesh_idx_offset = 0
    s = scale * 6.0
    c_link = [0.0, 0.0, 0.0, 1.0]

    def add_box(cx, cy, cz, wx, wy, wz, color):
        nonlocal mesh_idx_offset
        v = [
            [cx-wx, cy-wy, cz-wz], [cx+wx, cy-wy, cz-wz], [cx+wx, cy+wy, cz-wz], [cx-wx, cy+wy, cz-wz],
            [cx-wx, cy-wy, cz+wz], [cx+wx, cy-wy, cz+wz], [cx+wx, cy+wy, cz+wz], [cx-wx, cy+wy, cz+wz]
        ]
        f = [
            [0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
            [0, 3, 7], [0, 7, 4], [1, 2, 6], [1, 6, 5]
        ]
        mesh_verts.extend(v)
        mesh_faces.extend([[i + mesh_idx_offset for i in face] for face in f])
        for _ in range(8): mesh_colors.append(color)
        mesh_idx_offset += 8

    for n_id, node in nodes_dict.items():
        x, y, z = node.x, node.y, node.z
        k = getattr(node, 'spring_matrix', None)
        if k is not None:
            diag = np.diag(np.diag(k))
            off_diag = k - diag
            if not np.any(np.abs(off_diag) > 1e-6):
                axes = [
                    (k[0, 0], np.array([1.0, 0.0, 0.0]), [0.90, 0.45, 0.45, 1.0]),
                    (k[1, 1], np.array([0.0, 1.0, 0.0]), [0.45, 0.75, 0.50, 1.0]),
                    (k[2, 2], np.array([0.0, 0.0, -1.0]), [0.45, 0.60, 0.90, 1.0]),
                    (k[3, 3], np.array([-1.0, 0.0, 0.0]), [0.95, 0.75, 0.40, 1.0]),
                    (k[4, 4], np.array([0.0, -1.0, 0.0]), [0.95, 0.75, 0.40, 1.0]),
                    (k[5, 5], np.array([0.0, 0.0, 1.0]), [0.95, 0.75, 0.40, 1.0]),
                ]
                length = 22 * scale
                radius = 3 * scale
                for kval, axis_vec, color in axes:
                    if abs(kval) > 1e-6:
                        end_pt = np.array([x, y, z]) + axis_vec * length
                        plate_half = radius * 1.15
                        thin = s * 0.15
                        wx = thin if abs(axis_vec[0]) > 0.5 else plate_half
                        wy = thin if abs(axis_vec[1]) > 0.5 else plate_half
                        wz = thin if abs(axis_vec[2]) > 0.5 else plate_half
                        add_box(end_pt[0], end_pt[1], end_pt[2], wx, wy, wz, color)

    if links_dict:
        link_props = link_props or {}
        for lid, link in links_dict.items():
            prop = link_props.get(link['prop_name'])
            if not prop:
                continue
            nodes = link['nodes']
            if len(nodes) == 1:
                nid = nodes[0]
                n = nodes_dict.get(nid) or nodes_dict.get(str(nid))
                if n:
                    ground_z = n.z - s * 2.2
                    add_box(n.x, n.y, ground_z - s*0.1, s*1.0, s*1.0, s*0.1, c_link)

    mesh_item = None
    if mesh_verts:
        mesh_item = gl.GLMeshItem(
            vertexes=np.array(mesh_verts, dtype=np.float32),
            faces=np.array(mesh_faces, dtype=np.int32),
            vertexColors=np.array(mesh_colors, dtype=np.float32),
            smooth=False, shader='balloon', glOptions='opaque'
        )
    return mesh_item

_CUBE = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                  [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]], dtype=np.float64)
_BOX_FACES = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
                       [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
                       [0, 3, 7], [0, 7, 4], [1, 2, 6], [1, 6, 5]], dtype=np.int64)
_BOX_EDGES = np.array([[0, 1], [1, 2], [2, 3], [3, 0],
                       [4, 5], [5, 6], [6, 7], [7, 4],
                       [0, 4], [1, 5], [2, 6], [3, 7]], dtype=np.int64)
_PYR_FACES = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
                       [1, 2, 3], [1, 3, 4]], dtype=np.int64)
_CUSTOM_FACES = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1],
                          [5, 2, 1], [5, 3, 2], [5, 4, 3], [5, 1, 4]], dtype=np.int64)

def _sphere_template(bands=8):
    """Unit-sphere verts (V,3) and faces (F,3), same layout the old add_sphere() produced."""
    i = np.arange(bands + 1)[:, None]
    j = np.arange(bands)[None, :]
    lat = np.pi * i / bands
    lon = 2 * np.pi * j / bands
    z = np.broadcast_to(np.cos(lat), (bands + 1, bands))
    r = np.sin(lat)
    x = r * np.cos(lon)
    y = r * np.sin(lon)
    verts = np.stack([x, y, z], axis=-1).reshape(-1, 3)

    faces = []
    for ii in range(bands):
        for jj in range(bands):
            row1, row2 = ii * bands, (ii + 1) * bands
            c1, c2 = jj, (jj + 1) % bands
            p1, p2, p3, p4 = row1 + c1, row1 + c2, row2 + c2, row2 + c1
            faces.append([p1, p2, p4])
            faces.append([p2, p3, p4])
    return verts, np.array(faces, dtype=np.int64)

_SPHERE_V, _SPHERE_F = _sphere_template(8)

class _MeshAcc:
    """Collects many instances of small meshes into one big vertex/face/colour array."""
    def __init__(self):
        self._v, self._f, self._c = [], [], []
        self.n = 0

    def add(self, verts, faces, colors):
        """verts (n,V,3) instance vertices, faces (F,3) local indices, colors (n,4)."""
        n = verts.shape[0]
        if n == 0:
            return
        V = verts.shape[1]
        self._v.append(verts.reshape(-1, 3))
        offs = self.n + np.arange(n, dtype=np.int64) * V
        self._f.append((faces[None, :, :] + offs[:, None, None]).reshape(-1, 3))
        self._c.append(np.repeat(np.asarray(colors, dtype=np.float64), V, axis=0))
        self.n += n * V

    def add_boxes(self, centers, halfs, colors):
        centers = np.asarray(centers, dtype=np.float64).reshape(-1, 3)
        halfs = np.broadcast_to(np.asarray(halfs, dtype=np.float64), centers.shape)
        colors = np.broadcast_to(np.asarray(colors, dtype=np.float64), (len(centers), 4))
        self.add(centers[:, None, :] + _CUBE[None] * halfs[:, None, :], _BOX_FACES, colors)

    def add_template(self, centers, local_verts, faces, color):
        centers = np.asarray(centers, dtype=np.float64).reshape(-1, 3)
        colors = np.broadcast_to(np.asarray(color, dtype=np.float64), (len(centers), 4))
        self.add(centers[:, None, :] + local_verts[None], faces, colors)

    def result(self):
        if self.n == 0:
            return None
        return (np.concatenate(self._v).astype(np.float32),
                np.concatenate(self._f).astype(np.int32),
                np.concatenate(self._c).astype(np.float32))

def _coil_lines(P1, P2, color, radius, turns, lead_frac):
    """
    Vectorised version of the old add_line_spring(): for m springs returns
    (verts (K,3), colors (K,4)) as GL_LINES pairs.  Each spring is a straight
    lead, a helical coil and a straight lead.  Springs shorter than 1e-6 are skipped.
    """
    P1 = np.asarray(P1, dtype=np.float64).reshape(-1, 3)
    P2 = np.asarray(P2, dtype=np.float64).reshape(-1, 3)
    color = np.broadcast_to(np.asarray(color, dtype=np.float64), (len(P1), 4))
    radius = np.broadcast_to(np.asarray(radius, dtype=np.float64), (len(P1),))

    vec = P2 - P1
    L = np.linalg.norm(vec, axis=1)
    ok = L >= 1e-6
    if not ok.any():
        return np.zeros((0, 3)), np.zeros((0, 4))
    P1, P2, vec, L, color, radius = P1[ok], P2[ok], vec[ok], L[ok], color[ok], radius[ok]
    m = len(P1)

    u = vec / L[:, None]
    up = np.tile(np.array([0.0, 0.0, 1.0]), (m, 1))
    up[np.abs(u[:, 2]) > 0.99] = [0.0, 1.0, 0.0]
    v = np.cross(u, up)
    v /= np.linalg.norm(v, axis=1)[:, None]
    w = np.cross(u, v)

    lead1_end = P1 + u * (L * lead_frac)[:, None]
    lead2_start = P2 - u * (L * lead_frac)[:, None]
    coil_len = L * (1.0 - 2.0 * lead_frac)

    total = turns * 12
    t = np.arange(1, total + 1) / total
    ang = t * turns * 2 * np.pi
    centers = lead1_end[:, None, :] + u[:, None, :] * (coil_len[:, None, None] * t[None, :, None])
    pts = centers + radius[:, None, None] * (np.cos(ang)[None, :, None] * v[:, None, :]
                                             + np.sin(ang)[None, :, None] * w[:, None, :])

    poly = np.concatenate([P1[:, None], lead1_end[:, None], pts,
                           lead2_start[:, None], P2[:, None]], axis=1)                        
    verts = np.stack([poly[:, :-1], poly[:, 1:]], axis=2).reshape(-1, 3)                        
    cols = np.repeat(color, (total + 3) * 2, axis=0)
    return verts, cols

def _wire_boxes(centers, halfs, color):
    centers = np.asarray(centers, dtype=np.float64).reshape(-1, 3)
    corners = centers[:, None, :] + _CUBE[None] * halfs
    verts = corners[:, _BOX_EDGES, :].reshape(-1, 3)
    cols = np.tile(np.asarray(color, dtype=np.float64), (len(verts), 1))
    return verts, cols

def build_boundary_visuals(nodes_dict, links_dict=None, link_props=None, scale=1.0,
                            show_1joint_links=True, show_2joint_links=True,
                            show_support_glyphs=True,
                            node_displacements=None, disp_scale=0.0):
    """
    Generates unified boundary conditions in a single pass:
    - Meshes: Fixed, Pinned, Roller, Custom supports + Coupled Spring warnings.
    - Lines: Standard 6-DOF springs.

    node_displacements: optional {node_id: [dx,dy,dz,rx,ry,rz]} results dict.
    disp_scale: scalar multiplier applied to node_displacements (e.g. deflection_scale * anim_factor).
    When provided, nodal springs and 1-joint links attach to the DISPLACED node
    position, while their ground/anchor ends stay fixed at the node's original
    (undeformed) position. 2-joint links are never displaced.
    """
    s = scale * 6.0

    c_x = [0.90, 0.45, 0.45, 1.0]
    c_y = [0.45, 0.75, 0.50, 1.0]
    c_z = [0.45, 0.60, 0.90, 1.0]
    c_rot = [0.95, 0.75, 0.40, 1.0]
    c_link = [0.0, 0.0, 0.0, 1.0]

    mesh = _MeshAcc()
    line_v, line_c = [], []

    node_displacements = node_displacements or {}
    use_disp = bool(disp_scale) and bool(node_displacements)

    def displaced(n_id, base):
        if use_disp:
            d = node_displacements.get(str(n_id))
            if d is not None:
                return base + np.array(d[:3], dtype=np.float64) * disp_scale
        return base

    fixed, pinned, roller, custom = [], [], [], []
    spr_ids, spr_base, spr_K = [], [], []

    for n_id, node in nodes_dict.items():
        r = getattr(node, 'restraints', None)
        if show_support_glyphs and r is not None and any(r):
            pos = (node.x, node.y, node.z)
            if all(r[:3]) and all(r[3:]):
                fixed.append(pos)
            elif all(r[:3]) and not any(r[3:]):
                pinned.append(pos)
            elif r[2] and not any(r[0:2]) and not any(r[3:]):
                roller.append(pos)
            else:
                custom.append(pos)

        k = getattr(node, 'spring_matrix', None)
        if k is not None:
            spr_ids.append(n_id)
            spr_base.append((node.x, node.y, node.z))
            spr_K.append(k)

    plate_half = np.array([1.2 * s, 1.2 * s, 0.1 * s])

    if fixed:
        P = np.array(fixed, dtype=np.float64)
        col = [0.40, 0.45, 0.50, 1.0]
        mesh.add_boxes(P + [0, 0, -s], [0.8 * s, 0.8 * s, s], col)
        mesh.add_boxes(P + [0, 0, -2.1 * s], plate_half, col)

    if pinned:
        P = np.array(pinned, dtype=np.float64)
        col = [0.25, 0.55, 0.75, 1.0]
        w, h = 0.8 * s, 1.8 * s
        pyr = np.array([[0, 0, 0], [-w, -w, -h], [w, -w, -h], [w, w, -h], [-w, w, -h]])
        mesh.add_template(P, pyr, _PYR_FACES, col)
        mesh.add_boxes(P + [0, 0, -1.9 * s], plate_half, col)

    if roller:
        P = np.array(roller, dtype=np.float64)
        col = [0.20, 0.65, 0.50, 1.0]
        sph = _SPHERE_V * (0.9 * s) + np.array([0.0, 0.0, -0.9 * s])
        mesh.add_template(P, sph, _SPHERE_F, col)
        mesh.add_boxes(P + [0, 0, -1.9 * s], plate_half, col)

    if custom:
        P = np.array(custom, dtype=np.float64)
        col = [0.85, 0.55, 0.20, 1.0]
        w, h = 0.6 * s, s
        pyr = np.array([[0, 0, 0], [-w, -w, -h], [w, -w, -h], [w, w, -h], [-w, w, -h]])
        mesh.add_template(P, pyr, _PYR_FACES, col)
        bip = np.array([[0, 0, 0], [-w, -w, -s], [w, -w, -s], [w, w, -s], [-w, w, -s], [0, 0, -2 * s]])
        mesh.add_template(P, bip, _CUSTOM_FACES, col)

    if spr_K:
        base = np.array(spr_base, dtype=np.float64)
        struct = np.array([displaced(i, b) for i, b in zip(spr_ids, base)], dtype=np.float64)\
            if use_disp else base
        K = np.asarray(np.stack(spr_K), dtype=np.float64)                                
        eye = np.eye(6, dtype=bool)
        coupled = (np.abs(K[:, ~eye]) > 1e-6).any(axis=1)

        if coupled.any():
            wv, wc = _wire_boxes(base[coupled], 0.8 * s, [0.0, 0.0, 0.0, 1.0])
            line_v.append(wv); line_c.append(wc)

        simple = ~coupled
        if simple.any():
            length = 22 * scale
            radius = 3 * scale
            plate = radius * 1.15
            thin = s * 0.15
            axes = [
                (0, np.array([1.0, 0.0, 0.0]), c_x),
                (1, np.array([0.0, 1.0, 0.0]), c_y),
                (2, np.array([0.0, 0.0, -1.0]), c_z),
                (3, np.array([-1.0, 0.0, 0.0]), c_rot),
                (4, np.array([0.0, -1.0, 0.0]), c_rot),
                (5, np.array([0.0, 0.0, 1.0]), c_rot),
            ]
            for dof, axis_vec, col in axes:
                sel = simple & (np.abs(K[:, dof, dof]) > 1e-6)
                if not sel.any():
                    continue
                end_pt = base[sel] + axis_vec * length
                cv, cc = _coil_lines(struct[sel], end_pt, col, radius, 3, 0.2)
                line_v.append(cv); line_c.append(cc)
                halfs = np.where(np.abs(axis_vec) > 0.5, thin, plate)
                mesh.add_boxes(end_pt, halfs, col)

    if links_dict:
        link_props = link_props or {}
        one_base, one_p1 = [], []
        two_p1, two_p2 = [], []

        for lid, link in links_dict.items():
            prop = link_props.get(link['prop_name'])
            if not prop:
                continue
            nodes = link['nodes']

            if len(nodes) == 1:
                if not show_1joint_links:
                    continue
                nid = nodes[0]
                n = nodes_dict.get(nid) or nodes_dict.get(str(nid))
                if n:
                    b = np.array([n.x, n.y, n.z], dtype=np.float64)
                    one_base.append(b)
                    one_p1.append(displaced(nid, b))

            elif len(nodes) == 2:
                if not show_2joint_links:
                    continue
                nid_i, nid_j = nodes
                n_i = nodes_dict.get(nid_i) or nodes_dict.get(str(nid_i))
                n_j = nodes_dict.get(nid_j) or nodes_dict.get(str(nid_j))
                if n_i and n_j:
                    two_p1.append(displaced(nid_i, np.array([n_i.x, n_i.y, n_i.z], dtype=np.float64)))
                    two_p2.append(displaced(nid_j, np.array([n_j.x, n_j.y, n_j.z], dtype=np.float64)))

        if one_base:
            B = np.array(one_base)
            ground = B.copy()
            ground[:, 2] = B[:, 2] - s * 2.2
            cv, cc = _coil_lines(np.array(one_p1), ground, c_link, s * 0.5, 4, 0.15)
            line_v.append(cv); line_c.append(cc)
            mesh.add_boxes(ground + [0, 0, -s * 0.1], [s, s, s * 0.1], c_link)

        if two_p1:
            cv, cc = _coil_lines(np.array(two_p1), np.array(two_p2), c_link, s * 0.6, 5, 0.4)
            line_v.append(cv); line_c.append(cc)

    mesh_item = None
    res = mesh.result()
    if res is not None:
        mv, mf, mc = res
        mesh_item = gl.GLMeshItem(
            vertexes=mv, faces=mf, vertexColors=mc,
            smooth=False, shader='balloon', glOptions='opaque'
        )

    line_item = None
    if line_v:
        lv = np.concatenate(line_v).astype(np.float32)
        lc = np.concatenate(line_c).astype(np.float32)
        if len(lv):
            line_item = gl.GLLinePlotItem(pos=lv, color=lc, mode='lines', width=1.75, antialias=True)

    return mesh_item, line_item
