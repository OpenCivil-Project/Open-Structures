"""Fifty new elastic frame verification models (global IDs 201--250).

No production element or assembly functions are used by this generator.
Complex frames use the independently audited force-flexibility reference;
single-root frames also have exact static equilibrium reaction oracles.
"""
from __future__ import annotations

import math

from validation.linear_modal.models import _axis, _base, _check, _element, _force, _node, _udl


FAMILIES = (
    'frame_asymmetric_multibay',
    'frame_setback_three_storey',
    'frame_braced_diamond',
    'frame_mixed_supports_releases',
    'frame_branched_cantilever_3d',
    'frame_skew_roof_3d',
    'frame_closed_tower_3d',
    'frame_zigzag_cantilever_3d',
    'frame_reversed_rolled_l_3d',
    'frame_polygon_cantilever_3d',
)
PLANAR = [False, False, True, True, True, False]
ACTIVE_PLANAR = [True, True, False, False, False, True]


def _geometry(model, variant, planar=False):
    """Deduplicated joints and short member meshes, preserving physical IDs."""
    lookup = {}
    def joint(xyz):
        key = tuple(round(float(value), 10) for value in xyz)
        if key not in lookup:
            lookup[key] = _node(model, xyz, PLANAR if planar else [False] * 6)
        return lookup[key]
    def member(a, b, segments=1, release_i=False, release_j=False, beta=None):
        first = joint(a)
        ids = []
        moment_release = [False, False, False, False, False, True]
        for segment in range(1, segments + 1):
            point = [a[k] + (b[k] - a[k]) * segment / segments for k in range(3)]
            last = joint(point)
            roll = 0. if planar else (13. * variant + 7. * len(model['elements'])) % 100. - 50.
            ids.append(_element(model, first, last,
                                beta=roll if beta is None else beta,
                                release_i=moment_release if release_i and segment == 1 else None,
                                release_j=moment_release if release_j and segment == segments else None))
            first = last
        return ids
    return joint, member


def _fix(model, nid, restraints=None):
    next(node for node in model['nodes'] if node['id'] == nid)['restraints'] = list(restraints or [True] * 6)


def _root_reactions(model, spec, root):
    """Six exact support actions from force/moment equilibrium about the root."""
    coordinates = {n['id']: [n[key] for key in ('x', 'y', 'z')] for n in model['nodes']}
    root_xyz = coordinates[root]
    force, moment = [0.] * 3, [0.] * 3
    def add(vector, xyz, couple=(0., 0., 0.)):
        arm = [xyz[k] - root_xyz[k] for k in range(3)]
        cross = [arm[1] * vector[2] - arm[2] * vector[1],
                 arm[2] * vector[0] - arm[0] * vector[2],
                 arm[0] * vector[1] - arm[1] * vector[0]]
        for k in range(3):
            force[k] += vector[k]
            moment[k] += cross[k] + couple[k]
    elements = {el['id']: el for el in model['elements']}
    for load in model['loads']:
        if load['type'] == 'nodal':
            add([load.get(key, 0.) for key in ('fx', 'fy', 'fz')], coordinates[load['node_id']],
                [load.get(key, 0.) for key in ('mx', 'my', 'mz')])
        elif load['type'] == 'member_dist':
            element = elements[load['element_id']]
            a, b = coordinates[element['n1_id']], coordinates[element['n2_id']]
            delta = [b[k] - a[k] for k in range(3)]
            length = math.sqrt(sum(value * value for value in delta))
            vector = [load.get(key, 0.) for key in ('wx', 'wy', 'wz')]
            if load.get('coord', 'Global') == 'Local':
                axes = _axis(delta, element['beta'])
                vector = [sum(vector[j] * axes[j][k] for j in range(3)) for k in range(3)]
            add([value * length for value in vector], [(a[k] + b[k]) / 2 for k in range(3)])
        else:
            raise ValueError('Root-equilibrium oracle supports nodal and constant distributed loads only')
    for dof, value in enumerate(force + moment):
        _check(spec, root, dof, -value, 'Single-root equilibrium reaction',
               '-ΣF; -Σ(M + (r-r_root)×F)', result='reactions')


