import numpy as np

class TSC2018SpectrumGenerator:
    """
    Turkish Seismic Code 2018 (TBDY) Spectrum Generator.
    Calculates Horizontal (Sae) and Vertical (SaeD) Design Spectra.
    """
    def __init__(self):
                                                                        
        self.fs_table = {
            'ZA': {0.25: 0.8, 0.50: 0.8, 0.75: 0.8, 1.00: 0.8, 1.25: 0.8, 1.50: 0.8},
            'ZB': {0.25: 0.9, 0.50: 0.9, 0.75: 0.9, 1.00: 0.9, 1.25: 0.9, 1.50: 0.9},
            'ZC': {0.25: 1.3, 0.50: 1.3, 0.75: 1.2, 1.00: 1.2, 1.25: 1.2, 1.50: 1.2},
            'ZD': {0.25: 1.6, 0.50: 1.4, 0.75: 1.2, 1.00: 1.1, 1.25: 1.0, 1.50: 1.0},
            'ZE': {0.25: 2.4, 0.50: 1.7, 0.75: 1.3, 1.00: 1.1, 1.25: 0.9, 1.50: 0.8}
        }
        
        self.f1_table = {
            'ZA': {0.10: 0.8, 0.20: 0.8, 0.30: 0.8, 0.40: 0.8, 0.50: 0.8, 0.60: 0.8},
            'ZB': {0.10: 0.8, 0.20: 0.8, 0.30: 0.8, 0.40: 0.8, 0.50: 0.8, 0.60: 0.8},
            'ZC': {0.10: 1.5, 0.20: 1.5, 0.30: 1.5, 0.40: 1.5, 0.50: 1.5, 0.60: 1.4},
            'ZD': {0.10: 2.4, 0.20: 2.2, 0.30: 2.0, 0.40: 1.9, 0.50: 1.8, 0.60: 1.7},
            'ZE': {0.10: 4.2, 0.20: 3.3, 0.30: 2.8, 0.40: 2.4, 0.50: 2.2, 0.60: 2.0}
        }

    def _interpolate_coeff(self, table_row, val, breakpoints):
        """Linear interpolation helper."""
        if val <= breakpoints[0]: return table_row[breakpoints[0]]
        if val >= breakpoints[-1]: return table_row[breakpoints[-1]]
        
        for i in range(len(breakpoints) - 1):
            x1, x2 = breakpoints[i], breakpoints[i+1]
            if x1 <= val <= x2:
                y1, y2 = table_row[x1], table_row[x2]
                return y1 + (val - x1) * (y2 - y1) / (x2 - x1)
        return 1.0

    def get_coeffs(self, ss, s1, site_class):
        cls = site_class.upper()
        if cls not in self.fs_table: cls = 'ZC'
        ss_bps = [0.25, 0.50, 0.75, 1.00, 1.25, 1.50]
        s1_bps = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60]
        return self._interpolate_coeff(self.fs_table[cls], ss, ss_bps),\
               self._interpolate_coeff(self.f1_table[cls], s1, s1_bps)

    def calculate_corner_periods(self, sds, sd1, tl=6.0):
        if sds == 0: return 0.0, 0.0, tl
        return 0.2 * (sd1 / sds), (sd1 / sds), tl

    def calculate_horizontal_sa(self, T, sds, sd1, ta, tb, tl):
        """Horizontal Elastic Design Spectrum"""
        if T < ta: return sds * (0.4 + 0.6 * (T / ta))
        elif T <= tb: return sds
        elif T <= tl: return sd1 / T
        else: return sd1 * tl / (T**2)

    def calculate_vertical_sa(self, T, sds, ta, tb, tl):
        """
        Vertical Elastic Design Spectrum (TBDY 2018 Eq 2.13)
        Note: Vertical uses modified corner periods (TA/3, TB/3, TL/2)
        """
        tad = ta / 3.0
        tbd = tb / 3.0
        tld = tl / 2.0
        
        if T < tad: return sds * (0.32 + 0.48 * (T / tad))
        elif T <= tbd: return 0.8 * sds
        elif T <= tld: return 0.8 * sds * tbd / T
        else: return 0.0                                                                

    def calculate_reduction_factor(self, T, R, D, I, tb):
        """Seismic Load Reduction Factor R_a(T)"""
        Ra_target = R / I
        if T > tb: return Ra_target
        else: return D + ((Ra_target - D) * (T / tb))

    def generate_spectrum_curve(self, ss, s1, site_class, R, D, I, tl=6.0, direction="Horizontal", t_max=6.0):
                                              
        fs, f1 = self.get_coeffs(ss, s1, site_class)
        sds = ss * fs
        sd1 = s1 * f1
        ta, tb, tl = self.calculate_corner_periods(sds, sd1, tl)
        
        if direction == "Horizontal":
            key_points = [0.0, ta, tb, tl]
        else:
                                            
            key_points = [0.0, ta/3.0, tb/3.0, tl/2.0]

        raw_grid_list = []
        
        t_curr = 0.2
        while t_curr <= 2.01:              
            raw_grid_list.append(t_curr)
            t_curr += 0.2
            
        t_curr = 2.5
        while t_curr <= t_max + 0.01:                   
            raw_grid_list.append(t_curr)
            t_curr += 0.5
            
        raw_grid = np.array(raw_grid_list)
        
        final_list = list(key_points)
        
        for t_grid in raw_grid:
                                                 
            min_dist = min(abs(t_grid - k) for k in key_points)
            
            if min_dist >= 0.1:
                final_list.append(t_grid)
        
        periods = np.unique(np.array(final_list))
        periods.sort()
        
        sa_values = []
        for T in periods:
            if direction == "Horizontal":
                if T == 0:
                    sae = 0.4 * sds
                    ra = D
                else:
                    sae = self.calculate_horizontal_sa(T, sds, sd1, ta, tb, tl)
                    ra = self.calculate_reduction_factor(T, R, D, I, tb)
                val = sae / ra
            else:
                if T == 0:
                    val = 0.32 * sds
                else:
                    val = self.calculate_vertical_sa(T, sds, ta, tb, tl)
            
            sa_values.append(val)
            
        return periods, np.array(sa_values), {
            "Fs": fs, "F1": f1, "SDS": sds, "SD1": sd1, "TA": ta, "TB": tb
        }
