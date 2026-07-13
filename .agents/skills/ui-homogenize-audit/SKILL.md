---
name: ui-homogenize-audit
description: Audits a codebase or UI for visual and structural consistency — finds design token drift, mismatched components, broken patterns, spacing/typography/color inconsistencies, and any place the UI deviates from its own design system. Use whenever someone asks about UI consistency, design system compliance, visual homogenization, unifying the look and feel, standardizing components, cleaning up design debt, or making the app look like one cohesive product instead of a collection of screens. Works with any frontend stack (React, Vue, Tailwind, plain CSS, etc.) by reading source code and/or analyzing described visual output. Produces a structured report with findings, severity, and actionable fixes.
---

# UI Homogenization Audit

## Overview

This skill audits a codebase (or described UI) to find every place where the visual design drifts from the project's own patterns. The goal is a **unified, cohesive UI** — where the same thing looks the same everywhere, spacing follows a scale, colors come from tokens, and component usage is consistent across all screens.

The audit produces a structured report organized by design dimension, with each finding graded by severity and paired with a concrete fix.

Unlike a general UX audit (which focuses on usability and flow), this skill is purely about **visual and structural consistency** — making the UI look like one product, not many.

## Report Structure

Every audit produces this exact template. Fill in findings under each section. If a section has zero findings, mark it `✓ No issues found`.

```markdown
# UI Homogenization Audit: [Project/Area Name]

**Date:** [date]
**Scope:** [what was reviewed — files, screens, components]

---

## Summary

[X] total findings — [C] critical, [M] major, [m] minor, [n] nitpick
Overall consistency score: [Good / Fair / Poor / Fragmented]

**Top 3 priorities:**
1. [most impactful fix]
2. [second]
3. [third]

---

## 1. Color System

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | src/Button.tsx:24 | Hardcoded hex `#3B82F6` instead of `var(--color-primary)` | `<button class="bg-[#3B82F6]">` | `bg-primary` | Major |

Patterns to check:
- Hardcoded hex/rgb/hsl values outside the design token system
- Inconsistent use of semantic vs raw colors (e.g., using `text-red-500` for errors in one place, `text-status-error` in another)
- Missing dark mode variants where the rest of the app has them
- Color applied to wrong semantic role (e.g., `bg-primary` on a destructive action)

## 2. Typography

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | src/pages/About.tsx:45 | Inline style font size 15px | `style={{ fontSize: 15 }}` | `text-sm` or design token | Minor |

Patterns to check:
- Font sizes, weights, line heights outside the type scale
- Mixed heading levels (skipping h2→h4, using h2 styling on a span)
- Different font stacks or `font-family` declarations
- Inconsistent text colors (some headings `text-gray-900`, others `text-gray-800`)
- Line-height inconsistency between similar text elements

## 3. Spacing & Layout

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | src/components/Card.tsx:12 | Arbitrary padding `p-[13px]` | `p-[13px]` | `p-3` or `p-4` | Minor |

Patterns to check:
- Pixel values outside the spacing scale (e.g., `p-[13px]`, `gap-[7px]`)
- Inconsistent gap/margin/padding between similar components
- Layout patterns that change arbitrarily between screens (e.g., centered on one page, left-aligned on another)
- Missing or inconsistent max-width/page container patterns

## 4. Border Radius

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | src/components/Modal.tsx:30 | `rounded-3xl` on modal — rest use `rounded-lg` | `rounded-3xl` | `rounded-lg` | Major |

Patterns to check:
- Corner radii on similar elements that don't match (all cards `rounded-lg` except one `rounded-xl`)
- Radius used at the wrong hierarchy level (buttons with `rounded-full` when the design system uses `rounded-md`)
- Inline border-radius values instead of tokens

## 5. Component Consistency

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | src/pages/Settings.tsx:88 | Native `<select>` instead of project's `Select` component | `<select class="...">` | `<Select />` | Critical |

Patterns to check:
- Native HTML elements where a design system component exists
- Multiple implementations of the same pattern (two different button styles, three different card patterns)
- Inconsistent interaction patterns (some toggles are checkboxes, others are switch components)
- Missing shared wrapper/layout components
- Custom CSS where utility classes would suffice

## 6. Forms & Inputs

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | Login form | No error state styling on input | `border-gray-300` always | `border-red-500` on error | Minor |

Patterns to check:
- Input height, border, focus ring inconsistent across forms
- Label placement (top vs left) varies between forms
- Validation error styling differs (red border in one, red text in another, toast in third)
- Button placement in forms (right-aligned vs full-width vs left-aligned)
- Placeholder styling, disabled state, read-only state

## 7. Icons & Imagery

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | Header | Icon size 20px, rest use 16px | `size={20}` | `size={4}` (16px) | Minor |

Patterns to check:
- Mixed icon libraries (Lucide + Heroicons + Font Awesome)
- Inconsistent icon sizes for the same semantic role
- Missing icons where patterns use them (e.g., "edit" buttons sometimes have ✏️, sometimes just text)
- Image aspect ratios or fit behaviors differ
- SVG inline vs icon component inconsistency

## 8. Shadows & Elevation

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | Dropdown menu | `shadow-2xl`, rest use `shadow-lg` | `shadow-2xl` | `shadow-lg` | Minor |

Patterns to check:
- Shadow levels inconsistent between same-type elements
- Custom `box-shadow` where a token exists
- Elevation hierarchy not respected (modals have same shadow as cards)