def _sparse_shuffle(model, spec, variant):
    """IDs are noncontiguous; record order deliberately differs from DOF order."""
    mapping = {node['id']: 107 + 19 * node['id'] + 3 * variant for node in model['nodes']}
    for node in model['nodes']:
        node['id'] = mapping[node['id']]
    for element in model['elements']:
        element['n1_id'] = mapping[element['n1_id']]
        element['n2_id'] = mapping[element['n2_id']]
    for load in model['loads']:
        if 'node_id' in load:
            load['node_id'] = mapping[load['node_id']]
    for check in spec['analytical_static']:
        check['node_id'] = mapping[check['node_id']]
    nodes = model['nodes']
    if variant % 2:
        model['nodes'] = nodes[::2] + nodes[1::2]
    else:
        model['nodes'] = nodes[::-1]
    spec['node_order'] = 'noncontiguous IDs; deterministic interleaving or reverse record order'


def _multibay(model, spec, v):
    w1, w2, h1, h2 = 3.1 + .45 * v, 4.2 + .3 * v, 2.5 + .15 * v, 3.2 + .18 * v
    joint, member = _geometry(model, v, planar=True)
    xs, ys = (0., w1, w1 + w2), (0., h1, h1 + h2)
    for x in xs:
        _fix(model, joint((x, 0., 0.)))
        for low, high in zip(ys[:-1], ys[1:]):
            member((x, low, 0.), (x, high, 0.), segments=2)
    for floor, y in enumerate(ys[1:], 1):
        for i in range(2):
            ids = member((xs[i], y, 0.), (xs[i+1], y, 0.), segments=2)
            _udl(model, ids, (0., -(850. + 130. * v) * (1. + .2 * i), 0.))
        _force(model, joint((xs[-1], y, 0.)), (3800. * floor * v, -2200. * floor, 0.))
    spec['description'] = 'Asymmetric two-bay/two-storey frame; unequal spans/heights, mixed lateral and gravity loads'


def _setback(model, spec, v):
    w, h = 3.2 + .5 * v, 2.4 + .2 * v
    joint, member = _geometry(model, v, planar=True)
    for x in (0., w, 2.3 * w):
        _fix(model, joint((x, 0., 0.)))
    level_x = [(0., w, 2.3 * w), (0., w, 2.3 * w), (w, 2.3 * w)]
    for floor, xs in enumerate(level_x, 1):
        y0, y1 = (floor - 1) * h, floor * h
        for x in xs:
            member((x, y0, 0.), (x, y1, 0.), segments=2)
        for a, b in zip(xs[:-1], xs[1:]):
            ids = member((a, y1, 0.), (b, y1, 0.), segments=2)
            _udl(model, ids, (0., -600. - 90. * v, 0.))
        _force(model, joint((xs[-1], y1, 0.)), (3200. * floor, -1400. * v, 0.))
    spec['description'] = 'Three-storey frame with a missing upper-left bay and nonuniform floor spans'


def _braced(model, spec, v):
    w, h = 4.1 + .35 * v, 2.8 + .12 * v
    joint, member = _geometry(model, v, planar=True)
    for x in (0., w):
        _fix(model, joint((x, 0., 0.)))
        member((x, 0., 0.), (x, h, 0.), segments=2)
        member((x, h, 0.), (x, 2 * h, 0.), segments=2)
    for y in (h, 2 * h):
        _udl(model, member((0., y, 0.), (w, y, 0.), segments=2), (0., -700. - 80. * v, 0.))
    center = (w / 2, h, 0.)
    for corner in ((0., 0., 0.), (w, 0., 0.), (0., 2 * h, 0.), (w, 2 * h, 0.)):
        # Brace rotations are released at corner ends while the frame joints
        # retain stiffness from columns/beams; no unconnected rotational gauge.
        member(corner, center, release_i=True)
    _force(model, joint((w, 2 * h, 0.)), (6500. + 1200. * v, -3500., 0.))
    spec['description'] = 'Two-storey frame with four corner-to-centre diamond braces and elastic end releases'


