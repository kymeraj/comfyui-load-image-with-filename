# Load Image With Filename

A [ComfyUI](https://github.com/comfyanonymous/ComfyUI) custom node that works just like the built-in **Load Image** node, but adds a **filename** string output.

## Why?

The stock Load Image node outputs the image tensor and mask, but not the filename. If you want your saved outputs to keep the same name as the input file (e.g., for batch inpainting), you have to type it manually.

**Load Image With Filename** gives you a `filename` output you can wire straight into Save Image's `filename_prefix` -- your outputs automatically inherit the original file name.

## Features

- Drop-in replacement for the built-in Load Image node (same inputs, same image/mask outputs).
- Extra **filename** `STRING` output with three modes:
  - `name_only` -- filename without extension (default, e.g. `photo`)
  - `name_with_ext` -- filename with extension (e.g. `photo.png`)
  - `full_path` -- absolute file path
- **Clipspace / mask-editor aware** -- when you paint or mask an image via the built-in mask editor, ComfyUI renames the file to something like `clipspace/clipspace-painted-masked-{timestamp}.png`. This node automatically resolves back to the **original** filename so your outputs keep the correct name.

## Installation

### Via ComfyUI Manager (recommended)

Search for **"Load Image With Filename"** in the ComfyUI Manager and click Install.

### Manual

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/kymeraj/comfyui-load-image-with-filename.git
```

Restart ComfyUI.

## Usage

1. Add the **Load Image With Filename** node (search "Load Image With Filename" in the node menu).
2. Load an image as usual (drag-and-drop or select from the dropdown).
3. Connect the `filename` output to Save Image's `filename_prefix` input (or anywhere you need the name).
4. If you open the mask editor and paint/mask the image, the `filename` output still returns the original file name.

## How clipspace resolution works

When you use the mask editor, ComfyUI's frontend uploads several intermediate files to `input/clipspace/` and changes the widget value to the new clipspace path. This node registers a lightweight server middleware that records which original file each clipspace upload came from (stored as `input/clipspace/_source_map.json`). At execution time, the node follows this reference chain back to the original filename.

## License

[MIT](LICENSE)
