# Destructible Terrain Rasterization & BlendMode.ERASE Technical Audit

**Project**: Web Flash Player Pro  
**Date**: 2026-08-19  
**Target Engine**: Ruffle WebAssembly (ActionScript 3 / AVM2)  
**Game Reference**: Gunny / DDTank Version 2.3 (7Road / Road7 ActionScript 3 Engine)

---

## 1. Problem Statement & Observed Symptoms
- During live battle on map surfaces (e.g. Map 1042 "Tàu Cướp Biển"), weapon explosion craters and player drill/tunnel holes fail to carve transparent holes through the foreground ground bitmap.
- Instead of holes revealing the underlying background scene (sky / ferris wheel), the craters appear as **solid filled disks**:
  - On the wooden ship deck: **Solid orange circular disks** (`#D85527`) with burnt grass fringes.
  - On the woven ropes: **Solid light grey/blue circular disks** (`#AEC3CE`) stacked vertically.

---

## 2. ActionScript 3 Engine Architecture
In the DDTank / Gunny map engine (`game.view.map.MapView`):
```actionscript
public class MapView extends Sprite {
    private var _ground: Bitmap;        // Visual ground layer (BitmapData)
    private var _realGround: Bitmap;    // Physical collision layer (BitmapData)

    public function Dig(crater: Shape, matrix: Matrix): void {
        // Render crater with BlendMode.ERASE onto BitmapData
        this._ground.bitmapData.draw(crater, matrix, null, BlendMode.ERASE);
        this._realGround.bitmapData.draw(crater, matrix, null, BlendMode.ERASE);
    }
}
```

### Flash Player Specification:
- When `BitmapData.draw` is executed with `BlendMode.ERASE`, Adobe Flash Player modifies the alpha channel of the destination `BitmapData` by subtracting source alpha:
  $$\text{Alpha}_{\text{dest}} = \text{Alpha}_{\text{dest}} \times (1.0 - \text{Alpha}_{\text{src}})$$
- Pixels covered by the opaque circle in `crater` have their alpha set to `0x00`, turning that region 100% transparent.

### Ruffle WASM Execution Behavior:
- In WebGL2 / WGPU backend:
  - `BitmapData.draw` executes off-screen rendering using internal render targets (`render_offscreen`).
  - If the source display tree contains multiple nested shapes or if the destination `Bitmap` uses `cacheAsBitmap = true`, the WebGL texture cache may not be invalidated or the blending pass defaults to `BlendMode.NORMAL`, causing the base color of the shape (orange / grey) to be rendered directly onto the surface instead of clearing destination alpha.

---

## 3. Verified Hypotheses & Solution Pathways

### Pathway A: Runtime Flash Emulation Parameters
- Configure Ruffle with `playerRuntime: 'flashPlayer'`, `playerVersion: 32`, and `compatibilityRules: false` to force AVM2 Stage3D/BitmapData modern behavior and bypass AVM1 legacy quirks.

### Pathway B: WebGL Canvas Alpha Channel Compositing
- Ensure the underlying HTML5 `<canvas>` element created by Ruffle has `{ alpha: true, premultipliedAlpha: false }` so that cleared alpha pixels properly composite against CSS and HTML parent containers.

### Pathway C: Software Canvas2D Fallback
- For devices where WGPU WebGL2 shaders fail offscreen alpha blending, provide a Software Canvas2D renderer option (`preferredRenderer: 'canvas'`), which natively supports `globalCompositeOperation = 'destination-out'`.

---

## 4. Continuity & Future Session Handoff
This document serves as primary authority for any future task or agent session investigating Gunny terrain destruction, `BitmapData.draw`, or Ruffle shader blending.