## 9. Responsive Patterns

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | ProductGrid | Uses `grid-cols-2` mobile, rest use `grid-cols-1` | `grid-cols-2 sm:grid-cols-3` | `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3` | Major |

Patterns to check:
- Breakpoint usage inconsistent (some using `sm:`, others `md:` for the same trigger point)
- Mobile layout patterns differ between pages
- Missing responsive variants on some elements (padding, typography, grids)

## 10. Animation & Transitions

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | Sidebar toggle | `transition-all duration-500`, rest use `duration-200` | `duration-500` | `duration-200` | Minor |

Patterns to check:
- Transition durations and easings inconsistent
- Missing transitions where they exist on similar elements
- Different animation libraries or approaches (CSS transitions vs Framer Motion vs plain JS)

---

## Detailed Recommendations

### Critical fixes (blockers)
For each:
- **What**: one-line description
- **Where**: file:line
- **Why it matters**: this inconsistency causes [user confusion / brand damage / maintenance burden]
- **Fix**: exact code or component change

### Major fixes
For each:
- **What**: one-line description
- **Where**: file:line
- **Fix**: exact code or component change

### Minor & nitpicks
Grouped by area, listed concisely.

---

## Appendix: Design Token Reference

Document the actual design tokens discovered (or expected):
- **Color**: primary, secondary, accent, success, warning, error, surface, text variants
- **Spacing**: 0.25rem / 0.5rem / 0.75rem / 1rem / 1.5rem / 2rem / 3rem / 4rem
- **Typography**: font families, size scale, weight scale, line-height
- **Radius**: none, sm, md, lg, full
- **Shadow**: sm, md, lg, xl
- **Breakpoints**: sm(640), md(768), lg(1024), xl(1280)
```

## Audit Process

### Phase 1: Discover the Design System

Before finding inconsistencies, learn the project's actual design tokens:

1. **Read the design system config** — `tailwind.config.js`, CSS custom properties, theme files, design token files
2. **Find the component library** — check for shared components (Button, Input, Card, Modal, etc.)
3. **Identify the icon library** and its usage pattern
4. **Note the spacing/type/color scales** in use

If no formal design system exists, infer one from the most commonly used patterns. That becomes the baseline.

### Phase 2: Scan for Drift

Walk through the codebase systematically:

1. **Global search for hardcoded values**: `grep` for hex colors (`#[0-9a-fA-F]{3,6}`), arbitrary Tailwind values (`[` in class names), inline `style={{` props, raw `font-size:`, `box-shadow:`, `border-radius:`
2. **Component inventory**: List every component that duplicates functionality (are there 3 different button components?)
3. **Cross-page comparison**: Compare the same patterns across different routes/pages
4. **Dark mode audit**: If dark mode exists, check every dark variant is present

### Phase 3: Report

Write the structured report. For each finding:

- **Be specific**: Include exact file paths, line numbers, and current code
- **Show the fix**: Provide the exact change needed
- **Explain why**: One sentence on why the inconsistency matters
- **Grade honestly**: Not every mismatch is critical — use the severity scale

## Severity Guide

| Severity | Meaning | Examples |
|----------|---------|----------|
| **Critical** | Ships bugs, breaks the UX, or is a maintenance liability | Native elements where components exist, missing dark mode on primary actions, broken responsive layouts |
| **Major** | Visible inconsistency that damages perceived quality | Different button styles, mismatched radii on same-type elements, inconsistent heading hierarchy |
| **Minor** | Subtle drift — noticeable if looking | Off-by-one spacing, slightly different font weight, inconsistent icon sizes |
| **Nitpick** | Pedantic — only matters at highest polish level | 2px alignment difference, one-off transition duration, hardcoded value that happens to match the token |

## Code Patterns to Search For

When scanning a codebase, these are high-signal patterns:

```bash
# Hardcoded colors (Tailwind arbitrary values or raw hex)
# In React: className="bg-[#ff0000]" or style={{ color: '#ff0000' }}

# Arbitrary spacing (Tailwind arbitrary values)
# In React: className="p-[13px]" or style={{ padding: '13px' }}

# Mixed component usage
# Search for: <button vs <Button, <input vs <Input, <select vs <Select

# Multiple button/tag/spacing patterns
# Search for: variant=, intent=, type= in component props — multiple values suggest drift

# Inline styles (always suspicious)
# Search for: style={{

# Hardcoded font-sizes
# Search for: text-[, fontSize:
```

## Example Finding

```
## 3. Spacing & Layout

| # | Location | Issue | Current | Expected | Severity |
|---|----------|-------|---------|----------|----------|
| 1 | src/components/ProfileCard.tsx:42 | Arbitrary padding on card content | `p-[18px]` | `p-4` (16px, closest token) | Minor |

**Why it matters:** The spacing scale exists to make the UI feel mathematically consistent.
18px feels subtly off compared to every other card using 16px. Users won't notice consciously,
but the overall impression is less polished.

**Fix:** `className="p-4"` instead of `className="p-[18px]"`
```

## Verification

After completing an audit, ensure:

- [ ] Discovered the project's actual design tokens and patterns
- [ ] Scanned for hardcoded colors, spacing, and font sizes
- [ ] Checked component consistency across the codebase
- [ ] Compared same patterns across different pages/routes
- [ ] Checked responsive breakpoint consistency
- [ ] Checked dark mode consistency (if applicable)
- [ ] Graded each finding with appropriate severity
- [ ] Provided exact fixes for critical and major findings
- [ ] Report follows the standard template
