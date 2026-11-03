"""
hinge_loader.py

Builds dm.hinge_elements from the model's raw JSON, for
nonlinear_engine.py's fiber-hinge P-Delta path to consume.

Call build_hinge_elements(dm) once, right after dm.process_all(), and
set dm.hinge_elements = build_hinge_elements(dm) -- everything
downstream (nonlinear_engine.py) already does
getattr(dm, 'hinge_elements', {}) so this is purely additive; a model
export with no 'frame_hinges' key produces an empty dict and changes
nothing.

ASSUMPTIONS FLAGGED FOR VERIFICATION AGAINST A REAL EXPORTED .mf FILE
(all easy to fix in ONE place here if wrong -- nothing downstream cares
about the raw key names, only about the dm.hinge_elements dict this
function produces):

  1. dm.raw['frame_hinges'] is a dict or list of assignment records,
     each with 'element_id', 'hinge_name', 'rel_dist' -- straight
     field-name-preserving serialization of the FrameHingeAssignment
     objects (app/commands.py deepcopy's these directly, suggesting a
     plain dataclass/attrs-style dump).
  2. dm.raw['hinge_properties'] is a dict keyed by hinge name, each
     value having 'hinge_length', 'hinge_length_relative', 'fibers'
     (list of {'area','coord2','coord3','material'} dicts -- the exact
     shape hinge_dialog.generate_property_preserving_fibers returns).
     Per conversation: fibers are ALWAYS pre-calculated via the
     "Calculate" button before a hinge property is saved/assigned, so
     'fiber_option' == "Default From Section" regeneration is NOT
     handled here -- 'fibers' is assumed always populated.
  3. dm.materials[name] is a plain dict (confirmed against
     data_manager.py's own el['material']['rho'] access pattern),
     with 'nonlinear' holding a nested dict matching
     core.properties.NonlinearMaterialData's field names 1:1.

If any of these don't match your actual export, this is the ONE file
to edit -- FiberSection/compute_hinge_element/nonlinear_engine.py's
wiring don't need to change.
"""

from fiber_section import FiberSection

FIBER_COORDS_ARE_SAP_LOCAL_AXES = True

def build_hinge_elements(dm, area_lookup=None):
    """
    Returns: dict eid_str -> {'fiber_section': FiberSection,
                               'rel_dist': float, 'length': float}

    area_lookup: bar-size-string -> area (m^2). If not supplied, built
    automatically from dm.raw['rebar_sizes'] (confirmed present in a
    real exported .mf file, as {'id','area','diameter'} records --
    this is REQUIRED for confinement math to work at all when the
    model uses US-customary bar sizes ("#4" etc): mander_model.py's
    own fallback table (BAR_AREAS_MM2) only has metric designations
    ("10M" etc), so bar_area_m2() silently returns 0.0 for "#4" without
    an explicit area_lookup -- silently zeroing out confinement
    enhancement entirely, not a crash. Confirmed against this exact
    failure mode on a real model before this default was added.
    """
    if area_lookup is None:
        rebar_sizes = dm.raw.get('rebar_sizes', [])
        area_lookup = {r['id']: r['area'] for r in rebar_sizes}
    frame_hinges = dm.raw.get('frame_hinges', {})
    hinge_properties_raw = dm.raw.get('hinge_properties', {})

    if not frame_hinges or not hinge_properties_raw:
        return {}

    if isinstance(frame_hinges, dict):
        assignments = list(frame_hinges.values())
    else:
        assignments = list(frame_hinges)

    if isinstance(hinge_properties_raw, dict):
        hinge_properties = hinge_properties_raw
    else:
        hinge_properties = {p['name']: p for p in hinge_properties_raw}

    raw_materials = dm.raw.get('materials', [])
    materials_by_name = {m['name']: m for m in raw_materials}

    elements_by_id = {str(el['id']): el for el in dm.elements}

    fiber_section_cache = {}

    def get_fiber_section(hinge_name):
        if hinge_name in fiber_section_cache:
            return fiber_section_cache[hinge_name]
        prop = hinge_properties.get(hinge_name)
        if prop is None:
            print(f"      [!] Warning: hinge property '{hinge_name}' "
                  f"referenced by an assignment but not found in "
                  f"hinge_properties -- skipping.")
            fiber_section_cache[hinge_name] = None
            return None
        fibers = prop.get('fibers')
        if not fibers:
            print(f"      [!] Warning: hinge property '{hinge_name}' has "
                  f"no pre-calculated fibers -- skipping (fiber_option "
                  f"'Default From Section' regeneration is not handled "
                  f"here; fibers must be pre-calculated before assignment).")
            fiber_section_cache[hinge_name] = None
            return None
        if FIBER_COORDS_ARE_SAP_LOCAL_AXES:
                                                                          
            fibers = [dict(f, coord2=-f['coord3'], coord3=f['coord2']) for f in fibers]
        fs = FiberSection(fibers, materials_by_name, area_lookup=area_lookup)
        fiber_section_cache[hinge_name] = fs
        return fs

    hinge_elements = {}
    for rec in assignments:
        eid_str = str(rec['element_id'])
        hinge_name = rec['hinge_name']
        rel_dist = float(rec['rel_dist'])

        el = elements_by_id.get(eid_str)
        if el is None:
            print(f"      [!] Warning: hinge assignment references "
                  f"element {eid_str}, not found in model -- skipping.")
            continue

        fs = get_fiber_section(hinge_name)
        if fs is None:
            continue

        prop = hinge_properties[hinge_name]
        hinge_length_raw = float(prop['hinge_length'])
        hinge_length_relative = bool(prop.get('hinge_length_relative', True))
        L_clear = el['L_clear']
        hinge_length = hinge_length_raw * L_clear if hinge_length_relative else hinge_length_raw

        if eid_str in hinge_elements:
            print(f"      [!] Warning: element {eid_str} has more than "
                  f"one hinge assignment -- only the first "
                  f"('{hinge_elements[eid_str]['_hinge_name']}') is used. "
                  f"Multiple hinges per element (SAP-style 'Add' mode) "
                  f"is not yet supported by the solver -- flag if needed.")
            continue

        hinge_elements[eid_str] = {
            'fiber_section': fs,
            'rel_dist': rel_dist,
            'length': hinge_length,
            '_hinge_name': hinge_name,                                   
        }

    return hinge_elements
