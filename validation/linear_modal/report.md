# Linear static and modal verification

100 shared models; 100/100 static PASS; 100/100 modal PASS.

The reference is independent force-flexibility finite-element assembly. Continuum analytical comparisons are recorded separately in each expected.json. A numerical reference match alone does not establish convergence to continuum mechanics.

| Family | Models | Static pass | Modal pass |
|---|---:|---:|---:|
| cantilever_tip_y | 5 | 5 | 5 |
| cantilever_tip_z | 5 | 5 | 5 |
| inclined_cantilever | 5 | 5 | 5 |
| cantilever_udl | 5 | 5 | 5 |
| cantilever_tip_moment | 5 | 5 | 5 |
| axial_bar | 5 | 5 | 5 |
| torsion_bar | 5 | 5 | 5 |
| simply_supported_point | 5 | 5 | 5 |
| simply_supported_udl | 5 | 5 | 5 |
| fixed_fixed_point | 5 | 5 | 5 |
| fixed_fixed_udl | 5 | 5 | 5 |
| propped_udl | 5 | 5 | 5 |
| continuous_two_span | 5 | 5 | 5 |
| rigid_portal | 5 | 5 | 5 |
| pinned_base_portal | 5 | 5 | 5 |
| released_beam_portal | 5 | 5 | 5 |
| two_story_frame | 5 | 5 | 5 |
| space_frame | 5 | 5 | 5 |
| stepped_axial_chain | 5 | 5 | 5 |
| elastic_support_beam | 5 | 5 | 5 |

Failing cases:


Runtime: 150.4 seconds. Python 3.12.8, NumPy 1.26.4, SciPy 1.17.0.
Git commit: d633b8aefb70d6edb9fff4cbcc9def8f8c86a166. See summary.json for exact checks and tolerances.
