"""Fifty additional mass-source, inertia and elastic-support benchmarks.

Native .mf data only: no production element or solver routines are imported.
The one-dimensional spectra and foundation response are exact discrete formulas;
continuum beam frequencies retain explicit finite-mesh tolerances.
"""
from __future__ import annotations

import math
import numpy as np
from scipy import linalg, optimize

from validation.linear_modal.models import (
    G_ACCEL, _base, _beam_line, _check, _element, _force,
    _frequency, _node, _point, _properties, _udl,
)

FAMILIES = (
    'mass_self_modifier_beam', 'mass_nodal_pattern_chain',
    'mass_member_udl_chain', 'mass_member_point_chain',
    'mass_self_plus_nodal_beam', 'mass_added_tip_link_beam',
    'mass_fixedfixed_rotary_chain', 'support_tip_axial_spring_chain',
    'support_coupled_tip_spring', 'support_uniform_foundation_chain',
)


def _spring(model, nid, matrix):
    next(n for n in model['nodes'] if n['id']==nid)['spring_matrix'] = np.asarray(matrix).tolist()


def _mass_link(model, nid, mass=0., rotary=(0.,0.,0.)):
    name='Inertia_%d' % (len(model['link_properties'])+1)
    model['link_properties'].append(dict(name=name,mass=float(mass),weight=0.,
        r1=float(rotary[0]),r2=float(rotary[1]),r3=float(rotary[2]),
        stiffness=np.zeros((6,6)).tolist(),damping=np.zeros((6,6)).tolist(),is_fixed=[False]*6))
    model['links'].append(dict(id=len(model['links'])+1,prop_name=name,nodes=[nid],beta=0.))


def _pattern_source(model, scale, self_mass=False):
    model['load_patterns'].append(dict(name='INERTIA',type='Other',sw_mult=0.))
    model['mass_sources']=[dict(name='Default',include_self_mass=self_mass,include_patterns=True,
                               load_patterns=[['INERTIA',scale]])]


def _gravity_mass(model, nid, mass, scale):
    model['loads'].append(dict(type='nodal',pattern='INERTIA',node_id=nid,
                              fx=0.,fy=0.,fz=-mass*G_ACCEL/scale,mx=0.,my=0.,mz=0.))


def _beam(model, variant):
    length=[3.2,4.4,5.8,7.1,8.9][variant-1]
    segments=[8,10,12,14,16][variant-1]
    nodes,elements=_beam_line(model,length,segments,plane='xz')
    model['nodes'][0]['restraints']=[True]*6
    return length,segments,nodes,elements


def _axial(model, variant):
    length=[2.8,3.6,4.7,6.1,7.8][variant-1]
    segments=[6,8,10,12,14][variant-1]
    model['info']['active_dofs']=[True,False,False,False,False,False]
    nodes,elements=_beam_line(model,length,segments,plane='3d')
    for node in model['nodes']:
        node['restraints']=[False,True,True,True,True,True]
    model['nodes'][0]['restraints']=[True]*6
    return length,segments,nodes,elements


def _axial_static(model,spec,nodes,length,load):
    material,section=_properties(model)
    _force(model,nodes[-1],(load,0.,0.))
    _check(spec,nodes[-1],0,load*length/(material['E']*section['A']),
           'Axial tip displacement','PL/(EA)')
    _check(spec,nodes[0],0,-load,'Axial fixed-end reaction','-P',result='reactions')


def _chain_spectra(spec,k,m,n,half_tip=False,foundation=0.):
    denominator=4*n if half_tip else 4*n+2
    for mode in range(1,4):
        eigen=foundation/m+4*k/m*math.sin((2*mode-1)*math.pi/denominator)**2
        _frequency(spec,mode,math.sqrt(eigen)/(2*math.pi),
                   'sqrt(ks/m + 4k/m*sin²((2r-1)π/(4n%s)))/(2π)' % ('' if half_tip else '+2'),
                   tolerance=1e-6,label='Exact discrete axial chain frequency')


def _beam_static(model,spec,nodes,length,load,moment=0.):
    material,section=_properties(model)
    ei=material['E']*section['I22']
    _force(model,nodes[-1],(0.,0.,-load),(0.,moment,0.))
    _check(spec,nodes[-1],2,-load*length**3/(3*ei)-moment*length**2/(2*ei),
           'Cantilever force/moment displacement','-PL³/(3EI22)-MyL²/(2EI22)')
    _check(spec,nodes[-1],4,load*length**2/(2*ei)+moment*length/ei,
           'Cantilever force/moment rotation','PL²/(2EI22)+MyL/(EI22)')


