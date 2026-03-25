"""
LoadImageWithFilename - A custom node that extends LoadImage to also return the filename.

This node loads an image and returns:
- IMAGE: The loaded image tensor
- MASK: The alpha mask (if available)
- STRING: The original filename (without extension)

You can use the STRING output in SaveImage's filename_prefix field to preserve the original filename.

When the image has been painted/masked via the mask editor, the widget value changes to a
clipspace path like "clipspace/clipspace-painted-masked-{ts}.png". This node automatically
resolves back to the original filename via a source map written by middleware at upload time.
"""

import json
import logging
import os
import hashlib
import torch
import numpy as np
from PIL import Image, ImageOps, ImageSequence
from aiohttp import web
import folder_paths
import node_helpers
from server import PromptServer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Middleware: intercept clipspace uploads to record original_ref -> filename
# ---------------------------------------------------------------------------

UPLOAD_PATHS = frozenset({
    '/upload/image', '/upload/mask',
    '/api/upload/image', '/api/upload/mask',
})


@web.middleware
async def _track_clipspace_sources(request, handler):
    response = await handler(request)
    if request.method == 'POST' and request.path in UPLOAD_PATHS and response.status == 200:
        try:
            post = await request.post()
            original_ref_str = post.get("original_ref")
            subfolder = post.get("subfolder", "")
            if original_ref_str and subfolder == "clipspace":
                original_ref = json.loads(original_ref_str)
                resp_data = json.loads(response.body)
                actual_filename = resp_data.get("name", "")
                if actual_filename:
                    input_dir = folder_paths.get_input_directory()
                    clipspace_dir = os.path.join(input_dir, "clipspace")
                    source_map_path = os.path.join(clipspace_dir, "_source_map.json")
                    source_map = {}
                    if os.path.exists(source_map_path):
                        with open(source_map_path, 'r') as f:
                            source_map = json.load(f)
                    source_map[actual_filename] = {
                        "filename": original_ref.get("filename", ""),
                        "subfolder": original_ref.get("subfolder", ""),
                        "type": original_ref.get("type", "input"),
                    }
                    with open(source_map_path, 'w') as f:
                        json.dump(source_map, f, indent=2)
        except Exception:
            logger.debug("Failed to track clipspace source", exc_info=True)
    return response


def register_middleware():
    try:
        PromptServer.instance.app.middlewares.append(_track_clipspace_sources)
    except Exception:
        logger.warning("Could not register clipspace source-tracking middleware")


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class LoadImageWithFilename:
    @classmethod
    def INPUT_TYPES(s):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["image"])
        return {
            "required": {
                "image": (sorted(files), {"image_upload": True}),
            },
            "optional": {
                "filename_mode": (["name_only", "name_with_ext", "full_path"], {
                    "default": "name_only",
                    "tooltip": "name_only: filename without extension (e.g., 'photo'), name_with_ext: filename with extension (e.g., 'photo.jpg'), full_path: full file path"
                }),
            }
        }

    CATEGORY = "image"
    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "filename")
    FUNCTION = "load_image"
    DESCRIPTION = "Loads an image and returns the image, mask, and original filename. Use the filename output in SaveImage's filename_prefix to preserve the original filename."

    def _resolve_clipspace_source(self, image_path):
        """Follow the clipspace source map chain to find the original (pre-masked) filename."""
        basename = os.path.basename(image_path)
        dirpath = os.path.dirname(image_path)
        if not dirpath.endswith("clipspace"):
            return None
        source_map_path = os.path.join(dirpath, "_source_map.json")
        if not os.path.exists(source_map_path):
            return None
        try:
            with open(source_map_path, 'r') as f:
                source_map = json.load(f)
        except (json.JSONDecodeError, IOError):
            return None
        current = basename
        visited = set()
        while current in source_map and current not in visited:
            visited.add(current)
            ref = source_map[current]
            if ref.get("subfolder") == "clipspace":
                current = ref["filename"]
            else:
                return ref["filename"]
        return None

    def load_image(self, image, filename_mode="name_only"):
        image_path = folder_paths.get_annotated_filepath(image)

        source_filename = self._resolve_clipspace_source(image_path)
        if source_filename:
            effective_path = folder_paths.get_annotated_filepath(source_filename)
        else:
            effective_path = image_path

        if filename_mode == "name_only":
            filename = os.path.splitext(os.path.basename(effective_path))[0]
        elif filename_mode == "name_with_ext":
            filename = os.path.basename(effective_path)
        else:  # full_path
            filename = effective_path

        img = node_helpers.pillow(Image.open, image_path)

        output_images = []
        output_masks = []
        w, h = None, None

        for i in ImageSequence.Iterator(img):
            i = node_helpers.pillow(ImageOps.exif_transpose, i)

            if i.mode == 'I':
                i = i.point(lambda i: i * (1 / 255))
            image = i.convert("RGB")

            if len(output_images) == 0:
                w = image.size[0]
                h = image.size[1]

            if image.size[0] != w or image.size[1] != h:
                continue

            image = np.array(image).astype(np.float32) / 255.0
            image = torch.from_numpy(image)[None,]
            if 'A' in i.getbands():
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
            elif i.mode == 'P' and 'transparency' in i.info:
                mask = np.array(i.convert('RGBA').getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
            else:
                mask = torch.zeros((64,64), dtype=torch.float32, device="cpu")
            output_images.append(image)
            output_masks.append(mask.unsqueeze(0))

            if img.format == "MPO":
                break

        if len(output_images) > 1:
            output_image = torch.cat(output_images, dim=0)
            output_mask = torch.cat(output_masks, dim=0)
        else:
            output_image = output_images[0]
            output_mask = output_masks[0]

        return (output_image, output_mask, filename)

    @classmethod
    def IS_CHANGED(s, image, filename_mode="name_only"):
        image_path = folder_paths.get_annotated_filepath(image)
        m = hashlib.sha256()
        with open(image_path, 'rb') as f:
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(s, image, filename_mode="name_only"):
        if not folder_paths.exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)
        return True


NODE_CLASS_MAPPINGS = {
    "LoadImageWithFilename": LoadImageWithFilename
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadImageWithFilename": "Load Image With Filename"
}