def _mixed(model, spec, v):
    w, h = 3.3 + .4 * v, 3.1 + .16 * v
    joint, member = _geometry(model, v, planar=True)
    for i, x in enumerate((0., w, 2.15 * w)):
        base = joint((x, 0., 0.))
        restraint = [True] * 6
        if i > 0:
            restraint[5] = False
        _fix(model, base, restraint)
        member((x, 0., 0.), (x, h, 0.), segments=2)
    for i, (a, b) in enumerate(((0., w), (w, 2.15 * w))):
        ids = member((a, h, 0.), (b, h, 0.), segments=2, release_i=i == 1)
        _udl(model, ids, (0., -1000. - 110. * v, 0.))
    _force(model, joint((2.15 * w, h, 0.)), (7400. + 1200. * v, -1800., 0.))
    spec['description'] = 'Two-bay frame with one fixed and two pinned bases plus a released beam end'


def _branch(model, spec, v):
    joint, member = _geometry(model, v)
    root = joint((.3 * v, -.2 * v, .15 * v))
    _fix(model, root)
    a = (.3 * v, -.2 * v, .15 * v)
    hub = (1.5 + .35 * v, .6 + .12 * v, 3. + .18 * v)
    member(a, hub, segments=3)
    tips = [(4. + .3 * v, 1.6, 4.1), (-1. + .15 * v, 2.7 + .2 * v, 4.7),
            (2.1, -2.3 - .1 * v, 5.2)]
    for i, tip in enumerate(tips):
        ids = member(hub, tip, segments=2)
        _force(model, joint(tip), (1800. * (i + 1), -1000. * v, -2500. - 400. * i),
               (120. * (i + 1), 75. * v, -90.))
        _udl(model, ids, (0., 0., -110. - 30. * v))
    _root_reactions(model, spec, root)
    spec['description'] = 'Single-root three-dimensional tree frame with three loaded branches and joint couples'


def _skew_roof(model, spec, v):
    joint, member = _geometry(model, v)
    w, d, h = 3.4 + .35 * v, 2.7 + .25 * v, 3. + .14 * v
    bases = [(0., 0., 0.), (w, .3, 0.), (w + .7, d, 0.), (.5, d + .4, 0.)]
    roof = [(.15, -.1, h), (w + .2, .5, h + .35), (w + .4, d + .2, h + .6), (.2, d + .1, h + .15)]
    for a, b in zip(bases, roof):
        _fix(model, joint(a))
        member(a, b, segments=2)
    for i in range(4):
        _udl(model, member(roof[i], roof[(i+1) % 4], segments=2), (0., 0., -330. - 40. * v))
    member(roof[0], roof[2])
    for i, point in enumerate(roof):
        _force(model, joint(point), (2200. + 450. * i, -1300. * v, -2100. - 200. * i))
    spec['description'] = 'Skew four-column sloping roof frame with roof diagonal, nonvertical columns and biaxial loading'


def _tower(model, spec, v):
    joint, member = _geometry(model, v)
    w, d, h = 2.8 + .3 * v, 2.2 + .2 * v, 2.6 + .17 * v
    level = []
    for floor in range(3):
        inset = .12 * floor * v
        corners = [(inset, inset, floor * h), (w - inset, inset, floor * h),
                   (w - inset, d - inset, floor * h), (inset, d - inset, floor * h)]
        level.append(corners)
        for point in corners:
            joint(point)
            if floor == 0:
                _fix(model, joint(point))
        if floor:
            for i in range(4):
                member(level[floor-1][i], corners[i])
                _udl(model, member(corners[i], corners[(i+1)%4]), (0., 0., -260. - 30. * v))
            for i in (0, 2):
                member(level[floor-1][i], corners[(i+1)%4])
    for i, point in enumerate(level[-1]):
        _force(model, joint(point), (2100. * v, 1700. + 250. * i, -1800.))
    spec['description'] = 'Two-level tapered closed box frame with side bracing and torsional/biaxial roof loading'


