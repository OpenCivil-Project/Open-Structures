                       
class GridLines:
    def __init__(self):
                                         
        self.x_lines = []
        self.y_lines = []
        self.z_lines = []
        self.bubble_size = 1.25

    @property
    def x_grids(self):
        return sorted([line['ord'] for line in self.x_lines])
    
    @x_grids.setter
    def x_grids(self, values):
                                                                                      
        self.x_lines = [{'id': str(i+1), 'ord': v, 'visible': True, 'bubble': 'Start'} 
                        for i, v in enumerate(sorted(values))]

    @property
    def y_grids(self):
        return sorted([line['ord'] for line in self.y_lines])

    @y_grids.setter
    def y_grids(self, values):
        self.y_lines = [{'id': str(i+1), 'ord': v, 'visible': True, 'bubble': 'Start'} 
                        for i, v in enumerate(sorted(values))]

    @property
    def z_grids(self):
        return sorted([line['ord'] for line in self.z_lines])

    @z_grids.setter
    def z_grids(self, values):
        self.z_lines = [{'id': f"Z{i+1}", 'ord': v, 'visible': True, 'bubble': 'Start'} 
                        for i, v in enumerate(sorted(values))]

    def create_uniform(self, axis, start, num, spacing):
        """Helper to create grids quickly"""
        vals = [start + i*spacing for i in range(num + 1)]
        if axis == 'x': self.x_grids = vals
        elif axis == 'y': self.y_grids = vals
        elif axis == 'z': self.z_grids = vals
