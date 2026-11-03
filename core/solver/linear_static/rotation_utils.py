import numpy as np

"""
Rotation utilities for the 3D corotational beam formulation.

Core idea (Piece 1 of the large-displacement engine):
Rotations in 3D do not add like numbers - they compose like matrices.
A node's accumulated orientation must be tracked as a 3x3 rotation matrix,
updated each converged load step by COMPOSING (matrix-multiplying) the
incremental rotation onto the previous orientation, never by summing
rotation vectors.

Reference: Rodrigues' rotation formula (see e.g. Moon et al. 2023, Eqs 1-9;
Crisfield 1991).
"""

def skew(v):
    """3x3 skew-symmetric matrix S(v) such that S(v) @ x = v cross x."""
    v = np.asarray(v, dtype=float).flatten()
    return np.array([
        [0.0,   -v[2],  v[1]],
        [v[2],   0.0,  -v[0]],
        [-v[1],  v[0],  0.0]
    ])

def rodrigues(theta_vec):
    """
    Rotation matrix R(theta) from a rotation vector theta_vec, via the
    closed-form Rodrigues formula:

        R = I + (sin(theta)/theta) S + ((1-cos(theta))/theta^2) S @ S

    where theta = |theta_vec| and S = skew(theta_vec).

    theta_vec direction = rotation axis, |theta_vec| = rotation angle (rad).
    Valid for ANY rotation magnitude (not just small angles) - this is what
    makes it usable for large-rotation problems.
    """
    theta_vec = np.asarray(theta_vec, dtype=float).flatten()
    theta = np.linalg.norm(theta_vec)
    S = skew(theta_vec)

    if theta < 1e-10:
                                                                  
        return np.eye(3) + S + 0.5 * (S @ S)

    A = np.sin(theta) / theta
    B = (1.0 - np.cos(theta)) / (theta * theta)
    return np.eye(3) + A * S + B * (S @ S)

