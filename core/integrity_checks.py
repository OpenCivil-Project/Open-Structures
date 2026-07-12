"""
Pre-delete usage checks for Define-menu properties (Materials, Frame
Sections, Area Sections, Link/Support Properties).

Every "Delete Property" button in the various manager dialogs used to
remove the property from its dict with no check for whether anything
in the model still referenced it by name. That silently corrupts frame/
area elements on save+reload (they get dropped, since load resolves
`sec_name` -> `model.sections.get(...)` and skips the element if it's
None), and for links it's worse: `link["prop_name"]` is looked up live
with no fallback anywhere, so an orphaned link property is a bare
KeyError waiting to happen the next time the solver assembles it.

These functions are read-only: they never mutate the model. Each
returns (in_use: bool, message: str). Callers should check `in_use`
first and, if True, show `message` to the user and abort the delete
instead of removing the property.
"""

def _plural(count, noun):
    return f"{count} {noun}{'s' if count != 1 else ''}"

def check_material_in_use(model, material_name):
    """Can a Material named `material_name` be safely deleted?"""
    used_by = []

    sec_count = sum(
        1 for sec in model.sections.values()
        if getattr(sec, "material", None) is not None
        and sec.material.name == material_name
    )
    if sec_count:
        used_by.append(_plural(sec_count, "frame section"))

    area_sec_count = 0
    if hasattr(model, "area_sections"):
        area_sec_count = sum(
            1 for sec in model.area_sections.values()
            if getattr(sec, "material", None) is not None
            and sec.material.name == material_name
        )
    if area_sec_count:
        used_by.append(_plural(area_sec_count, "area section"))

    slab_count = 0
    if hasattr(model, "slabs"):
        slab_count = sum(
            1 for slab in model.slabs.values()
            if getattr(slab, "material", None) is not None
            and slab.material.name == material_name
        )
    if slab_count:
        used_by.append(_plural(slab_count, "slab"))

    if not used_by:
        return False, ""

    msg = (
        f"Material '{material_name}' can't be deleted because it's still "
        f"assigned to {', '.join(used_by)}.\n\n"
        "Reassign or delete those first, then try again."
    )
    return True, msg

def check_section_in_use(model, section_name):
    """Can a Frame Section named `section_name` be safely deleted?"""
    count = sum(
        1 for el in model.elements.values()
        if getattr(el, "section", None) is not None
        and el.section.name == section_name
    )
    if count == 0:
        return False, ""

    msg = (
        f"Frame Property '{section_name}' can't be deleted because it's "
        f"still assigned to {_plural(count, 'frame member')}.\n\n"
        "Reassign or delete those members first, then try again."
    )
    return True, msg

def check_area_section_in_use(model, section_name):
    """Can an Area Section named `section_name` be safely deleted?"""
    count = 0
    if hasattr(model, "area_elements"):
        count = sum(
            1 for ae in model.area_elements.values()
            if getattr(ae, "section", None) is not None
            and ae.section.name == section_name
        )
    if count == 0:
        return False, ""

    msg = (
        f"Area Section '{section_name}' can't be deleted because it's "
        f"still assigned to {_plural(count, 'area element')}.\n\n"
        "Reassign or delete those elements first, then try again."
    )
    return True, msg

def check_link_property_in_use(model, prop_name):
    """Can a Link/Support Property named `prop_name` be safely deleted?"""
    count = 0
    if hasattr(model, "links"):
        count = sum(
            1 for link in model.links.values()
            if link.get("prop_name") == prop_name
        )
    if count == 0:
        return False, ""

    msg = (
        f"Link Property '{prop_name}' can't be deleted because it's "
        f"still assigned to {_plural(count, 'link element')}.\n\n"
        "Delete or reassign those links first, then try again."
    )
    return True, msg