def _zigzag(model, spec, v):
    joint, member = _geometry(model, v)
    points = [(0., 0., 0.), (2.3 + .2*v, .4, .8), (1.5, 2.4 + .2*v, 2.1),
              (4.1 + .15*v, 3., 3.4), (3., .7, 5.1 + .15*v)]
    root = joint(points[0])
    _fix(model, root)
    for a, b in zip(points[:-1], points[1:]):
        _udl(model, member(a, b, segments=2), (0., 0., -200. - 45. * v))
    _force(model, joint(points[-1]), (4200. + 600. * v, -2300., -3100.), (500., -280., 350.))
    _force(model, joint(points[2]), (-900., 1300. * v, -1700.))
    _root_reactions(model, spec, root)
    spec['description'] = 'Four-turn 3D cantilever with interior joint load, gravity UDL and a tip force/couple'


def _reverse_l(model, spec, v):
    joint, member = _geometry(model, v)
    points = [(0., 0., 0.), (2.1 + .25*v, .5, 1.2), (3.7, 3. + .2*v, 2.8)]
    root = joint(points[0])
    _fix(model, root)
    for a, b in zip(points[:-1], points[1:]):
        _udl(model, member(a, b, segments=3), (120., -90., -280. - 30.*v))
    _force(model, joint(points[-1]), (2300.*v, 1400., -3300.), (210., 180., -250.))
    for i, element in enumerate(model['elements']):
        if (i + v) % 2:
            element['n1_id'], element['n2_id'] = element['n2_id'], element['n1_id']
            element['beta'] *= -1
    _root_reactions(model, spec, root)
    spec['description'] = 'Rolled 3D L-cantilever with alternating member connectivity reversal; global loading'


def _polygon(model, spec, v):
    joint, member = _geometry(model, v)
    radius, angle, segments = 3. + .35*v, math.radians(65. + 9.*v), 8 + v
    points = [(radius*math.sin(angle*i/segments), radius*(1-math.cos(angle*i/segments)),
               (.7 + .08*v)*i/segments) for i in range(segments+1)]
    root = joint(points[0])
    _fix(model, root)
    for a, b in zip(points[:-1], points[1:]):
        _udl(model, member(a, b), (0., 0., -140. - 25.*v))
    _force(model, joint(points[-1]), (2500. + 700.*v, -2100., -2800.), (120., 180., 310.))
    _root_reactions(model, spec, root)
    spec['description'] = 'Three-dimensional polygonal curved cantilever under uniform gravity and tip force/couple'
    spec.update(radius=radius,sweep_degrees=65.+9.*v,segments=segments)


BUILDERS = (_multibay, _setback, _braced, _mixed, _branch, _skew_roof, _tower, _zigzag, _reverse_l, _polygon)


def build_cases():
    cases = []
    for family, builder in zip(FAMILIES, BUILDERS):
        planar = family in FAMILIES[:4]
        for variant in range(1, 6):
            case_id = f'{201 + len(cases):03d}_{family}_v{variant}'
            model = _base(case_id, variant, ACTIVE_PLANAR if planar else [True]*6, shear=True)
            spec = {'family':family, 'variant':variant, 'analytical_static':[], 'analytical_modal':[],
                    'reference_method':'independent force-flexibility assembled reference',
                    'reference_sources':['Gere and Timoshenko: linear elastic frames and equilibrium',
                                         'Selected planar CALFEM beam2e/beam2te audit; independent 3D force-flexibility reference'],
                    'shear_deformation':True, 'mass_model':'lumped translational frame self-mass'}
            builder(model, spec, variant)
            _sparse_shuffle(model, spec, variant)
            if len(model['nodes']) > 30:
                raise AssertionError(f'Node cap exceeded: {case_id}: {len(model["nodes"])}')
            cases.append(dict(id=case_id, family=family, variant=variant, model=model, spec=spec))
    assert len(cases) == 50
    return cases
