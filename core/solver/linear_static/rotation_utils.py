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
        angle = np.arccos(cos_a)
        R_delta = rodrigues(axis * angle)

    return R_delta @ R_r_old
