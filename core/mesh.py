import math
import numpy as np
from core.properties import Section

class Node:
    def __init__(self, id: int, x: float, y: float, z: float):
        self.id = int(id)
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
                                                 
        self.restraints = [False] * 6 
        self.diaphragm_name = None

    def get_coords(self):
        return np.array([self.x, self.y, self.z])

    def __repr__(self):
        return f"Node({self.id})"

class FrameElement:
    def __init__(self, id: int, node_i: Node, node_j: Node, section: Section, beta_angle: float = 0.0):
        self.id = int(id)
        self.node_i = node_i
        self.node_j = node_j
        self.section = section
        self.beta_angle = float(beta_angle)             
        
        self.end_offset_i = 0.0                        
        self.end_offset_j = 0.0                        
        self.rigid_zone_factor = 0.0                                    

        self.cardinal_point = 10
        self.joint_offset_i = np.array([0.0, 0.0, 0.0]) 
        self.joint_offset_j = np.array([0.0, 0.0, 0.0])
        self.releases_i = [False] * 6 
        self.releases_j = [False] * 6

    def length(self):
        dx = self.node_j.x - self.node_i.x
        dy = self.node_j.y - self.node_i.y
        dz = self.node_j.z - self.node_i.z
        return math.sqrt(dx**2 + dy**2 + dz**2)

    def get_local_axes(self):
        """
        Calculates the 3x3 Rotation Matrix (Direction Cosines) for the element.
        Needed for:
        1. 3D Extrusion (Visualizing the shape)
        2. Stiffness Matrix Transformation (Solver)
        """
                                          
        xi, yi, zi = self.node_i.x, self.node_i.y, self.node_i.z
        xj, yj, zj = self.node_j.x, self.node_j.y, self.node_j.z
        
        V_x = np.array([xj - xi, yj - yi, zj - zi])
        L = np.linalg.norm(V_x)
        if L == 0: return np.eye(3)
        v_x = V_x / L                

        if np.abs(v_x[2]) > 0.99:
                                                           
            temp_vec = np.array([0.0, 1.0, 0.0]) 
        else:
            temp_vec = np.array([0.0, 0.0, 1.0])

        v_y = np.cross(temp_vec, v_x)
        v_y = v_y / np.linalg.norm(v_y)

        v_z = np.cross(v_x, v_y)
        v_z = v_z / np.linalg.norm(v_z)

        rad = math.radians(self.beta_angle)
        c = math.cos(rad)
        s = math.sin(rad)

        v_y_final = v_y * c + v_z * s
        v_z_final = -v_y * s + v_z * c
        
        return v_x, v_y_final, v_z_final

    def __repr__(self):
        return f"Frame3D({self.id})"
    
    def get_transformation_matrix(self):
        """
        Builds the 12x12 Transformation Matrix (T).
        This allows us to add this element's stiffness to the global system,
        regardless of how the element is oriented or rotated.
        """
                                                                                   
        v1, v2, v3 = self.get_local_axes()
        
        R = np.array([v1, v2, v3]) 

        T = np.zeros((12, 12))
        
        T[0:3, 0:3] = R
        
        T[3:6, 3:6] = R
        
        T[6:9, 6:9] = R
        
        T[9:12, 9:12] = R
        
        return T
    
    def get_cardinal_offsets(self):
        """
        Returns (ey, ez): the offset in local 2-3 coords from the Node (at the
        cardinal point) to the Section Centroid, for cardinal point IDs 1-11.

        Uses section.get_bbox_offsets() which works for all section types
        including arbitrary polygons from the Section Designer.

        Sign convention (matches the renderer and get_insertion_matrix):
          positive ey → centroid is in the +local2 direction from the node
          positive ez → centroid is in the +local3 direction from the node
        """
        y_l, y_r, z_b, z_t = self.section.get_bbox_offsets()

        table = {
            1:  (+y_l,  +z_b),                
            2:  ( 0.0,  +z_b),                  
            3:  (-y_r,  +z_b),                 
            4:  (+y_l,   0.0),                
            5:  ( 0.0,   0.0),                  
            6:  (-y_r,   0.0),                 
            7:  (+y_l,  -z_t),             
            8:  ( 0.0,  -z_t),               
            9:  (-y_r,  -z_t),              
            10: ( 0.0,   0.0),                         
            11: ( 0.0,   0.0),                               
        }
        return table.get(self.cardinal_point, (0.0, 0.0))

    def get_insertion_matrix(self):
        """
        Builds the 12x12 Transformation Matrix [Tcp] that links
        Node Displacements to Centroid Displacements.
        """
                                                                
        cy, cz = self.get_cardinal_offsets()
        
        v1, v2, v3 = self.get_local_axes()
        
        R = np.array([v1, v2, v3]) 
        
        local_off_i = R @ self.joint_offset_i
        local_off_j = R @ self.joint_offset_j

        ex_i = local_off_i[0] + self.end_offset_i
        ex_j = local_off_j[0] - self.end_offset_j
        
        ey_i = cy + local_off_i[1]
        ez_i = cz + local_off_i[2]
        
        ey_j = cy + local_off_j[1]
        ez_j = cz + local_off_j[2]

        def make_block(ex, ey, ez):
            B = np.eye(6)
            B[0, 4] = ez                             
            B[0, 5] = -ey                            
            B[1, 3] = -ez
            B[1, 5] = ex                                                                           
            B[2, 3] = ey
            B[2, 4] = -ex                                                                            
            return B

        T = np.zeros((12, 12))
        T[0:6, 0:6]   = make_block(ex_i, ey_i, ez_i)
        T[6:12, 6:12] = make_block(ex_j, ey_j, ez_j)
        
        return T
    
    def get_transformed_stiffness_matrix(self, k_pure):
        """
        Applies the Cardinal Point transformation to the raw stiffness matrix.
        K_final = T_cp.T * K_pure * T_cp
        """
                                                       
        if getattr(self, 'do_not_transform_stiffness', False):
            return k_pure
            
        T = self.get_insertion_matrix()
        return T.T @ k_pure @ T
    
class Slab:
    """
    Represents a visual area element (Floor/Wall).
    Used for:
    1. Visualizing the building (Grey semi-transparent planes)
    2. Calculating Center of Mass for Rigid Diaphragms
    3. Distributing area loads to frames (future)
    """
    def __init__(self, id, nodes, thickness, material=None):
        self.id = int(id)
        self.nodes = nodes                                         
        self.thickness = float(thickness)
        self.material = material
        self.color = (0.8, 0.8, 0.8, 0.4)                               
        
    def get_centroid(self):
                                   
        if not self.nodes: return (0,0,0)
        x = sum(n.x for n in self.nodes) / len(self.nodes)
        y = sum(n.y for n in self.nodes) / len(self.nodes)
        z = sum(n.z for n in self.nodes) / len(self.nodes)
        return x, y, z

    def __repr__(self):
        return f"Slab({self.id})"

class AreaElement:
    """
    Represents a finite element area (Shell, Plane, or Asolid).
    """
    def __init__(self, element_id, nodes, section):
        self.id = int(element_id)
        self.nodes = nodes                                                      
        self.section = section                                          

    def __repr__(self):
        return f"AreaElement({self.id}, sec={self.section.name})"
