class UnitConverter:
    def __init__(self):
                                                                          
        self.force_scale = 0.001                                  
        self.length_scale = 1.0                 
        self.temp_scale = 1.0                   
        
        self.current_unit_label = "kN, m, C"

    def set_unit_system(self, unit_string):
        """
        Parses string like "kN, mm, C" and sets scaling factors.
        """
        self.current_unit_label = unit_string
        parts = unit_string.replace(" ", "").split(",")
        force_unit = parts[0]
        length_unit = parts[1]
        
        if force_unit == "kN": self.force_scale = 1/1000.0
        elif force_unit == "N": self.force_scale = 1.0
        elif force_unit == "Tonf": self.force_scale = 1/9806.65
        elif force_unit == "kgf": self.force_scale = 1/9.80665
        elif force_unit == "kip": self.force_scale = 1/4448.22
        
        if length_unit == "m": self.length_scale = 1.0
        elif length_unit == "mm": self.length_scale = 1000.0
        elif length_unit == "cm": self.length_scale = 100.0
        elif length_unit == "ft": self.length_scale = 3.28084
        elif length_unit == "in": self.length_scale = 39.3701

    def to_display_force(self, base_val):
        """Convert SI force (N) → display units (e.g. kN)."""
        return base_val * self.force_scale

    def from_display_force(self, disp_val):
        """Convert display force → SI (N)."""
        return disp_val / self.force_scale

    def to_display_length(self, base_val):
        """Convert SI length (m) → display units (e.g. mm)."""
        return base_val * self.length_scale
        
    def from_display_length(self, disp_val):
        """Convert display length → SI (m)."""
        return disp_val / self.length_scale

    def to_display_pressure(self, base_val):
        """Convert SI pressure (N/m²) → display units (e.g. kN/m²)."""
        return base_val * self.force_scale / (self.length_scale ** 2)

    def from_display_pressure(self, disp_val):
        """Convert display pressure (force/length²) → SI (N/m²)."""
        return disp_val * (self.length_scale ** 2) / self.force_scale

    def to_display_acceleration(self, base_val):
        """Convert SI acceleration (m/s²) -> display units (e.g. mm/s²)."""
        return base_val * self.length_scale

    def from_display_acceleration(self, disp_val):
        """Convert display acceleration -> SI (m/s²)."""
        return disp_val / self.length_scale

    @property
    def acceleration_unit(self):
        """Returns length/s² unit label (e.g., 'm/s²', 'mm/s²')"""
        return f"{self.length_unit_name}/s\u00b2"

    @property
    def force_unit_name(self):
        """Returns just the force unit (e.g., 'kN', 'N', 'kip')"""
        parts = self.current_unit_label.replace(" ", "").split(",")
        return parts[0]
    
    @property
    def length_unit_name(self):
        """Returns just the length unit (e.g., 'm', 'mm', 'ft')"""
        parts = self.current_unit_label.replace(" ", "").split(",")
        return parts[1]
    
    @property
    def distributed_load_unit(self):
        """Returns force/length unit (e.g., 'kN/m', 'kip/ft')"""
        return f"{self.force_unit_name}/{self.length_unit_name}"

    @property
    def pressure_unit(self):
        """Returns force/length² unit label (e.g., 'kN/m²', 'kip/ft²')"""
        return f"{self.force_unit_name}/{self.length_unit_name}\u00b2"

unit_registry = UnitConverter()
