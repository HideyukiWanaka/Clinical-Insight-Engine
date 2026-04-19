# Design System Document: High-End Clinical Intelligence

## 1. Overview & Creative North Star
**The Creative North Star: "The Clinical Curator"**

In the world of high-stakes clinical research, data is often overwhelming and chaotic. This design system rejects the cluttered, line-heavy aesthetic of traditional enterprise software. Instead, it adopts the persona of a "Clinical Curator"—an interface that feels like a premium, high-end editorial journal combined with the precision of a laboratory instrument.

To move beyond a "template" look, we utilize **Intentional Asymmetry** and **Tonal Depth**. By favoring negative space over containment lines, we allow the data to breathe, signaling a level of sophistication and "quiet authority." This system doesn't just display data; it presents it with medical-grade clarity and high-end elegance.

---

## 2. Colors: Tonal Architecture
The color strategy moves away from "flat" design into a tiered architectural approach. We use a palette of sophisticated blues and slate grays to establish trust without feeling cold.

### The "No-Line" Rule
**Explicit Instruction:** Designers are prohibited from using 1px solid borders for sectioning or layout containment. Boundaries must be defined through:
- **Background Shifts:** Using `surface-container-low` against a `surface` background.
- **Tonal Transitions:** Defining logic blocks through color blocks rather than strokes.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers, like stacked sheets of optical-grade glass.
- **Base Layer:** `surface` (#f8f9ff) serves as the canvas.
- **Content Zones:** Use `surface-container-low` (#eff4ff) for sidebar or secondary navigation areas.
- **Interactive Focus:** Use `surface-container-lowest` (#ffffff) for the most important data cards to create a natural, "raised" visual priority.

### The Glass & Gradient Rule
To ensure the "Clinical Insight Engine" feels premium, use **Glassmorphism** for floating elements (modals, popovers). Use semi-transparent surface colors with a `20px` backdrop-blur. 
- **CTA Soul:** Main buttons and hero headers should utilize a subtle linear gradient from `primary` (#003e78) to `primary-container` (#0a559f). This adds a "visual soul" and depth that prevents the interface from looking sterile.

---

## 3. Typography: Editorial Authority
We utilize **Inter** not as a standard UI font, but as a high-readability editorial tool.

*   **Display (lg/md/sm):** Used for high-level data summaries or dashboard "hero" metrics. Wide letter-spacing and `medium` weights convey a sense of modern precision.
*   **Headline & Title:** These are the "Curator" levels. They use `surface-on-background` (#0b1c30) to create high-contrast anchors for the eye.
*   **Body (lg/md/sm):** Optimized for long-form research notes. Line heights are increased to `1.6` for `body-md` to ensure legibility during intensive analysis.
*   **Labels:** Small, all-caps treatments with slightly increased tracking are used for metadata to distinguish it from the "narrative" of the data.

---

## 4. Elevation & Depth: Tonal Layering
Traditional shadows are often a crutch for poor layout. This system uses **Tonal Layering** as the primary driver of hierarchy.

*   **The Layering Principle:** Stack `surface-container` tiers. A `surface-container-lowest` card placed on a `surface-container-low` section creates a "soft lift" that feels architectural rather than digital.
*   **Ambient Shadows:** If a floating effect is required (e.g., a "New Analysis" modal), use an extra-diffused shadow: `box-shadow: 0 12px 40px rgba(11, 28, 48, 0.06)`. Note the tint: we use the `on-surface` color (#0b1c30) at a very low opacity to mimic natural ambient light.
*   **The "Ghost Border" Fallback:** If a border is required for accessibility (e.g., in a data table header), use `outline-variant` (#c2c6d3) at **15% opacity**. Never use 100% opaque lines.
*   **Glassmorphism Depth:** For overlays, use `surface_variant` at 80% opacity with a `backdrop-filter: blur(12px)`. This integrates the overlay into the environment rather than "pasting" it on top.

---

## 5. Components: The Research Toolkit

### Buttons
*   **Primary:** Linear gradient (`primary` to `primary-container`), `md` corner radius (0.375rem). Use `on-primary` (#ffffff) for text.
*   **Secondary:** Ghost style using `secondary` text. No border; background appears as `surface-container-high` on hover.
*   **Tertiary:** Text-only, using `primary` color for high-visibility actions within dense data.

### Data Tables (The Precision Grid)
*   **No Dividers:** Prohibit horizontal and vertical lines. Use alternating row colors (`surface` and `surface-container-low`) or 16px of vertical white space to separate entries.
*   **Header:** Use `label-md` in `on-surface-variant` (#424751) to keep the focus on the data cells.

### Research Cards
*   **Structure:** No borders. Background: `surface-container-lowest` (#ffffff).
*   **Padding:** Aggressive 32px internal padding to emphasize the "High-End" feel. 
*   **Shadow:** Only on hover—a subtle 4% ambient shadow to indicate interactivity.

### Status Chips
*   **Medical Logic:** Use `tertiary_container` (#8a4000) for "In Progress" and `error_container` (#ffdad6) for "Anomalies Detected." Text must always be the "On" variant for accessibility.

---

## 6. Do's and Don'ts

### Do:
*   **Do** use asymmetrical layouts (e.g., a wide data column next to a narrow "Insights" sidebar) to break the "standard dashboard" feel.
*   **Do** prioritize vertical rhythm. Use the Spacing Scale to create "breathing room" between disparate data sets.
*   **Do** use `primary` (#003e78) sparingly as an accent to guide the eye to the most critical action.

### Don't:
*   **Don't** use 100% black text. Always use `on-surface` (#0b1c30) for better optical comfort.
*   **Don't** use "Default" 1px borders. If a container feels invisible, increase the tonal contrast of the background colors rather than adding a line.
*   **Don't** crowd the interface. If a screen feels full, use a "layered" approach (e.g., a slide-out panel) instead of shrinking font sizes.