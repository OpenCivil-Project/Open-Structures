                        
from dataclasses import dataclass
from typing import Optional

@dataclass
class LoadPattern:
    """
    A container for loads (e.g., 'Dead', 'Live', 'Quake_X').
    """
    name: str
    self_weight_multiplier: float = 0.0

@dataclass
class NodalLoad:
    """
    Force/Moment applied to a specific Node.
    """
    node_id: int
    load_pattern_name: str
            
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
             
    mx: float = 0.0
    my: float = 0.0
    mz: float = 0.0

@dataclass
class MemberLoad:
    """
    Distributed load applied to a Frame Element.
    Currently supports Uniform Distributed Load (UDL).
    """
    element_id: int
    load_pattern_name: str
                                      
    wx: float = 0.0                     
    wy: float = 0.0                        
    wz: float = 0.0                        
    
    projected: bool = False                                                 

@dataclass
class MemberPointLoad:
    """
    Concentrated force or moment applied to a frame element.
    """
    element_id: int
    pattern_name: str
    force: float                            
    dist: float                         
    is_relative: bool                                               
    coord_system: str                        
    direction: str                                                                  
    load_type: str                           

    def __repr__(self):
        type_s = "Rel" if self.is_relative else "Abs"
        return f"PointLoad(El={self.element_id}, {self.force:.2f} @ {self.dist:.2f}{type_s}, {self.direction})"

@dataclass
class AreaGravityLoad:
    """
    Gravity multiplier load applied to an AreaElement (shell/plane/asolid).
    Scales the element's self-weight independently in each global direction.

    Usage:
        gz = -1.0  → full self-weight downward  (standard dead load)
        gz =  0.5  → 50 % upward (buoyancy, etc.)
        gx = 0.1   → small lateral seismic-equivalent body force

    Only valid on AreaElements — not on frames.
    """
    area_id: int
    pattern_name: str
    coord_system: str = "GLOBAL"
    gx: float = 0.0                                
    gy: float = 0.0                                
    gz: float = 0.0                                

    def __repr__(self):
        return (f"AreaGravityLoad(area={self.area_id}, pat={self.pattern_name}, "
                f"g=({self.gx:.3g}, {self.gy:.3g}, {self.gz:.3g}))")

@dataclass
class AreaUniformLoad:
    """
    Uniform pressure (force / area) applied to an AreaElement.
    Only valid on AreaElements — not on frames.

    load_direction options:
        'Gravity'             → global −Z (downward)
        'Local 1'             → shell normal (outward positive)
        'Local 2' / 'Local 3' → in-plane shear
        'Global X/Y/Z'        → explicit global axis
    """
    area_id: int
    pattern_name: str
    coord_system: str = "GLOBAL"
    load_direction: str = "Gravity"                              
    uniform_load: float = 0.0                                                              

    def __repr__(self):
        return (f"AreaUniformLoad(area={self.area_id}, pat={self.pattern_name}, "
                f"{self.uniform_load:.3g} [{self.load_direction}])")

@dataclass
class GroundDisplacement:
    """
    Specified ground displacement/rotation applied to a specific Node.
    """
    node_id: int
    pattern_name: str
            
    ux: float = 0.0
    uy: float = 0.0
    uz: float = 0.0
             
    rx: float = 0.0
    ry: float = 0.0
    rz: float = 0.0
