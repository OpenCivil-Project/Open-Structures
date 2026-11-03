"""Fifty additional beam benchmarks with independent continuum static formulas.

Member-load cases exercise virtual-work interpolation, including off-mesh
forces/moments and piecewise-linear loading. All stored quantities are SI.
"""
from __future__ import annotations

import math

from validation.linear_modal.models import (
    _axis, _base, _beam_line, _check, _force, _frequency, _point, _properties, _udl,
)


FAMILIES = (
    'beam_mixed_tip_3d', 'beam_interior_point_force',
    'beam_interior_point_moment', 'beam_triangular_load',
    'beam_patch_trapezoid_load', 'beam_projected_gravity_load',
    'beam_self_weight', 'beam_section_stiffness_modifiers',
    'beam_two_pattern_superposition', 'beam_rigid_root_segment',
)


def _global(local, axes):
    return [sum(local[i]*axes[i][j] for i in range(3)) for j in range(3)]


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _tip_force_solution(model, spec, nodes, axes, length, force, moment):
    """Exact linear Timoshenko cantilever compliance for six tip actions."""
    mat, gross = _properties(model)
    mods = model['sections'][0]['modifiers']
    E, G = mat['E'], mat['G']
    A = gross['A']*mods.get('A',1.)
    I2, I3 = gross['I22']*mods.get('I2',1.), gross['I33']*mods.get('I3',1.)
    As2, As3 = gross['As2']*mods.get('As2',1.), gross['As3']*mods.get('As3',1.)
    J = gross['J']*mods.get('J',1.)
    x, y, z = force
    tx, my, mz = moment
    shear2 = length/(G*As2) if As2 else 0.
    shear3 = length/(G*As3) if As3 else 0.
    displacement = [x*length/(E*A),
                    y*(length**3/(3*E*I3)+shear2)+mz*length**2/(2*E*I3),
                    z*(length**3/(3*E*I2)+shear3)-my*length**2/(2*E*I2)]
    rotation = [tx*length/(G*J),
                -z*length**2/(2*E*I2)+my*length/(E*I2),
                y*length**2/(2*E*I3)+mz*length/(E*I3)]
    for dof,value in enumerate(_global(displacement,axes)+_global(rotation,axes)):
        _check(spec,nodes[-1],dof,value,'Mixed tip-action compliance',
               'Transform[FxL/EA, Fy(L³/3EI33+L/GAs2)+MzL²/2EI33, Fz(L³/3EI22+L/GAs3)-MyL²/2EI22; TxL/GJ, -FzL²/2EI22+MyL/EI22, FyL²/2EI33+MzL/EI33]')


def _root_actions(model,spec,nodes,force,moment):
    end = next(node for node in model['nodes'] if node['id']==nodes[-1])
    position = [end[key] for key in ('x','y','z')]
    cross = _cross(position,force)
    for dof,value in enumerate([-v for v in force]+[-moment[j]-cross[j] for j in range(3)]):
        _check(spec,nodes[0],dof,value,'Root equilibrium','[-F, -M-r×F]',result='reactions')


def _uniform_solution(model,spec,nodes,axes,L,qglobal):
    mat, sec = _properties(model)
    E,G=mat['E'],mat['G']
    q=[sum(axis[j]*qglobal[j] for j in range(3)) for axis in axes]
    displacement=[q[0]*L**2/(2*E*sec['A']),
        q[1]*(L**4/(8*E*sec['I33'])+(L**2/(2*G*sec['As2']) if sec['As2'] else 0.)),
        q[2]*(L**4/(8*E*sec['I22'])+(L**2/(2*G*sec['As3']) if sec['As3'] else 0.))]
    rotation=[0.,-q[2]*L**3/(6*E*sec['I22']),q[1]*L**3/(6*E*sec['I33'])]
    for dof,value in enumerate(_global(displacement,axes)+_global(rotation,axes)):
        _check(spec,nodes[-1],dof,value,'Distributed-action tip compliance',
               'Transform[qxL²/2EA, qy(L⁴/8EI33+L²/2GAs2), qz(L⁴/8EI22+L²/2GAs3);0,-qzL³/6EI22,qyL³/6EI33]')
    r=[L*v/2 for v in axes[0]]
    force=[L*v for v in qglobal]
    moment=_cross(r,force)
    for dof,value in enumerate([-v for v in force]+[-v for v in moment]):
        _check(spec,nodes[0],dof,value,'Distributed root equilibrium','[-qL, -(r/2)×qL]',result='reactions')


