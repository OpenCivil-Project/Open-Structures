"""Generate 100 native OpenCivil projects with independently checkable solutions.

All stored values are SI base quantities. ``rho`` is weight density (N/m³),
matching the project format; it is not mass density. This module deliberately
does not import OpenCivil's element or solver implementations.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

G_ACCEL = 9.80665
FAMILIES = (
    "cantilever_tip_y", "cantilever_tip_z", "inclined_cantilever",
    "cantilever_udl", "cantilever_tip_moment", "axial_bar", "torsion_bar",
    "simply_supported_point", "simply_supported_udl", "fixed_fixed_point",
    "fixed_fixed_udl", "propped_udl", "continuous_two_span", "rigid_portal",
    "pinned_base_portal", "released_beam_portal", "two_story_frame",
    "space_frame", "stepped_axial_chain", "elastic_support_beam",
)


def _norm(a):
    return math.sqrt(sum(x * x for x in a))


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _axis(direction, beta=0):
    x = [v / _norm(direction) for v in direction]
    up = [1., 0., 0.] if abs(x[2]) > .999 else [0., 0., 1.]
    y = _cross(up, x)
    y = [v / _norm(y) for v in y]
    z = _cross(x, y)
    c, s = math.cos(math.radians(beta)), math.sin(math.radians(beta))
    return x, [c*a+s*b for a, b in zip(y, z)], [-s*a+c*b for a, b in zip(y, z)]


def _base(name, variant, active=None, shear=False):
    E = [200e9, 70e9, 30e9, 210e9, 190e9][variant-1]
    density = [7850., 2700., 2400., 7850., 7800.][variant-1]
    nu = [0.30, 0.33, 0.20, 0.28, 0.29][variant-1]
    b, h = .18 + .02*variant, .27 + .015*variant
    area = b*h
    sec = dict(A=area, J=area*min(b,h)**2/8, I22=h*b**3/12,
               I33=b*h**3/12, As2=5*area/6 if shear else 0.,
               As3=5*area/6 if shear else 0., theta_p=0.)
    return {
        "info": {"name": name, "units": "N, m, C", "active_dofs": active or [True]*6,
                 "analysis_engine": "native", "last_run_case": "STATIC", "show_analysis_log": True},
        "grid": {"x_lines": [], "y_lines": [], "z_lines": []},
        "nodes": [], "elements": [],
        "materials": [{"name": "Elastic", "type": "Steel" if variant != 3 else "Concrete",
                       "E": E, "nu": nu, "G": E/(2*(1+nu)), "rho": density*G_ACCEL}],
        "sections": [{"name": "Beam", "type": "general", "mat_name": "Elastic",
                     "properties": sec, "modifiers": {"A":1., "I2":1., "I3":1.,
                     "As2":1., "As3":1., "J":1., "Mass":1., "Weight":1.},
                     "color": [0.25, .7, 1., 1.]}],
        "load_patterns": [{"name": "TEST", "type": "Other", "sw_mult": 0.}],
        "load_cases": [{"name": "STATIC", "type": "Linear Static", "loads": [["TEST", 1.]]},
                       {"name": "MODAL", "type": "Modal", "loads": [],
                        "mass_source": "Default", "num_modes": 3}],
        "load_combinations": [], "loads": [], "constraints": [],
        "mass_sources": [{"name": "Default", "include_self_mass": True,
                          "include_patterns": False, "load_patterns": []}],
        "link_properties": [], "links": [], "area_elements": [], "area_sections": [],
        "slabs": [], "tendons": [], "cables": [],
    }


def _node(model, xyz, restraints=None):
    nid = len(model["nodes"]) + 1
    model["nodes"].append(dict(id=nid, x=float(xyz[0]), y=float(xyz[1]), z=float(xyz[2]),
                               restraints=list(restraints or [False]*6), diaphragm=None))
    return nid


def _element(model, ni, nj, sec="Beam", beta=0, release_i=None, release_j=None):
    eid = len(model["elements"]) + 1
    model["elements"].append(dict(id=eid, n1_id=ni, n2_id=nj, sec_name=sec, beta=beta,
        rel_i=list(release_i or [False]*6), rel_j=list(release_j or [False]*6),
        off_i=[0., 0., 0.], off_j=[0., 0., 0.], end_off_i=0., end_off_j=0., rz_factor=0.))
    return eid


def _force(model, nid, force=(0.,0.,0.), moment=(0.,0.,0.)):
    data = dict(type="nodal", pattern="TEST", node_id=nid)
    data.update(zip(("fx","fy","fz","mx","my","mz"), [*force, *moment]))
    model["loads"].append(data)


def _udl(model, element_ids, vector, coord="Global"):
    for eid in element_ids:
        model["loads"].append(dict(type="member_dist", pattern="TEST", element_id=eid,
                                  wx=vector[0], wy=vector[1], wz=vector[2], coord=coord,
                                  projected=False))


def _point(model, eid, rel, value, direction="Y", coord="Global"):
    model["loads"].append(dict(type="member_point", pattern="TEST", element_id=eid,
                               force=value, dist=rel, is_rel=True, dir=direction,
                               coord=coord, l_type="Force"))


def _check(spec, nid, dof, value, label, formula, result="displacements"):
    spec["analytical_static"].append(dict(node_id=nid, dof=dof, value=float(value),
                                        label=label, formula=formula, result=result))


def _frequency(spec, mode, f, formula, tolerance=.02, label="Continuum first frequency"):
    spec["analytical_modal"].append(dict(mode=mode, frequency_hz=f, tolerance=tolerance,
                                       formula=formula, label=label))


def _beam_line(model, length, n, direction=(1.,0.,0.), beta=0., plane="xy"):
    ax = [v/_norm(direction) for v in direction]
    restraints = [False,False,True,True,True,False] if plane == "xy" else \
                 [False,True,False,True,False,True] if plane == "xz" else [False]*6
    nodes = [_node(model, [length*i/n*v for v in ax], restraints) for i in range(n+1)]
    elements = [_element(model, nodes[i], nodes[i+1], beta=beta) for i in range(n)]
    return nodes, elements


def _properties(model):
    return model["materials"][0], model["sections"][0]["properties"]


def _beam_case(family, variant, model, spec):
    L = [3., 4., 5.5, 7., 8.5][variant-1]
    n = [6,8,10,12,14][variant-1]
    P, q = 7000.+1300.*variant, 1800.+250.*variant
    mat, sec = _properties(model)
    E, G, A, I = mat["E"], mat["G"], sec["A"], sec["I33"]
    density = mat["rho"] / G_ACCEL
    spec.update(length=L, segments=n, load=P, uniform_load=q, mass_model="lumped translational self-mass")
    if family == "inclined_cantilever":
        direction = [(1.,.6,.4),(1.,-1.,.7),(.4,.8,1.),(0.,0.,1.),(1.,.4,.9)][variant-1]
        beta = [0.,25.,-40.,65.,15.][variant-1]
        axes = _axis(direction,beta)
        nodes, els = _beam_line(model,L,n,direction,beta,plane="3d")
        model["nodes"][0]["restraints"] = [True]*6
        _force(model,nodes[-1],[P*v for v in axes[1]])
        delta = P*L**3/(3*E*I) + P*L/(G*sec["As2"])
        theta = P*L**2/(2*E*I)
        for j,v in enumerate(axes[1]):
            _check(spec,nodes[-1],j,v*delta,"Inclined tip displacement", "e2*(PL³/(3EI33)+PL/(GAs2))")
        for j,v in enumerate(axes[2]):
            _check(spec,nodes[-1],3+j,v*theta,"Inclined tip rotation", "e3*PL²/(2EI33)")
        spec.update(direction=direction,beta=beta,shear_deformation=True)
        if variant == 5:
            model["nodes"] = model["nodes"][2:] + model["nodes"][:2]
            spec["node_order"] = "shuffled; identical physical node IDs and coordinates"
        return
    plane = "xz" if family == "cantilever_tip_z" else "xy"
    nodes, els = _beam_line(model,L,n,plane=plane)
    ydof, rdof = (2,4) if plane == "xz" else (1,5)
    forcevector = [0.,0.,0.]
    forcevector[ydof] = -P
    if plane == "xz":
        I = sec["I22"]
    if family.startswith("cantilever"):
        model["nodes"][0]["restraints"] = [True]*6
        if family in ("cantilever_tip_y","cantilever_tip_z"):
            _force(model,nodes[-1],forcevector)
            _check(spec,nodes[-1],ydof,-P*L**3/(3*E*I),"Tip bending displacement","-PL³/(3EI)")
            rotation_sign = 1. if plane == "xz" else -1.
            _check(spec,nodes[-1],rdof,rotation_sign*P*L**2/(2*E*I),"Tip bending rotation","±PL²/(2EI)")
        elif family == "cantilever_udl":
            _udl(model,els,(0.,-q,0.))
            _check(spec,nodes[-1],1,-q*L**4/(8*E*I),"Cantilever UDL tip displacement","-qL⁴/(8EI)")
            _check(spec,nodes[-1],5,-q*L**3/(6*E*I),"Cantilever UDL tip rotation","-qL³/(6EI)")
            _check(spec,nodes[0],1,q*L,"Root shear","qL",result="reactions")
        else:
            M = P*L/3
            _force(model,nodes[-1],moment=(0.,0.,M))
            _check(spec,nodes[-1],1,M*L**2/(2*E*I),"Tip moment displacement","ML²/(2EI)")
            _check(spec,nodes[-1],5,M*L/(E*I),"Tip moment rotation","ML/(EI)")
        _frequency(spec,1,1.875104068711961**2/(2*math.pi*L**2)*math.sqrt(E*I/(density*A)),
                   "β1²/(2πL²)*sqrt(EI/(ρm A)), β1=1.8751040687")
        return
    # Horizontal supports: left fixes axial movement; right is an axial roller.
    model["nodes"][0]["restraints"][0:2] = [True,True]
    model["nodes"][-1]["restraints"][1] = True
    center = nodes[n//2]
    if family.startswith("fixed_fixed"):
        model["nodes"][0]["restraints"] = [True]*6
        model["nodes"][-1]["restraints"] = [True]*6
    if family == "propped_udl":
        model["nodes"][0]["restraints"] = [True]*6
    if family == "elastic_support_beam":
        k = (6.+variant)*E*I/L**3
        model["nodes"][-1]["restraints"][1] = False
        spring = [[0.]*6 for _ in range(6)]
        spring[1][1] = k
        model["nodes"][-1]["spring_matrix"] = spring
        _force(model,center,(0.,-P,0.))
        _check(spec,nodes[-1],1,-P/(2*k),"Elastic roller settlement","-P/(2k)")
        _check(spec,nodes[0],1,P/2,"Left reaction","P/2",result="reactions")
        _check(spec,nodes[-1],1,P/2,"Spring reaction","P/2",result="reactions")
        spec["support_stiffness"] = k
        return
    if family == "continuous_two_span":
        # Existing line length is the total of two equal spans.
        model["nodes"][n//2]["restraints"][1] = True
        _udl(model,els,(0.,-q,0.))
        span = L/2
        for nid,r in [(nodes[0],3*q*span/8),(center,5*q*span/4),(nodes[-1],3*q*span/8)]:
            _check(spec,nid,1,r,"Two-span UDL support reaction","[3/8,5/4,3/8]*q*span",result="reactions")
        return
    if family.endswith("point"):
        if family == "simply_supported_point":
            # An interior member point load exercises the equivalent nodal load path.
            a = [.31,.43,.57,.67,.39][variant-1]*L
            pos = a*n/L
            idx = min(n-1,int(pos))
            _point(model,els[idx],pos-idx,-P)
            b = L-a
            _check(spec,nodes[0],1,P*b/L,"Pin reaction","P*(L-a)/L",result="reactions")
            _check(spec,nodes[-1],1,P*a/L,"Roller reaction","P*a/L",result="reactions")
            _check(spec,nodes[0],5,-P*b*(L*L-b*b)/(6*L*E*I),"Left support slope","-Pb(L²-b²)/(6LEI)")
            _check(spec,nodes[-1],5,P*a*(L*L-a*a)/(6*L*E*I),"Right support slope","Pa(L²-a²)/(6LEI)")
            spec["point_location"] = a
        else:
            _force(model,center,(0.,-P,0.))
            _check(spec,center,1,-P*L**3/(192*E*I),"Fixed beam center displacement","-PL³/(192EI)")
            _check(spec,nodes[0],1,P/2,"Fixed beam shear","P/2",result="reactions")
            _check(spec,nodes[0],5,P*L/8,"Fixed beam root moment","PL/8",result="reactions")
    else:
        _udl(model,els,(0.,-q,0.))
        if family == "simply_supported_udl":
            _check(spec,center,1,-5*q*L**4/(384*E*I),"Simply supported center displacement","-5qL⁴/(384EI)")
            _check(spec,nodes[0],5,-q*L**3/(24*E*I),"Support slope","-qL³/(24EI)")
            _check(spec,nodes[0],1,q*L/2,"Support reaction","qL/2",result="reactions")
        elif family == "fixed_fixed_udl":
            _check(spec,center,1,-q*L**4/(384*E*I),"Fixed beam center displacement","-qL⁴/(384EI)")
            _check(spec,nodes[0],5,q*L**2/12,"Fixed beam root moment","qL²/12",result="reactions")
        elif family == "propped_udl":
            _check(spec,nodes[0],1,5*q*L/8,"Propped root shear","5qL/8",result="reactions")
            _check(spec,nodes[-1],1,3*q*L/8,"Prop shear","3qL/8",result="reactions")
            _check(spec,nodes[0],5,q*L**2/8,"Propped root moment","qL²/8",result="reactions")
    if family.startswith("simply_supported"):
        _frequency(spec,1,math.pi/(2*L*L)*math.sqrt(E*I/(density*A)),"π/(2L²)*sqrt(EI/(ρm A))")
    if family.startswith("fixed_fixed"):
        _frequency(spec,1,4.730040744862704**2/(2*math.pi*L*L)*math.sqrt(E*I/(density*A)),
                   "β1²/(2πL²)*sqrt(EI/(ρm A)), β1=4.7300407449", tolerance=.03)


def _chain_case(family,variant,model,spec):
    L = [2.5,3.5,5.,6.,8.][variant-1]
    n = [6,8,10,12,14][variant-1]
    P = 9000.+1000*variant
    nodes,els = _beam_line(model,L,n,plane="3d")
    model["nodes"][0]["restraints"] = [True]*6
    dof = 3 if family == "torsion_bar" else 0
    model["info"]["active_dofs"] = [i == dof for i in range(6)]
    for node in model["nodes"][1:]:
        node["restraints"] = [i != dof for i in range(6)]
    mat, sec = _properties(model)
    spec.update(length=L,segments=n,load=P)
    if family == "torsion_bar":
        _force(model,nodes[-1],moment=(P,0.,0.))
        jmass = .5 + .25*variant
        model["link_properties"] = [dict(name="RotaryInertia", mass=0.,weight=0.,r1=jmass,r2=0.,r3=0.,
            stiffness=[[0.]*6 for _ in range(6)],damping=[[0.]*6 for _ in range(6)],is_fixed=[False]*6)]
        model["links"] = [dict(id=i,prop_name="RotaryInertia",nodes=[nid],beta=0.) for i,nid in enumerate(nodes[1:],1)]
        _check(spec,nodes[-1],3,P*L/(mat["G"]*sec["J"]),"Uniform bar twist","TL/(GJ)")
        _check(spec,nodes[0],3,-P,"Root torque","-T",result="reactions")
        k = mat["G"]*sec["J"]/(L/n)
        for mode in range(1,4):
            f=math.sqrt(4*k/jmass)*math.sin((2*mode-1)*math.pi/(4*n+2))/(2*math.pi)
            _frequency(spec,mode,f,"sqrt(4k/Jm)*sin((2r-1)π/(4n+2))/(2π)",1e-6,"Exact discrete torsional chain frequency")
        spec.update(mass_model="explicit identical rotary inertias at each free node",rotary_inertia=jmass)
        return
    _force(model,nodes[-1],(P,0.,0.))
    if family == "axial_bar":
        _check(spec,nodes[-1],0,P*L/(mat["E"]*sec["A"]),"Axial tip displacement","PL/(EA)")
        k = mat["E"]*sec["A"]/(L/n)
        m = mat["rho"]/G_ACCEL*sec["A"]*(L/n)
        for mode in range(1,4):
            f=math.sqrt(4*k/m)*math.sin((2*mode-1)*math.pi/(4*n))/(2*math.pi)
            _frequency(spec,mode,f,"sqrt(4k/m)*sin((2r-1)π/(4n))/(2π)",1e-6,"Exact lumped axial bar frequency")
    else:
        compliance=0.
        for i,e in enumerate(model["elements"]):
            factor = [1.,.6,1.4,.8,1.2][(i+variant)%5]
            name="Axial_%d" % i
            p=dict(sec)
            p["A"]*=factor
            model["sections"].append(dict(name=name,type="general",mat_name="Elastic",properties=p))
            e["sec_name"]=name
            compliance+=(L/n)/(mat["E"]*p["A"])
        _check(spec,nodes[-1],0,P*compliance,"Stepped bar tip displacement","P Σ(Li/(Ei Ai))")
        spec["mass_model"]="self-mass from each stepped gross area"
    _check(spec,nodes[0],0,-P,"Axial root reaction","-P",result="reactions")


def _frame_case(family,variant,model,spec):
    width=[3.,4.,5.,6.5,8.][variant-1]
    height=[2.5,3.,3.5,4.,4.5][variant-1]
    P=8000.+variant*2000.
    nseg=[2,3,4,5,6][variant-1]
    space=family=="space_frame"
    mat,sec=_properties(model)
    planar=[False,False,True,True,True,False]
    coords={}  # Preserve connectivity by IDs even when input records are reordered.
    def joint(x,y,z=0.):
        key=(round(x,10),round(y,10),round(z,10))
        if key not in coords:
            coords[key]=_node(model,(x,y,z),[False]*6 if space else planar)
        return coords[key]
    def member(a,b,release_i=None,release_j=None):
        start=joint(*a)
        ids=[]
        for step in range(1,nseg+1):
            xyz=[a[k]+(b[k]-a[k])*step/nseg for k in range(3)]
            end=joint(*xyz)
            ids.append(_element(model,start,end,
                release_i=release_i if step==1 else None,
                release_j=release_j if step==nseg else None))
            start=end
        return ids
    if space:
        depth=width*(.6+.04*variant)
        bases=[]
        tops=[]
        for x,z in [(0.,0.),(width,0.),(width,depth),(0.,depth)]:
            bases.append(joint(x,0.,z))
            tops.append(joint(x,height,z))
            member((x,0.,z),(x,height,z))
        for a,b in [((0.,height,0.),(width,height,0.)),((width,height,0.),(width,height,depth)),
                    ((width,height,depth),(0.,height,depth)),((0.,height,depth),(0.,height,0.))]:
            member(a,b)
        for nid in bases:
            model["nodes"][nid-1]["restraints"]=[True]*6
        for i,nid in enumerate(tops):
            _force(model,nid,(P*(.5+i*.15),-P*.3,P*.2))
        spec.update(depth=depth,description="3D four-column roof frame; biaxial lateral and gravity loading")
    else:
        floors=2 if family=="two_story_frame" else 1
        base_left,base_right=joint(0.,0.),joint(width,0.)
        for base in (base_left,base_right):
            model["nodes"][base-1]["restraints"]=[True]*6
            if family=="pinned_base_portal":
                model["nodes"][base-1]["restraints"][5]=False
        release=[False,False,False,False,False,True]
        for floor in range(1,floors+1):
            y0,y1=(floor-1)*height,floor*height
            member((0.,y0,0.),(0.,y1,0.))
            member((width,y0,0.),(width,y1,0.))
            beams=member((0.,y1,0.),(width,y1,0.),
                         release if family=="released_beam_portal" else None,
                         release if family=="released_beam_portal" else None)
            left,right=joint(0.,y1),joint(width,y1)
            _force(model,left,(P*floor/2,0.,0.))
            _force(model,right,(P*floor/2,0.,0.))
            if family in ("rigid_portal","two_story_frame"):
                _udl(model,beams,(0.,-900.-150.*variant,0.))
        if family=="released_beam_portal":
            # Each column remains a cantilever when roof beam bending is released.
            # Identical lateral motion leaves roof beam axial strain zero.
            delta=(P/2)*height**3/(3*mat["E"]*sec["I33"])
            for nid in (left,right):
                _check(spec,nid,0,delta,"Released portal sway","(P/2)H³/(3EI33)")
        if family=="two_story_frame" and variant==5:
            model["nodes"]=model["nodes"][::-1]
            spec["node_order"]="reversed input records; physical IDs/connectivity unchanged"
        spec["description"]="%d-story planar frame with lateral load%s" % (floors," and beam UDL" if family in ("rigid_portal","two_story_frame") else "")
    spec.update(width=width,height=height,segments_per_member=nseg,load=P,
                reference_method="independent force-flexibility assembled frame solution")


def generate_cases(output_root):
    """Write the 100 projects and return their paths, raw models and reference specs.

    Re-running deterministically replaces only files belonging to this generated
    suite. The root owns summary/reference artifacts; this function owns .mf files.
    """
    output_root=Path(output_root).resolve()
    cases=[]
    beam_families=set(FAMILIES[:5]) | set(FAMILIES[7:13]) | {"elastic_support_beam"}
    chain_families={"axial_bar","torsion_bar","stepped_axial_chain"}
    for family in FAMILIES:
        for variant in range(1,6):
            case_id="%03d_%s_v%d" % (len(cases)+1,family,variant)
            active=[True,True,False,False,False,True]
            if family=="cantilever_tip_z":
                active=[True,False,True,False,True,False]
            if family in ("inclined_cantilever","space_frame","torsion_bar"):
                active=[True]*6
            model=_base(case_id,variant,active,shear=family=="inclined_cantilever")
            spec={"family":family,"variant":variant,"analytical_static":[],"analytical_modal":[],
                  "node_order":"ascending IDs","shear_deformation":family=="inclined_cantilever",
                  "reference_sources":["Gere and Timoshenko, Mechanics of Materials: beam and bar formulas",
                                       "Clough and Penzien, Dynamics of Structures: beam vibration and discrete chains"]}
            if family in beam_families:
                _beam_case(family,variant,model,spec)
            elif family in chain_families:
                _chain_case(family,variant,model,spec)
            else:
                _frame_case(family,variant,model,spec)
            directory=output_root/"cases"/case_id
            directory.mkdir(parents=True,exist_ok=True)
            path=directory/(case_id+".mf")
            path.write_text(json.dumps(model,indent=2,allow_nan=False)+"\n",encoding="utf-8")
            cases.append(dict(id=case_id,family=family,variant=variant,directory=str(directory),
                              mf_path=str(path),model=model,spec=spec))
    if len(cases)!=100:
        raise AssertionError("The suite must contain exactly 100 shared projects")
    return cases
