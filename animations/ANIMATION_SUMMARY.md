# OpenAdapt Evals Animation Summary

## Generated Animations

This directory contains animated GIF demonstrations of the OpenAdapt benchmark viewer in action.

**Generation Date:** January 18, 2026

**Important:** All animations use real WAA evaluation data to provide accurate representation of capabilities.

### Files Generated

| Animation | File | Size | Description |
|-----------|------|------|-------------|
| Benchmark Viewer | `benchmark-viewer.gif` | 88 KB | Demonstration using real WAA evaluation results from `waa-live_eval_20260116_200004` |

### Animation Details

**Technical Specifications:**
- Resolution: 1920x1080 (Full HD)
- Frame Count: 5 frames per animation
- Frame Duration: 500ms per frame
- Format: Animated GIF
- Total Animation Duration: ~2.5 seconds (looped)

**Animation Infrastructure:**
- Generated using: `openadapt-viewer/scripts/generate_animations.py`
- Browser automation: Playwright (Chromium)
- Image processing: Pillow, imageio
- Optimization: Disabled (gifsicle not available)

### What the Animation Shows

The animation demonstrates key features of the benchmark viewer using real WAA evaluation data:

1. **Frame 1: Overview** - Initial state showing summary statistics and task list from actual evaluation
2. **Frame 2-5: Static captures** - Additional views of the viewer interface with real screenshots

**Data Source:** `waa-live_eval_20260116_200004` - Real Windows Agent Arena evaluation run

**Note:** Interactive features (task selection, log expansion, playback) were not captured in this version due to selector mismatches between the scenario script and actual viewer HTML structure.

### Usage in Documentation

The primary animation (`benchmark-viewer.gif`) has been embedded in the README.md:

```markdown
### Demo: Benchmark Viewer in Action

![Benchmark Viewer Animation](animations/benchmark-viewer.gif)
```

This provides visual proof that the benchmark viewer works with real WAA evaluation results, demonstrating actual capabilities rather than synthetic data.

### Improvements for Future Animations

To capture full interactive demonstrations:

1. **Update selectors** in `openadapt-viewer/src/openadapt_viewer/animation/scenarios.py` to match actual viewer HTML:
   - Task list item selector
   - Log toggle button selector
   - Playback control selectors

2. **Add ffmpeg support** for MP4 generation:
   ```bash
   uv add "imageio[ffmpeg]"
   ```

3. **Enable GIF optimization** with gifsicle:
   ```bash
   brew install gifsicle
   ```

4. **Create custom scenarios** for specific viewer features:
   - Cost tracking dashboard
   - Live monitoring views
   - Domain-specific task filtering

### Regenerating Animations

To regenerate or create new animations:

```bash
# Navigate to openadapt-viewer
cd /Users/abrichr/oa/src/openadapt-viewer

# Generate animation for a specific viewer
uv run python scripts/generate_animations.py \
    --ui benchmark-viewer \
    --html /path/to/viewer.html \
    --output /Users/abrichr/oa/src/openadapt-evals/animations/ \
    --no-optimize

# Generate with all formats (requires ffmpeg)
uv run python scripts/generate_animations.py \
    --ui benchmark-viewer \
    --html /path/to/viewer.html \
    --output /Users/abrichr/oa/src/openadapt-evals/animations/ \
    --all-formats
```

### Related Documentation

- Animation infrastructure: `/Users/abrichr/oa/src/openadapt-viewer/README.md`
- Benchmark viewer: `/Users/abrichr/oa/src/openadapt-evals/README.md`
- Scenario definitions: `/Users/abrichr/oa/src/openadapt-viewer/src/openadapt_viewer/animation/scenarios.py`

---

**Note:** These animations serve as proof-of-concept that the viewer works with real benchmark data. Future iterations can capture more interactive demonstrations once the scenario selectors are aligned with the viewer's HTML structure.