def _linear_value(stations,values,x):
    if x<stations[0] or x>stations[-1]:
        return 0.
    for a,b,qa,qb in zip(stations[:-1],stations[1:],values[:-1],values[1:]):
        if a<=x<=b:
            return qa+(qb-qa)*(x-a)/(b-a)
    return 0.


def _load_piecewise(model,els,L,stations,values,coord):
    h=L/len(els)
    for i,eid in enumerate(els):
        a,b=i*h,(i+1)*h
        points=sorted({a,b,*[x for x in stations if a<x<b]})
        # Four stations are the native project's usual load-profile shape.
        while len(points)<4:
            pairs=list(zip(points[:-1],points[1:]))
            lower,upper=max(pairs,key=lambda pair:pair[1]-pair[0])
            points.append((lower+upper)/2)
            points.sort()
        magnitudes=[_linear_value(stations,values,x) for x in points]
        if max(abs(q) for q in magnitudes)<1e-12:
            continue
        model['loads'].append(dict(type='member_dist',pattern='TEST',element_id=eid,
            wx=0.,wy=0.,wz=0.,coord=coord,projected=False,is_relative=True,
            distances=[(x-a)/h for x in points],magnitudes=magnitudes,load_direction='Y'))


def _moment_integral(stations,values,power):
    """Closed-form integral of q(s)*s**power for piecewise linear q."""
    total=0.
    for a,b,qa,qb in zip(stations[:-1],stations[1:],values[:-1],values[1:]):
        slope=(qb-qa)/(b-a)
        intercept=qa-slope*a
        total+=intercept*(b**(power+1)-a**(power+1))/(power+1)
        total+=slope*(b**(power+2)-a**(power+2))/(power+2)
    return total


def _profile_solution(model,spec,nodes,L,stations,values):
    mat,sec=_properties(model)
    EI=mat['E']*sec['I33']
    GA=mat['G']*sec['As2']
    integrals=[_moment_integral(stations,values,power) for power in range(4)]
    displacement=(3*L*integrals[2]-integrals[3])/(6*EI)+(integrals[1]/GA if GA else 0.)
    rotation=integrals[2]/(2*EI)
    _check(spec,nodes[-1],1,displacement,'Piecewise-linear load tip displacement',
           '∫q(s)[s²(3L-s)/(6EI)+s/(GAs)]ds, integrated analytically per linear segment')
    _check(spec,nodes[-1],5,rotation,'Piecewise-linear load tip rotation','∫q(s)s²/(2EI)ds')
    _check(spec,nodes[0],1,-integrals[0],'Profile root shear','-∫q(s)ds',result='reactions')
    _check(spec,nodes[0],5,-integrals[1],'Profile root moment','-∫q(s)s ds',result='reactions')


def _shuffle_sparse(model,spec,variant):
    node_map={node['id']:107+19*variant+7*i for i,node in enumerate(model['nodes'])}
    element_map={element['id']:211+13*variant+11*i for i,element in enumerate(model['elements'])}
    for node in model['nodes']:
        node['id']=node_map[node['id']]
    for element in model['elements']:
        element['id']=element_map[element['id']]
        element['n1_id']=node_map[element['n1_id']]
        element['n2_id']=node_map[element['n2_id']]
    for load in model['loads']:
        if 'node_id' in load:
            load['node_id']=node_map[load['node_id']]
        if 'element_id' in load:
            load['element_id']=element_map[load['element_id']]
    for record in spec['analytical_static']:
        record['node_id']=node_map[record['node_id']]
    shift=variant%len(model['nodes'])
    model['nodes']=model['nodes'][shift:]+model['nodes'][:shift]
    if variant%2==0:
        model['nodes'].reverse()
    spec['node_order']='shuffled sparse IDs, independent of DOF indices'


