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

        self._char_to_row = {}
        self._uv_rows = []
        self._uv_table_cache = None

    def _load_mapping(self, json_name):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(current_dir, json_name)
        try:
            with open(path, 'r') as f:
                self.mapping = json.load(f)
            self.is_ready = True
        except Exception as e:
            print(f"❌ SDFTextBuilder: Could not load {path}. Error: {e}")

    def _ensure_uv_table(self, chars_needed):
        grew = False
        for c in chars_needed:
            if c not in self._char_to_row:
                char_data = self.mapping.get(c, self.mapping.get(' '))
                self._char_to_row[c] = len(self._uv_rows)
                self._uv_rows.append((
                    char_data['u_min'], char_data['u_max'],
                    char_data['v_min'], char_data['v_max'],
                ))
                grew = True
        if grew or self._uv_table_cache is None:
            self._uv_table_cache = np.array(self._uv_rows, dtype=np.float32)
        return self._uv_table_cache

    def build_text_geometry(self, labels, default_text_height=0.15):
        if not self.is_ready or not labels:
            return np.array([]), np.array([]), np.array([]), np.array([])

        N = len(labels)
        texts = [lbl['text'] for lbl in labels]
        L = np.fromiter((len(t) for t in texts), dtype=np.int64, count=N)
        total_chars = int(L.sum())
        if total_chars == 0:
            return np.array([]), np.array([]), np.array([]), np.array([])

        vals = np.fromiter((lbl['val'] for lbl in labels), dtype=np.float32, count=N)
        heights = np.fromiter(
            (lbl.get('text_height', default_text_height) for lbl in labels),
            dtype=np.float32, count=N,
        )
        char_advance = heights * 0.55

        origins = np.asarray([lbl['pos_3d'] for lbl in labels], dtype=np.float32)          
        v_rights = np.asarray([lbl['v_right'] for lbl in labels], dtype=np.float32)        
        v_ups = np.asarray([lbl['v_up'] for lbl in labels], dtype=np.float32)              

        colors = np.empty((N, 4), dtype=np.float32)
        for i, lbl in enumerate(labels):
            c = lbl.get('color')
            if c is None:
                c = self.color_pos if vals[i] >= 0 else self.color_neg
            colors[i] = c

        total_width = L.astype(np.float32) * char_advance
        shift_x = np.empty(N, dtype=np.float32)
        for i, lbl in enumerate(labels):
            align = lbl.get('align', 'center')
            if align == 'left':
                shift_x[i] = heights[i] * 0.5
            elif align == 'right':
                shift_x[i] = -total_width[i] - (heights[i] * 0.5)
            else:
                shift_x[i] = -(total_width[i] / 2.0)

        start = origins + v_rights * shift_x[:, None] + v_ups * (heights * 0.4)[:, None]         

        label_idx = np.repeat(np.arange(N, dtype=np.int64), L)                                      
        label_start_offset = np.concatenate(([0], np.cumsum(L)[:-1]))
        char_pos = np.arange(total_chars, dtype=np.float32) - np.repeat(label_start_offset, L).astype(np.float32)

        adv = char_advance[label_idx]
        cursors = start[label_idx] + (char_pos * adv)[:, None] * v_rights[label_idx]                   

        vr = v_rights[label_idx]
        vu = v_ups[label_idx]
        hgt = heights[label_idx]

        bl = cursors
        br = cursors + vr * hgt[:, None]
        tr = br + vu * hgt[:, None]
        tl = cursors + vu * hgt[:, None]

        verts = np.stack([bl, br, tr, tl], axis=1).reshape(-1, 3)                       

        all_chars = ''.join(texts)
        uv_table = self._ensure_uv_table(set(all_chars))
        char_ids = np.fromiter(
            (self._char_to_row[c] for c in all_chars), dtype=np.int64, count=total_chars,
        )
        char_uv = uv_table[char_ids]                                               

        uvs = np.empty((total_chars, 4, 2), dtype=np.float32)
        uvs[:, 0, 0] = char_uv[:, 0]; uvs[:, 0, 1] = char_uv[:, 2]       
        uvs[:, 1, 0] = char_uv[:, 1]; uvs[:, 1, 1] = char_uv[:, 2]       
        uvs[:, 2, 0] = char_uv[:, 1]; uvs[:, 2, 1] = char_uv[:, 3]       
        uvs[:, 3, 0] = char_uv[:, 0]; uvs[:, 3, 1] = char_uv[:, 3]       
        uvs = uvs.reshape(-1, 2)

        vert_colors = np.repeat(colors[label_idx], 4, axis=0)                       

        quad_idx = np.arange(total_chars, dtype=np.uint32) * 4
        tri = np.empty((total_chars, 6), dtype=np.uint32)
        tri[:, 0] = quad_idx
        tri[:, 1] = quad_idx + 1
        tri[:, 2] = quad_idx + 2
        tri[:, 3] = quad_idx
        tri[:, 4] = quad_idx + 2
        tri[:, 5] = quad_idx + 3
        indices = tri.reshape(-1)

        return (
            verts.astype(np.float32),
            uvs.astype(np.float32),
            vert_colors.astype(np.float32),
            indices.astype(np.uint32),
        )