def rotation_to_vector(R):
    """
    Inverse Rodrigues (the 'log map'): recover the rotation vector theta_vec
    from a rotation matrix R, such that rodrigues(rotation_to_vector(R)) == R.

    Used to extract the LOCAL deformational rotation (small, after rigid-body
    filtering) as a 3-component vector we can feed into beam bending/torsion
    formulas.
    """
    R = np.asarray(R, dtype=float)
    tr = np.trace(R)
    cos_theta = np.clip((tr - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_theta)

    if theta < 1e-8:
                                                                        
        v = np.array([R[2, 1] - R[1, 2],
                      R[0, 2] - R[2, 0],
                      R[1, 0] - R[0, 1]]) / 2.0
        return v

    if np.pi - theta < 1e-6:
                                                                          
        B = (R + np.eye(3)) / 2.0
                                                                            
        k = np.argmax(np.diag(B))
        axis = B[:, k] / np.sqrt(max(B[k, k], 1e-14))
        return axis * theta

    S = (R - R.T) / (2.0 * np.sin(theta))
    v = np.array([S[2, 1], S[0, 2], S[1, 0]])
    return v * theta

def compose(R_increment, R_old):
    """
    Compose an incremental rotation onto an existing orientation:
        R_new = R_increment @ R_old
    This is the operation that REPLACES naive rotation-vector addition
    once rotations stop being small.
    """
    return R_increment @ R_old

def update_corotational_frame(R_r_old, e1_new):
    """
    Rotation-minimizing update of an element's corotational frame.

    Given the element's previous local frame R_r_old (columns = local
    x,y,z axes in global coordinates) and the NEW chord direction e1_new
    (unit vector along the deformed element axis), returns the new frame
    R_r_new obtained by applying the *minimal* rotation that swings the
    old x-axis onto the new x-axis - i.e. the frame's roll about its own
    axis is left undisturbed by this update. This keeps the corotational
    frame continuous step-to-step without needing to re-derive it from
    scratch (and without the redundant-DOF bookkeeping of averaging both
    nodes' triads directly).
    """
    e1_old = R_r_old[:, 0]
    e1_new = np.asarray(e1_new, dtype=float)
    e1_new = e1_new / np.linalg.norm(e1_new)

    cos_a = np.clip(np.dot(e1_old, e1_new), -1.0, 1.0)
    axis = np.cross(e1_old, e1_new)
    axis_norm = np.linalg.norm(axis)

    if axis_norm < 1e-12:
        if cos_a > 0:
            R_delta = np.eye(3)
        else:
                                                                             
            perp = np.array([1.0, 0.0, 0.0]) if abs(e1_old[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
            axis = np.cross(e1_old, perp)
            axis = axis / np.linalg.norm(axis)
            R_delta = rodrigues(axis * np.pi)
    else:
        axis = axis / axis_norm
                                                                               
        angle = np.arctan2(axis_norm, cos_a)
        R_delta = rodrigues(axis * angle)

    return R_delta @ R_r_old

def skew_batch(v):
    """v: (N,3) -> (N,3,3), batched version of skew()."""
    v = np.asarray(v, dtype=float)
    N = v.shape[0]
    S = np.zeros((N, 3, 3))
    S[:, 0, 1] = -v[:, 2]; S[:, 0, 2] =  v[:, 1]
    S[:, 1, 0] =  v[:, 2]; S[:, 1, 2] = -v[:, 0]
    S[:, 2, 0] = -v[:, 1]; S[:, 2, 1] =  v[:, 0]
    return S

def rodrigues_batch(theta_vecs):
    """
    theta_vecs: (N,3) -> R: (N,3,3). Batched Rodrigues formula, identical
    branch structure (small-angle series vs closed form) to rodrigues().
    """
    theta_vecs = np.asarray(theta_vecs, dtype=float)
    N = theta_vecs.shape[0]
    theta = np.linalg.norm(theta_vecs, axis=1)                
    S = skew_batch(theta_vecs)                                   
    S2 = np.einsum('nij,njk->nik', S, S)
    eye = np.broadcast_to(np.eye(3), (N, 3, 3))

    small = theta < 1e-10
                                         
    R_small = eye + S + 0.5 * S2

    theta_safe = np.where(small, 1.0, theta)                                                       
    A = np.sin(theta_safe) / theta_safe
    B = (1.0 - np.cos(theta_safe)) / (theta_safe * theta_safe)
    R_full = eye + A[:, None, None] * S + B[:, None, None] * S2

    return np.where(small[:, None, None], R_small, R_full)

def rotation_to_vector_batch(Rs):
    """
    Rs: (N,3,3) -> (N,3). Batched inverse-Rodrigues (log map), same three
    branches (near-zero / near-pi / general) as rotation_to_vector(), with
    per-row branch selection.
    """
    Rs = np.asarray(Rs, dtype=float)
    N = Rs.shape[0]
    tr = np.trace(Rs, axis1=1, axis2=2)                        
    cos_theta = np.clip((tr - 1.0) / 2.0, -1.0, 1.0)
    theta = np.arccos(cos_theta)                               

    near_zero = theta < 1e-8
    near_pi = (np.pi - theta) < 1e-6

    v_zero = np.stack([
        Rs[:, 2, 1] - Rs[:, 1, 2],
        Rs[:, 0, 2] - Rs[:, 2, 0],
        Rs[:, 1, 0] - Rs[:, 0, 1],
    ], axis=1) / 2.0

    B = (Rs + np.broadcast_to(np.eye(3), (N, 3, 3))) / 2.0
    diagB = np.diagonal(B, axis1=1, axis2=2)                    
    k = np.argmax(diagB, axis=1)                               
    Bkk = diagB[np.arange(N), k]
    axis_pi = B[np.arange(N), :, k]                             
    denom = np.sqrt(np.maximum(Bkk, 1e-14))
    axis_pi = axis_pi / denom[:, None]
    v_pi = axis_pi * theta[:, None]

    sin_theta_safe = np.where(near_zero | near_pi, 1.0, np.sin(theta))
    S = (Rs - np.transpose(Rs, (0, 2, 1))) / (2.0 * sin_theta_safe[:, None, None])
    v_gen = np.stack([S[:, 2, 1], S[:, 0, 2], S[:, 1, 0]], axis=1) * theta[:, None]

    out = np.where(near_pi[:, None], v_pi, v_gen)
    out = np.where(near_zero[:, None], v_zero, out)
    return out