def _beam_frequency(spec,model,length,mass_factor=1.):
    material,section=_properties(model)
    density=material['rho']/G_ACCEL
    value=1.875104068711961**2/(2*math.pi*length**2)*math.sqrt(
        material['E']*section['I22']/(density*section['A']*mass_factor))
    _frequency(spec,1,value,'β1²/(2πL²)*sqrt(EI22/(ρm*A*mass_factor))',
               tolerance=.02,label='Continuum cantilever frequency with uniform mass scaling')


def _mass_cases(family,variant,model,spec):
    load=6500.+900.*variant
    scale=[.5,.75,1.,1.25,1.5][variant-1]
    if family=='mass_fixedfixed_rotary_chain':
        length,n,nodes,elements=_axial(model,variant)
        model['info']['active_dofs']=[False,False,False,True,False,False]
        for node in model['nodes']:
            node['restraints']=[True,True,True,False,True,True]
        model['nodes'][0]['restraints']=model['nodes'][-1]['restraints']=[True]*6
        material,section=_properties(model)
        material['rho']=0.
        inertia=.35+.15*variant
        for nid in nodes[1:-1]:
            _mass_link(model,nid,rotary=(inertia,0.,0.))
        torque=650.+110.*variant
        _force(model,nodes[n//2],moment=(torque,0.,0.))
        _check(spec,nodes[n//2],3,torque*length/(4*material['G']*section['J']),
               'Fixed-fixed bar center twist','TL/(4GJ)')
        for nid in (nodes[0],nodes[-1]):
            _check(spec,nid,3,-torque/2,'Fixed-fixed bar support torque','-T/2',result='reactions')
        k=material['G']*section['J']/(length/n)
        for mode in range(1,4):
            f=math.sqrt(4*k/inertia)*math.sin(mode*math.pi/(2*n))/(2*math.pi)
            _frequency(spec,mode,f,'sqrt(4k/Jm)*sin(rπ/(2n))/(2π)',1e-6,
                       'Exact fixed-fixed discrete torsional frequency')
        spec.update(length=length,segments=n,rotary_inertia=inertia,
                    mass_model='Explicit rotary inertias; zero self weight; fixed-fixed torsional chain')
        return
    if family in ('mass_nodal_pattern_chain','mass_member_udl_chain','mass_member_point_chain'):
        length,n,nodes,elements=_axial(model,variant)
        material,section=_properties(model)
        _pattern_source(model,scale,self_mass=False)
        _axial_static(model,spec,nodes,length,load)
        k=material['E']*section['A']/(length/n)
        m=28.+12.*variant
        if family=='mass_nodal_pattern_chain':
            for nid in nodes[1:]:
                _gravity_mass(model,nid,m,scale)
            _chain_spectra(spec,k,m,n)
        elif family=='mass_member_udl_chain':
            q=m*G_ACCEL/(scale*(length/n))
            _udl(model,elements,(0.,0.,-q))
            for record in model['loads']:
                if record['type']=='member_dist':
                    record['pattern']='INERTIA'
            _chain_spectra(spec,k,m,n,half_tip=True)
        else:
            for eid in elements:
                _point(model,eid,.5,-m*G_ACCEL/scale,direction='Z')
                model['loads'][-1]['pattern']='INERTIA'
            # Mid-member points supply half mass to the free tip; this added
            # nodal gravity action makes every free-node mass exactly m.
            _gravity_mass(model,nodes[-1],m/2,scale)
            _chain_spectra(spec,k,m,n)
        spec.update(length=length,segments=n,free_nodal_mass=m,pattern_mass_multiplier=scale,
                    mass_model='Downward INERTIA pattern / g; self mass excluded')
        return
    length,n,nodes,elements=_beam(model,variant)
    material,section=_properties(model)
    density=material['rho']/G_ACCEL
    if family=='mass_self_modifier_beam':
        factor=[.35,.65,1.3,1.8,2.4][variant-1]
        model['sections'][0]['modifiers']['Mass']=factor
        _beam_static(model,spec,nodes,length,load)
        _beam_frequency(spec,model,length,factor)
        spec.update(mass_factor=factor,mass_model='Gross self mass multiplied by section Mass modifier')
    elif family=='mass_self_plus_nodal_beam':
        factor=[.15,.35,.8,1.2,1.7][variant-1]
        _pattern_source(model,scale,self_mass=True)
        segment_mass=density*section['A']*length/n
        for i,nid in enumerate(nodes):
            _gravity_mass(model,nid,factor*segment_mass*(.5 if i in (0,n) else 1.),scale)
        _beam_static(model,spec,nodes,length,load,moment=load*length/5)
        _beam_frequency(spec,model,length,1+factor)
        spec.update(added_mass_ratio=factor,pattern_mass_multiplier=scale,
                    mass_model='Self mass plus matching uniform nodal INERTIA pattern')
    else:
        ratio=[.3,.7,1.5,2.4,4.][variant-1]
        added=ratio*density*section['A']*length
        _mass_link(model,nodes[-1],mass=added)
        _beam_static(model,spec,nodes,length,load)
        characteristic=lambda b:1+math.cos(b)*math.cosh(b)+ratio*b*(math.cos(b)*math.sinh(b)-math.sin(b)*math.cosh(b))
        root=optimize.brentq(characteristic,.001,1.876)
        frequency=root**2/(2*math.pi*length**2)*math.sqrt(material['E']*section['I22']/(density*section['A']))
        _frequency(spec,1,frequency,
                   'β²/(2πL²)*sqrt(EI/(ρm A)); 1+cosβ coshβ+μβ(cosβ sinhβ−sinβ coshβ)=0',
                   .02,'Continuum cantilever with concentrated tip mass')
        spec.update(tip_mass=added,tip_mass_ratio=ratio,characteristic_root=root,
                    mass_model='Translational lumped beam self mass plus mass-only tip link',
                    additional_reference='Euler-Bernoulli cantilever tip-mass boundary characteristic equation')
    spec.update(length=length,segments=n)


def _support_cases(family,variant,model,spec):
    load=7000.+1200.*variant
    if family=='support_coupled_tip_spring':
        length=[2.,2.8,3.6,4.4,5.2][variant-1]
        nodes=[_node(model,(0.,0.,0.),[True]*6),_node(model,(length,0.,0.))]
        _element(model,*nodes)
        model['info']['active_dofs']=[True]*6
        material,section=_properties(model)
        e,g=material['E'],material['G']
        flexibility=np.zeros((6,6))
        flexibility[0,0]=length/(e*section['A'])
        flexibility[3,3]=length/(g*section['J'])
        for indices,inertia,sign in (([1,5],section['I33'],1.),([2,4],section['I22'],-1.)):
            flexibility[np.ix_(indices,indices)]=np.array([[length**3/3,sign*length**2/2],
                                                         [sign*length**2/2,length]])/(e*inertia)
        tip_stiffness=linalg.inv(flexibility)
        spring_scale=np.sqrt(np.diag(tip_stiffness))
        coupling=np.eye(6)*(.12+.08*variant)
        coupling[0,1]=coupling[1,0]=.045
        coupling[2,4]=coupling[4,2]=-.035
        coupling[3,5]=coupling[5,3]=.025
        spring=spring_scale[:,None]*coupling*spring_scale[None,:]
        _spring(model,nodes[-1],spring)
        force=np.array([load,-.7*load,.4*load,.025*load,-.04*load,.03*load])
        _force(model,nodes[-1],force[:3],force[3:])
        u=linalg.solve(tip_stiffness+spring,force,assume_a='pos')
        reaction=-spring@u
        for dof in range(6):
            _check(spec,nodes[-1],dof,u[dof],'Coupled-spring tip response',
                   'u=(F_tip^−1+Kspring)^−1 P; F_tip from Castigliano')
            _check(spec,nodes[-1],dof,reaction[dof],'Coupled spring nodal reaction',
                   '-Kspring*u',result='reactions')
        _mass_link(model,nodes[-1],mass=40.+10*variant,
                   rotary=(.8+.2*variant,1.2+.2*variant,1.6+.2*variant))
        spec.update(length=length,mass_model='Beam self mass plus explicit tip translation/rotary inertia',
                    support_stiffness=spring.tolist(),coupled_global_spring=True)
        return
    length,n,nodes,elements=_axial(model,variant)
    material,section=_properties(model)
    k=material['E']*section['A']/(length/n)
    if family=='support_tip_axial_spring_chain':
        rod_stiffness=material['E']*section['A']/length
        spring_stiffness=rod_stiffness*[.25,.6,1.1,1.8,3.][variant-1]
        spring=np.zeros((6,6));spring[0,0]=spring_stiffness
        _spring(model,nodes[-1],spring)
        _force(model,nodes[-1],(load,0.,0.))
        displacement=load/(rod_stiffness+spring_stiffness)
        _check(spec,nodes[-1],0,displacement,'Rod with tip elastic support','P/(EA/L+ks)')
        _check(spec,nodes[-1],0,-spring_stiffness*displacement,'Tip spring reaction','-ks*u',result='reactions')
        _check(spec,nodes[0],0,-rod_stiffness*displacement,'Rod base reaction','-(EA/L)*u',result='reactions')
        spec.update(support_stiffness=spring_stiffness,mass_model='Self mass with elastic axial tip support')
    else:
        material['rho']=0.
        spring_stiffness=k*[.025,.05,.075,.1,.15][variant-1]
        mass=25.+15*variant
        for nid in nodes[1:]:
            spring=np.zeros((6,6));spring[0,0]=spring_stiffness
            _spring(model,nid,spring)
            _mass_link(model,nid,mass=mass)
        _force(model,nodes[-1],(load,0.,0.))
        alpha=math.acosh(1+spring_stiffness/(2*k))
        amplitude=load/((k+spring_stiffness)*math.sinh(n*alpha)-k*math.sinh((n-1)*alpha))
        for i,nid in enumerate(nodes[1:],1):
            displacement=amplitude*math.sinh(i*alpha)
            _check(spec,nid,0,displacement,'Uniform foundation chain displacement',
                   'u_i=C sinh(iα); coshα=1+ks/(2k); C=P/[(k+ks)sinh(nα)−k sinh((n−1)α)]')
            _check(spec,nid,0,-spring_stiffness*displacement,'Foundation spring reaction','-ks*u_i',result='reactions')
        _check(spec,nodes[0],0,-k*amplitude*math.sinh(alpha),'Foundation chain root reaction','-k*u_1',result='reactions')
        _chain_spectra(spec,k,mass,n,foundation=spring_stiffness)
        spec.update(support_stiffness=spring_stiffness,free_nodal_mass=mass,
                    mass_model='Equal explicit link masses; zero member self mass; equal nodal axial support springs')
    spec.update(length=length,segments=n)


def _sparse_shuffle(model,spec,variant):
    if variant not in (2,4,5):
        return
    ids={node['id']:11+7*i for i,node in enumerate(model['nodes'])}
    for node in model['nodes']:
        node['id']=ids[node['id']]
    for element in model['elements']:
        element['n1_id']=ids[element['n1_id']]
        element['n2_id']=ids[element['n2_id']]
    for load in model['loads']:
        if 'node_id' in load:
            load['node_id']=ids[load['node_id']]
    for link in model['links']:
        link['nodes']=[ids[nid] for nid in link['nodes']]
    for check in spec['analytical_static']:
        check['node_id']=ids[check['node_id']]
    model['nodes']=model['nodes'][2:]+model['nodes'][:2] if len(model['nodes'])>2 else model['nodes'][::-1]
    spec['node_order']='Sparse noncontiguous IDs with shuffled input records'


def build_cases():
    cases=[]
    for family_index,family in enumerate(FAMILIES):
        for variant in range(1,6):
            serial=151+5*family_index+variant-1
            cid=f'{serial:03d}_{family}_v{variant}'
            model=_base(cid,variant,active=[True,False,True,False,True,False])
            spec=dict(family=family,variant=variant,analytical_static=[],analytical_modal=[],
                      node_order='Ascending IDs',shear_deformation=False,
                      reference_sources=['Gere and Timoshenko: beam/bar force flexibility',
                                         'Clough and Penzien: exact discrete chain eigenvalues',
                                         'Euler-Bernoulli cantilever tip-mass characteristic equation'])
            if family.startswith('mass_'):
                _mass_cases(family,variant,model,spec)
            else:
                _support_cases(family,variant,model,spec)
            _sparse_shuffle(model,spec,variant)
            cases.append(dict(id=cid,family=family,variant=variant,model=model,spec=spec))
    assert len(cases)==50
    return cases
