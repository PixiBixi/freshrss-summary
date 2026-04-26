# UI Redesign — FreshRSS Summary

**Date:** 2026-04-26
**Status:** Approved

---

## Overview

Redesign the FreshRSS Summary UI toward a minimal/editorial aesthetic while preserving all existing functionality. No backend changes required — CSS and JS only.

---

## Design Direction

**Minimal / Editorial**

- Background: `#ffffff` (pure white)
- Text: `#111111` (near-black), secondary `#6b7280`, muted `#9ca3af`
- Borders: `#e5e7eb` (light), separators `#f3f4f6` (very light)
- Font: keep Space Grotesk (already loaded)
- Typography: strong weight contrast — titles `font-weight: 800`, meta `font-weight: 400`
- Zero decorative shadows or gradients; structure conveyed through typography and thin lines

**Accent color**

- Default: teal `#5c98a0` (unchanged from current)
- User-configurable via a color picker in the ··· overflow menu
- Persisted in `localStorage` under key `freshrss-accent`
- Applied via a single CSS custom property `--accent` on `:root`

---

## Header

Two rows, sticky, white background with bottom border.

**Row 1 — identity + search + primary actions**

```
📡 FreshRSS   [🔍 Rechercher…        ⌘K]   [⟳ Refresh]   [···]
```

- Logo left, search bar flex-grows to fill space
- Search bar shows `⌘K` hint on the right edge (opens command palette, does not conflict with text input)
- Refresh button: primary accent color, always visible
- `···` button: opens a dropdown with secondary actions (see below)

**Row 2 — filters**

```
[Score ▾]  [Min: 1]  [7j ▾]  [⏪ Lu]          2h · 42 articles
```

- Sort select, min score input, period select, show-read toggle
- Last-refresh timestamp + article count pushed to the right
- Remove: compact toggle button, rescore button, scoring-cfg button, password button, lang dropdown — all moved to ··· menu or ⌘K

**··· overflow dropdown**

Actions accessible from the dropdown (mouse path):

| Action | Current location |
|--------|-----------------|
| ⊟ Mode compact | filter bar |
| ⇄ Re-scorer | filter bar |
| ⚙ Topics | filter bar |
| 🎨 Couleur d'accent… | new |
| 🌐 Langue | header |
| 🔑 Mot de passe | filter bar |
| Déconnexion | header |

---

## Command Palette (⌘K)

Triggered by `Cmd+K` (Mac) / `Ctrl+K` (Linux/Windows), or clicking the `⌘K` hint in the search bar.

Behavior:
- Overlay modal, centered, dark background (`#111`) with white text
- Text input at top filters the command list in real time
- Keyboard navigation: `↑`/`↓` to move, `Enter` to execute, `Esc` to close
- Commands:

| Command | Shortcut |
|---------|----------|
| ⟳ Rafraîchir les articles | R |
| ✓ Marquer les visibles comme lus | M |
| ⇄ Re-scorer | — |
| ⚙ Configurer les topics… | — |
| 🎨 Couleur d'accent… | — |
| 🌐 Langue… | — |
| 🔑 Changer le mot de passe… | — |
| Déconnexion | — |

The existing keyboard shortcuts (`j`/`k`, `o`, `m`, `r`, `Esc`) are preserved and listed in the palette as hints.

---

## Topic Pills

Unchanged visually, kept below the header filters row. Active pill uses `--accent` color.

---

## Article List

### Mode normal (default)

Two-line layout per article:

```
How Cilium replaced kube-proxy at scale              9↑
The New Stack · 2h · K8s · SRE
─────────────────────────────────────────────────────
ArgoCD 2.14 — new sync strategies                    7↑
CNCF Blog · 3h · GitOps
```

- Title: `font-size: 13px`, `font-weight: 600`, `color: #111`
- Meta line: `font-size: 11px`, `color: #9ca3af`
- Score: `font-weight: 700`, colored with `--accent` if high, `#9ca3af` if low
- Separator: `1px solid #f3f4f6`
- No card borders, no shadows — pure list

### Mode compact (⊟ toggle, moved to ···)

Single-line layout, expandable on click:

**Collapsed:**
```
9  How Cilium replaced kube-proxy at scale            2h ▼
7  ArgoCD 2.14 — new sync strategies                  3h ▼
```

**Expanded (click on row):**
```
9  How Cilium replaced kube-proxy at scale            2h ▲
   The New Stack · K8s · SRE
   [Ouvrir →]  [✓ Lu]  [☆]
```

- Left border accent `2px solid --accent` on expanded row
- Actions inline below title: open link, mark as read, bookmark
- Only one row expanded at a time (same behavior as current detail panel)

### Date group headers

```
AUJOURD'HUI                                    Tout lire
──────────────────────────────────────────────────────
```

- `font-size: 10px`, `font-weight: 800`, `letter-spacing: 0.08em`, `text-transform: uppercase`
- "Tout lire" link right-aligned, muted, appears on hover

---

## Color Picker

Simple implementation in the ··· dropdown:

- Native `<input type="color">` styled to match the UI
- On change: updates `--accent` on `:root`, saves to `localStorage`
- On load: reads from `localStorage`, falls back to `#5c98a0`
- A "Réinitialiser" link resets to default teal

---

## Files Changed

| File | Change |
|------|--------|
| `static/css/app.css` | Full rewrite of color variables, layout, typography |
| `static/js/ui.js` | Add `···` dropdown, command palette, color picker logic |
| `static/js/i18n.js` | Add keys for new palette commands |
| `templates/index.html` | Update header markup, add palette overlay, add ··· dropdown |

No changes to Python backend, API, or tests.

---

## Out of Scope

- Dark mode (not requested)
- Mobile responsiveness changes (current behavior preserved)
- Any backend or API changes
- Changes to the login page