def build_cases():
    cases=[]
    for family_index,family in enumerate(FAMILIES):
        for variant in range(1,6):
            cid=f'{101+family_index*5+variant-1:03d}_{family}_v{variant}'
            three_d=family in ('beam_mixed_tip_3d','beam_projected_gravity_load',
                              'beam_self_weight','beam_section_stiffness_modifiers')
            active=[True]*6 if three_d else [True,True,False,False,False,True]
            shear=family!='beam_interior_point_moment'
            model=_base(cid,variant,active,shear=shear)
            spec=dict(family=family,variant=variant,analytical_static=[],analytical_modal=[],
                      shear_deformation=shear,reference_sources=[
                          'Gere and Timoshenko: beam compliance and virtual work',
                          'Clough and Penzien: independent generalized eigenproblem'])
            L=[2.1,3.8,5.2,6.9,9.3][variant-1]
            n=[6,7,8,10,12][variant-1]
            P=11000.+1700.*variant
            q=1450.+350.*variant
            direction=[(1.,.35,.7),(.7,-.55,1.),(0.,0.,1.),(1.,-.8,.4),(.4,.8,-1.)][variant-1] if three_d else (1.,0.,0.)
            beta=[17.,-28.,43.,70.,-51.][variant-1] if three_d else 0.
            axes=_axis(direction,beta)
            nodes,els=_beam_line(model,L,n,direction,beta,plane='3d' if three_d else 'xy')
            model['nodes'][0]['restraints']=[True]*6
            mat,sec=_properties(model)
            E,G=mat['E'],mat['G']
            EI=E*sec['I33']
            GA=G*sec['As2']
            spec.update(length=L,segments=n,direction=direction,beta=beta,load=P)

            if family in ('beam_mixed_tip_3d','beam_section_stiffness_modifiers'):
                if family=='beam_section_stiffness_modifiers':
                    model['sections'][0]['modifiers'].update(A=.55+.08*variant,
                        I2=.35+.1*variant,I3=1.3-.12*variant,
                        As2=.4+.09*variant,As3=1.2-.1*variant,J=.45+.12*variant)
                    spec['section_modifiers']=dict(model['sections'][0]['modifiers'])
                force=[.6*P,-P,.45*P]
                moment=[P*L/17,P*L/23,-P*L/19]
                fglobal,mglobal=_global(force,axes),_global(moment,axes)
                _force(model,nodes[-1],fglobal,mglobal)
                _tip_force_solution(model,spec,nodes,axes,L,force,moment)
                _root_actions(model,spec,nodes,fglobal,mglobal)
            elif family in ('beam_interior_point_force','beam_interior_point_moment'):
                a=[.27,.41,.56,.68,.83][variant-1]*L
                position=a*n/L
                segment=min(n-1,int(position))
                if family=='beam_interior_point_force':
                    value=-P
                    _point(model,els[segment],position-segment,value,'Y','Global' if variant%2 else 'Local')
                    tip=value*a*a*(3*L-a)/(6*EI)+(value*a/GA if GA else 0.)
                    slope=value*a*a/(2*EI)
                    reaction,moment=-value,-value*a
                    formula='Pa²(3L-a)/(6EI)+Pa/(GAs)'
                else:
                    value=P*L/(7+variant)
                    _point(model,els[segment],position-segment,value,'Z','Global' if variant%2 else 'Local')
                    model['loads'][-1]['l_type']='Moment'
                    tip=value*a*(2*L-a)/(2*EI)
                    slope=value*a/EI
                    reaction,moment=0.,-value
                    formula='Ma(2L-a)/(2EI)'
                    density=mat['rho']/9.80665
                    f=1.875104068711961**2/(2*math.pi*L**2)*math.sqrt(EI/(density*sec['A']))
                    _frequency(spec,1,f,'β1²/(2πL²)*sqrt(EI/(ρmA)); β1=1.875104068711961',.02)
                _check(spec,nodes[-1],1,tip,'Interior action tip displacement',formula)
                _check(spec,nodes[-1],5,slope,'Interior action tip slope','Pa²/(2EI) or Ma/(EI)')
                _check(spec,nodes[0],1,reaction,'Interior action root shear','-P or zero for applied couple',result='reactions')
                _check(spec,nodes[0],5,moment,'Interior action root moment','-Pa or -M',result='reactions')
                spec.update(point_position=a,point_fraction=a/L)
            elif family in ('beam_triangular_load','beam_patch_trapezoid_load'):
                stations,values=([0.,L],[0.,-q]) if family=='beam_triangular_load' else (
                    [.12*L,.36*L,.63*L,.87*L],[0.,-q,-.6*q,0.])
                _load_piecewise(model,els,L,stations,values,'Global' if variant%2 else 'Local')
                _profile_solution(model,spec,nodes,L,stations,values)
                spec.update(profile_stations=stations,profile_values=values)
            elif family=='beam_projected_gravity_load':
                _udl(model,els,(0.,0.,-q))
                for load in model['loads']:
                    load['projected']=True
                projection=math.hypot(axes[0][0],axes[0][1])
                # A vertical beam would have zero projected load; retain a
                # meaningful oblique direction in this particular variant.
                if projection<1e-8:
                    direction=(.6,.3,1.)
                    axes=_axis(direction,beta)
                    for i,node in enumerate(model['nodes']):
                        node.update(zip(('x','y','z'),[L*i/n*v for v in axes[0]]))
                    projection=math.hypot(axes[0][0],axes[0][1])
                    spec['direction']=direction
                _uniform_solution(model,spec,nodes,axes,L,[0.,0.,-q*projection])
                spec['horizontal_projection_factor']=projection
            elif family=='beam_self_weight':
                mult=[1.,.5,1.3,.8,1.8][variant-1]
                weight_mod=[.8,1.,1.25,.65,1.45][variant-1]
                model['load_patterns'][0]['sw_mult']=mult
                model['sections'][0]['modifiers']['Weight']=weight_mod
                effective_q=-mat['rho']*sec['A']*mult*weight_mod
                _uniform_solution(model,spec,nodes,axes,L,[0.,0.,effective_q])
                spec.update(self_weight_multiplier=mult,weight_modifier=weight_mod)
            elif family=='beam_two_pattern_superposition':
                model['load_patterns'] += [dict(name='WIND',type='Other',sw_mult=0.),
                                          dict(name='INACTIVE',type='Other',sw_mult=0.)]
                alpha,beta_case=.7+.12*variant,-.6+.07*variant
                model['load_cases'][0]['loads']=[['TEST',alpha],['WIND',beta_case]]
                _udl(model,els,(0.,-q,0.))
                _force(model,nodes[-1],(0.,P,0.),(0.,0.,P*L/5))
                model['loads'][-1]['pattern']='WIND'
                _force(model,nodes[-1],(0.,1e7,0.))
                model['loads'][-1]['pattern']='INACTIVE'
                load_q,load_p,load_m=-q*alpha,P*beta_case,P*L/5*beta_case
                tip=load_q*(L**4/(8*EI)+L**2/(2*GA))+load_p*(L**3/(3*EI)+L/GA)+load_m*L**2/(2*EI)
                slope=load_q*L**3/(6*EI)+load_p*L**2/(2*EI)+load_m*L/EI
                _check(spec,nodes[-1],1,tip,'Scaled-pattern superposition tip','q(L⁴/8EI+L²/2GAs)+P(L³/3EI+L/GAs)+ML²/2EI')
                _check(spec,nodes[-1],5,slope,'Scaled-pattern superposition rotation','qL³/6EI+PL²/2EI+ML/EI')
                _check(spec,nodes[0],1,-load_q*L-load_p,'Scaled-pattern support shear','-qL-P',result='reactions')
                _check(spec,nodes[0],5,-load_q*L**2/2-load_p*L-load_m,'Scaled-pattern support moment','-qL²/2-PL-M',result='reactions')
                spec['pattern_factors']={'TEST':alpha,'WIND':beta_case,'INACTIVE':0.}
            else:
                rigid=(.3+.05*variant)*L/n
                model['elements'][0].update(end_off_i=rigid,rz_factor=1.)
                flexible=L-rigid
                moment=P*L/9
                _force(model,nodes[-1],(0.,-P,0.),(0.,0.,moment))
                tip=-P*(flexible**3/(3*EI)+flexible/GA)+moment*flexible**2/(2*EI)
                slope=-P*flexible**2/(2*EI)+moment*flexible/EI
                _check(spec,nodes[-1],1,tip,'Rigid-root clear-length compliance','P(Lclear³/3EI+Lclear/GAs)+MLclear²/2EI')
                _check(spec,nodes[-1],5,slope,'Rigid-root clear-length rotation','PLclear²/2EI+MLclear/EI')
                _check(spec,nodes[0],1,P,'Rigid-root shear','-P',result='reactions')
                _check(spec,nodes[0],5,P*L-moment,'Rigid-root moment includes arm','-PLtotal-M',result='reactions')
                spec.update(root_rigid_length=rigid,flexible_length=flexible)

            _shuffle_sparse(model,spec,variant)
            cases.append(dict(id=cid,family=family,variant=variant,model=model,spec=spec))
    assert len(cases)==50
    return cases
