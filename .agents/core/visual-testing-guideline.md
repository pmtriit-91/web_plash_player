# Visual Runtime Debugging & Puppeteer Testing Guideline

This document defines the strict principles and implementation patterns for writing runtime Puppeteer tests. The goal is to ensure visual clarity, realistic browser emulation, and smooth UI transitions for human reviewers.

---

## 1. Principles of Visual Integrity

### Rule 1.1: Preserve Realistic Viewport Size
*   **DO NOT** stretch the viewport artificially (e.g. using `1920x1080` or extremely wide dimensions) to force elements into the DOM and bypass scrolling.
*   **DO** use the standard desktop viewport representing a MacBook 13-inch M3 device (default to **`1440x900`**).
*   **Reasoning**: Virtualized lists/grids (like Material UI DataGrid) only mount DOM elements within or near the viewport. Artificially wide viewports hide layout/wrapping bugs and prevent visual validation of scroll features.

### Rule 1.2: UI-Based Navigation Only
*   **DO NOT** jump directly to sub-routes using `page.goto(url)` after logging in, unless absolutely necessary.
*   **DO** navigate interactively by clicking sidebar menus, expanding dropdowns, and selecting menu items.
*   **Reasoning**: Demonstrates navigation flows visually and ensures layout sidebar menus behave correctly under test conditions.

### Rule 1.3: Clean Authentication Flow via UI
*   **DO** check for existing login state on the homepage, open the user profile dropdown, and click the "Logout" button via the UI before executing login tests.
*   **DO NOT** just clear `localStorage` via scripts and trigger a silent reload.

---

## 2. Scroll and Interaction Patterns

### Pattern 2.1: Element-Specific Smooth Scrolling
When a target element (like an Action button) is hidden inside a scrollable container (e.g., MUI DataGrid virtual scroller), perform a smooth scroll on that container instead of a sudden jump.

```javascript
// Example: Smooth scroll a table container to the right to reveal action buttons
await page.evaluate(() => {
    const scroller = document.querySelector('.MuiDataGrid-virtualScroller');
    if (scroller) {
        scroller.scrollTo({
            left: scroller.scrollWidth,
            behavior: 'smooth'
        });
    }
});
// CRITICAL: Always wait for the scroll animation to finish and DOM to remount virtual columns
await new Promise(r => setTimeout(r, 2500));
```
