# -*- coding: utf-8 -*-
# hero mode: use rembg to remove background, keep subject, put on white bg
import os

_session = None

def _get_session():
    global _session
    if _session is None:
        from rembg import new_session
        _session = new_session("u2net")
    return _session

def extract_subject(image_path, out_path):
    # remove background with alpha matting for cleaner edges,
    # then composite subject onto a white background (best for Tripo image-to-3d).
    try:
        from rembg import remove
        from PIL import Image
        import io
        with open(image_path, "rb") as f:
            data = f.read()
        cut = remove(
            data,
            session=_get_session(),
            alpha_matting=True,
            alpha_matting_foreground_threshold=270,
            alpha_matting_background_threshold=20,
            alpha_matting_erode_size=11,
        )
        fg = Image.open(io.BytesIO(cut)).convert("RGBA")
        # white background composite
        bg = Image.new("RGBA", fg.size, (255, 255, 255, 255))
        bg.paste(fg, (0, 0), fg)
        out = bg.convert("RGB")
        # ensure .png output path
        if not out_path.lower().endswith(".png"):
            out_path = os.path.splitext(out_path)[0] + ".png"
        out.save(out_path)
        return out_path
    except Exception as e:
        print("segment failed, use original:", e)
        return image_path
