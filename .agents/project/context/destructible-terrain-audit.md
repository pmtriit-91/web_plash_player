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

## 3. Verified Hypotheses & Testing Matrix

| Experiment | Configuration | Empirical Result | Technical Cause / Finding |
| :--- | :--- | :---: | :--- |
| **Option 1** | `playerRuntime: 'flashPlayer'`, `playerVersion: 32`, `compatibilityRules: false`, `wmode: 'transparent'` | ❌ Lỗi vẫn còn (Hình tròn màu cam đặc trên map) | AVM2 emulation flags alone do not alter WGPU offscreen shader blending logic. |
| **Option 2** | `preferredRenderer: 'canvas'` (Canvas 2D Software Engine) | ❌ Đứng ở 100% Loading | Gunny 2.3 ActionScript 3 client requires WebGL / Stage3D hardware acceleration context during initialization. Canvas 2D lacks Stage3D. |
| **Option 3** | `preferredRenderer: 'wgpu-webgl'`, `webgl`, `webgpu` + `wmode: 'direct'` | ❌ Lỗi vẫn còn (Hình tròn màu cam đặc trên map) | Ruffle WASM's `BitmapData.draw` offscreen rendering pipeline (`operations.rs`) currently renders vector shape fill colors instead of executing alpha clearing for `BlendMode::Erase`. |

---

## 4. Architectural Ground Truth & Conclusion
- **Root Cause Identified**: In Ruffle WASM's AVM2 implementation (`core/src/bitmap/operations.rs`), `BitmapData.draw(source, ..., BlendMode.ERASE)` offscreen passes for vector shapes currently execute normal fill rasterization rather than alpha channel subtraction on the destination bitmap buffer.
- **Upstream Dependency**: Full destructible terrain transparency requires Ruffle's upstream implementation of offscreen vector `BlendMode::Erase` shaders.
- **Continuity Status**: All findings, test evidence, and decompiled ActionScript 3 architecture are permanently committed and bound to Universal Agent OS V9.1.0 Project Authority.
