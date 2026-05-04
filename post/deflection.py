import numpy as np

def get_deflected_shape(p1, p2, disp_i, disp_j, v1, v2, v3, scale=1.0, num_points=11, off_i=0.0, off_j=0.0):
    P1 = np.array(p1)
    P2 = np.array(p2)
    L_vec = P2 - P1
    L = np.linalg.norm(L_vec)
    
    if L < 1e-6: 
        return [(p1, v1, 0.0), (p2, v1, 0.0)]

    if off_i + off_j >= L:
        scale_off = (L / (off_i + off_j)) * 0.99
        off_i *= scale_off
        off_j *= scale_off

    L_flex = max(L - off_i - off_j, 1e-6)

    R = np.vstack([v1, v2, v3])
    
    u_global_i = np.array(disp_i[:3]) * scale
    theta_global_i = np.array(disp_i[3:]) * scale
    u_local_i = R @ u_global_i      
    theta_local_i = R @ theta_global_i 

    u_global_j = np.array(disp_j[:3]) * scale
    theta_global_j = np.array(disp_j[3:]) * scale
    u_local_j = R @ u_global_j
    theta_local_j = R @ theta_global_j

    u1_i, u1_j = u_local_i[0], u_local_j[0]
    v_i, v_j = u_local_i[1], u_local_j[1]
    dv_i, dv_j = theta_local_i[2], theta_local_j[2] 
    w_i, w_j = u_local_i[2], u_local_j[2]
    dw_i, dw_j = -theta_local_i[1], -theta_local_j[1]
    twist_i, twist_j = theta_local_i[0], theta_local_j[0]

    v_flex_i = v_i + dv_i * off_i
    w_flex_i = w_i + dw_i * off_i
    v_flex_j = v_j - dv_j * off_j
    w_flex_j = w_j - dw_j * off_j

    results = [] 
    steps = np.linspace(0, 1, num_points)
    axial_strain = (u1_j - u1_i) / L
    
    for s_flex in steps:
                                                                        
        x_val = off_i + s_flex * L_flex
        
        s2 = s_flex * s_flex
        s3 = s2 * s_flex
        
        H1 = 1.0 - 3.0*s2 + 2.0*s3
        H2 = (s_flex * L_flex) * (1.0 - s_flex)**2
        H3 = 3.0*s2 - 2.0*s3
        H4 = (s_flex * L_flex) * (s2 - s_flex)
        
        dH1 = -6.0*s_flex + 6.0*s2
        dH2 = L_flex * (1.0 - 4.0*s_flex + 3.0*s2)
        dH3 = 6.0*s_flex - 6.0*s2
        dH4 = L_flex * (3.0*s2 - 2.0*s_flex)

        disp_axial = u1_i + axial_strain * x_val
        disp_v = (H1 * v_flex_i) + (H2 * dv_i) + (H3 * v_flex_j) + (H4 * dv_j)
        disp_w = (H1 * w_flex_i) + (H2 * dw_i) + (H3 * w_flex_j) + (H4 * dw_j)
        
        d_axial_ds = L_flex + axial_strain * L_flex
        d_v_ds = (dH1 * v_flex_i + dH2 * dv_i + dH3 * v_flex_j + dH4 * dv_j)
        d_w_ds = (dH1 * w_flex_i + dH2 * dw_i + dH3 * w_flex_j + dH4 * dw_j)
        
        current_twist = twist_i + (twist_j - twist_i) * (x_val / L)

        local_pos = np.array([x_val + disp_axial, disp_v, disp_w])
        local_tangent = np.array([d_axial_ds, d_v_ds, d_w_ds])
        
        norm_t = np.linalg.norm(local_tangent)
        if norm_t > 1e-9: 
            local_tangent /= norm_t
        else: 
            local_tangent = np.array([1.0, 0, 0])

        global_pos = P1 + (R.T @ local_pos)
        global_tangent = R.T @ local_tangent 
        
        results.append((global_pos, global_tangent, current_twist))
        
    return results
