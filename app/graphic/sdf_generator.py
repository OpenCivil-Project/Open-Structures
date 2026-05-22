import os
import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import distance_transform_edt

def generate_sdf_atlas(font_name="consola.ttf", out_prefix="font_atlas"):
    """
    Generates an SDF texture atlas and JSON mapping for 3D text rendering.
    Requires: pip install Pillow scipy numpy
    """
    print(f">> Starting SDF Generation for {font_name}...")
    
    chars = " 0123456789.-+eEKNm,ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    chars = "".join(dict.fromkeys(chars))              
    
    cols = 8
    rows = (len(chars) + cols - 1) // cols
    
    hr_size = 256
    lr_size = 64
    downscale = hr_size // lr_size
    spread = 32                                                   
    
    atlas_lr = np.zeros((rows * lr_size, cols * lr_size), dtype=np.uint8)
    mapping = {}
    
    try:
                                                                              
        font = ImageFont.truetype(font_name, 180)
    except IOError:
        print(f"❌ Error: Could not find font '{font_name}'. Try 'arial.ttf' or provide a full path.")
        return

    img = Image.new('L', (hr_size, hr_size), color=0)
    draw = ImageDraw.Draw(img)

    for i, char in enumerate(chars):
        row = i // cols
        col = i % cols
        
        draw.rectangle([0, 0, hr_size, hr_size], fill=0)
        
        bbox = font.getbbox(char)
        if bbox:
            left, top, right, bottom = bbox
            char_w = right - left
            char_h = bottom - top
            
            x = (hr_size - char_w) / 2 - left
            y = (hr_size - char_h) / 2 - top
            draw.text((x, y), char, fill=255, font=font)
        else:
            char_w, char_h = hr_size // 2, hr_size // 2

        img_arr = np.array(img)
        
        inside = distance_transform_edt(img_arr > 127)
                               
        outside = distance_transform_edt(img_arr <= 127)
        
        sdf = inside - outside
        
        sdf = np.clip(sdf / spread, -1.0, 1.0)
        sdf = (sdf + 1.0) * 127.5
        sdf = sdf.astype(np.uint8)
        
        sdf_downscaled = sdf.reshape(lr_size, downscale, lr_size, downscale).mean(axis=(1, 3))
        
        lr_y = row * lr_size
        lr_x = col * lr_size
        atlas_lr[lr_y:lr_y+lr_size, lr_x:lr_x+lr_size] = sdf_downscaled
        
        u_min = lr_x / (cols * lr_size)
        u_max = (lr_x + lr_size) / (cols * lr_size)
        
        v_min = 1.0 - ((lr_y + lr_size) / (rows * lr_size))
        v_max = 1.0 - (lr_y / (rows * lr_size))
        
        mapping[char] = {
            "u_min": u_min,
            "v_min": v_min,
            "u_max": u_max,
            "v_max": v_max,
            "aspect": char_w / max(char_h, 1)                                    
        }
        
        print(f"Processed: '{char}'")

    out_dir = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(out_dir, f"{out_prefix}.png")
    json_path = os.path.join(out_dir, f"{out_prefix}.json")
    
    Image.fromarray(atlas_lr).save(img_path)
    with open(json_path, 'w') as f:
        json.dump(mapping, f, indent=4)
        
    print(f"\n>> SUCCESS! Saved {img_path} and {json_path}")

if __name__ == "__main__":
                                                                                       
    generate_sdf_atlas("consola.ttf", "font_atlas")
