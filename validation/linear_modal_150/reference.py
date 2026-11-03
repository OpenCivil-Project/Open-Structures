"""Use the previously audited independent force-flexibility reference.

No production solver is imported into this reference. See
validation/linear_modal/reference_audit.md for the formulation/CALFEM audit.
"""
from validation.linear_modal.reference import analyze, SOURCES

__all__=['analyze','SOURCES']
