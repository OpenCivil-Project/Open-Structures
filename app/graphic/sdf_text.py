import json
import os
import numpy as np

class SDFTextBuilder:
    def __init__(self, json_path="font_atlas.json"):
        self.mapping = {}
        self.is_ready = False
        self._load_mapping(json_path)
        
        self.color_pos = [0.2, 0.5, 1.0, 1.0]
        self.color_neg = [1.0, 0.2, 0.2, 1.0]

    def _load_mapping(self, json_name):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_dir, json_name)
        try:
            with open(path, 'r') as f:
                self.mapping = json.load(f)
            self.is_ready = True
        except Exception as e:
            print(f"❌ SDFTextBuilder: Could not load {path}. Error: {e}")

    def build_text_geometry(self, labels, default_text_height=0.15):
        if not self.is_ready or not labels:
            return np.array([]), np.array([]), np.array([]), np.array([])

        all_verts = []
        all_uvs = []
        all_colors = []
        all_indices = []
        vertex_offset = 0

        for label in labels:
            text = label['text']
            val = label['val']
            
            current_text_height = label.get('text_height', default_text_height)
            char_advance = current_text_height * 0.55
            
            origin = np.array(label['pos_3d'], dtype=np.float32)
            v_right = np.array(label['v_right'], dtype=np.float32)
            v_up = np.array(label['v_up'], dtype=np.float32)
            
            color = label.get('color', self.color_pos if val >= 0 else self.color_neg)

            total_width = len(text) * char_advance
            align = label.get('align', 'center')
            
            if align == 'left':
                shift_x = current_text_height * 0.5
            elif align == 'right':
                shift_x = -total_width - (current_text_height * 0.5)
            else:
                shift_x = -(total_width / 2.0)

            cursor_pos = origin + (v_right * shift_x) + (v_up * (current_text_height * 0.4))

            for char in text:
                char_data = self.mapping.get(char, self.mapping.get(' '))
                u_min, u_max = char_data['u_min'], char_data['u_max']
                v_min, v_max = char_data['v_min'], char_data['v_max']

                quad_w = current_text_height
                quad_h = current_text_height

                bl = cursor_pos
                br = cursor_pos + (v_right * quad_w)
                tr = cursor_pos + (v_right * quad_w) + (v_up * quad_h)
                tl = cursor_pos + (v_up * quad_h)

                all_verts.extend([bl, br, tr, tl])
                all_uvs.extend([[u_min, v_min], [u_max, v_min], [u_max, v_max], [u_min, v_max]])
                all_colors.extend([color, color, color, color])
                
                idx = vertex_offset
                all_indices.extend([idx, idx+1, idx+2, idx, idx+2, idx+3])
                
                vertex_offset += 4
                cursor_pos = cursor_pos + (v_right * char_advance)

        return (
            np.array(all_verts, dtype=np.float32),
            np.array(all_uvs, dtype=np.float32),
            np.array(all_colors, dtype=np.float32),
            np.array(all_indices, dtype=np.uint32)
        )
