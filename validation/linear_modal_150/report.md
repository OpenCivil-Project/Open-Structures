# Linear static and modal verification

150 shared models; 150/150 static PASS; 150/150 modal PASS.

The reference is independent force-flexibility finite-element assembly. Continuum analytical comparisons are recorded separately in each expected.json. A numerical reference match alone does not establish convergence to continuum mechanics.

| Family | Models | Static pass | Modal pass |
|---|---:|---:|---:|
| beam_mixed_tip_3d | 5 | 5 | 5 |
| beam_interior_point_force | 5 | 5 | 5 |
| beam_interior_point_moment | 5 | 5 | 5 |
| beam_triangular_load | 5 | 5 | 5 |
| beam_patch_trapezoid_load | 5 | 5 | 5 |
| beam_projected_gravity_load | 5 | 5 | 5 |
| beam_self_weight | 5 | 5 | 5 |
| beam_section_stiffness_modifiers | 5 | 5 | 5 |
| beam_two_pattern_superposition | 5 | 5 | 5 |
| beam_rigid_root_segment | 5 | 5 | 5 |
| mass_self_modifier_beam | 5 | 5 | 5 |
| mass_nodal_pattern_chain | 5 | 5 | 5 |
| mass_member_udl_chain | 5 | 5 | 5 |
| mass_member_point_chain | 5 | 5 | 5 |
| mass_self_plus_nodal_beam | 5 | 5 | 5 |
| mass_added_tip_link_beam | 5 | 5 | 5 |
| mass_fixedfixed_rotary_chain | 5 | 5 | 5 |
| support_tip_axial_spring_chain | 5 | 5 | 5 |
| support_coupled_tip_spring | 5 | 5 | 5 |
| support_uniform_foundation_chain | 5 | 5 | 5 |
| frame_asymmetric_multibay | 5 | 5 | 5 |
| frame_setback_three_storey | 5 | 5 | 5 |
| frame_braced_diamond | 5 | 5 | 5 |
| frame_mixed_supports_releases | 5 | 5 | 5 |
| frame_branched_cantilever_3d | 5 | 5 | 5 |
| frame_skew_roof_3d | 5 | 5 | 5 |
| frame_closed_tower_3d | 5 | 5 | 5 |
| frame_zigzag_cantilever_3d | 5 | 5 | 5 |
| frame_reversed_rolled_l_3d | 5 | 5 | 5 |
| frame_polygon_cantilever_3d | 5 | 5 | 5 |

Failing cases:


Runtime: 238.1 seconds. Python 3.12.8, NumPy 1.26.4, SciPy 1.17.0.
Git commit: d633b8aefb70d6edb9fff4cbcc9def8f8c86a166. See summary.json for exact checks and tolerances.
