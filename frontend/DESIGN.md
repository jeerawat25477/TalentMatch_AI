---
name: Luminous HR
colors:
  surface: '#f8f9ff'
  surface-dim: '#cbdbf5'
  surface-bright: '#f8f9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#eff4ff'
  surface-container: '#e5eeff'
  surface-container-high: '#dce9ff'
  surface-container-highest: '#d3e4fe'
  on-surface: '#0b1c30'
  on-surface-variant: '#424754'
  inverse-surface: '#213145'
  inverse-on-surface: '#eaf1ff'
  outline: '#727785'
  outline-variant: '#c2c6d6'
  surface-tint: '#005ac2'
  primary: '#0058be'
  on-primary: '#ffffff'
  primary-container: '#2170e4'
  on-primary-container: '#fefcff'
  inverse-primary: '#adc6ff'
  secondary: '#006c49'
  on-secondary: '#ffffff'
  secondary-container: '#6cf8bb'
  on-secondary-container: '#00714d'
  tertiary: '#825100'
  on-tertiary: '#ffffff'
  tertiary-container: '#a36700'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d8e2ff'
  primary-fixed-dim: '#adc6ff'
  on-primary-fixed: '#001a42'
  on-primary-fixed-variant: '#004395'
  secondary-fixed: '#6ffbbe'
  secondary-fixed-dim: '#4edea3'
  on-secondary-fixed: '#002113'
  on-secondary-fixed-variant: '#005236'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#ffb95f'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#f8f9ff'
  on-background: '#0b1c30'
  surface-variant: '#d3e4fe'
colors-dark:
  surface: '#0d1526'
  surface-dim: '#0a1120'
  surface-bright: '#22304a'
  surface-container-lowest: '#080e1a'
  surface-container-low: '#141d2e'
  surface-container: '#182238'
  surface-container-high: '#222d45'
  surface-container-highest: '#2c3852'
  surface-variant: '#414859'
  surface-tint: '#adc6ff'
  on-surface: '#e3e9f5'
  on-surface-variant: '#c2c7d6'
  inverse-surface: '#e3e9f5'
  inverse-on-surface: '#0b1c30'
  outline: '#8c92a3'
  outline-variant: '#424859'
  primary: '#adc6ff'
  on-primary: '#002e69'
  primary-container: '#00458f'
  on-primary-container: '#d8e2ff'
  inverse-primary: '#0058be'
  secondary: '#4edea3'
  on-secondary: '#003825'
  secondary-container: '#005236'
  on-secondary-container: '#6ffbbe'
  tertiary: '#ffb95f'
  on-tertiary: '#452b00'
  tertiary-container: '#653e00'
  on-tertiary-container: '#ffddb8'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  background: '#0d1526'
  on-background: '#e3e9f5'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-md:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '500'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  base: 4px
  xs: 8px
  sm: 16px
  md: 24px
  lg: 40px
  xl: 64px
  gutter: 24px
  margin-mobile: 16px
  margin-desktop: 48px
---

## Brand & Style
The design system is centered on the intersection of professional stability and AI-driven innovation. It utilizes a **Glassmorphism** aesthetic to evoke a sense of transparency, light, and modern fluid intelligence. The target audience—HR professionals and modern employees—should feel that the platform is both technically advanced and approachable. 

The visual style relies on multi-layered depth, using frosted glass effects to signify different functional modules without creating heavy visual silos. High-quality whitespace and subtle background blurs maintain a "clean-room" feel, ensuring that data-heavy HR tasks remain legible and stress-free.

## Colors
The palette uses a "Trustworthy Blue" as the anchor to maintain professional credibility. Semantic colors (Emerald, Amber, Rose) are tuned for high accessibility against semi-transparent surfaces. 

The background is a soft, fixed linear gradient that provides the necessary chromatic depth for the glass layers to "pick up" via backdrop blurs. All primary actions utilize the core blue, while secondary surfaces use reduced opacity versions of the neutral slate to maintain the ethereal, light-filled aesthetic.

## Typography
This design system utilizes **Inter** exclusively to lean into its systematic, utilitarian nature, which balances the expressive "glass" UI. 

Headlines use tighter letter spacing and heavier weights to provide a strong structural anchor. Body text is optimized for long-form HR documentation with generous line heights. For mobile, headline sizes scale down aggressively to ensure that data visualizations and glass cards have sufficient breathing room on narrow viewports.

## Layout & Spacing
The system employs a **Fluid Grid** model. On desktop, a 12-column grid is used with 24px gutters to accommodate complex dashboard layouts. On mobile, this collapses to a 4-column grid with 16px margins.

Spacing is governed by a 4px base unit. Glass cards should have consistent internal padding (usually 24px) to ensure content doesn't feel cramped against the rounded edges. Grouped elements use `xs` (8px) spacing, while distinct sections within a page use `lg` (40px) to maintain the airy, "high-tech" feel.

## Elevation & Depth
Depth is created through **Glassmorphism** rather than traditional opaque shadows. 
- **Surface Level 0:** The soft background gradient.
- **Surface Level 1 (Default Card):** Background: `rgba(255, 255, 255, 0.6)`. Backdrop Blur: `12px`. Border: `1px solid rgba(255, 255, 255, 0.4)`.
- **Surface Level 2 (Floating/Modals):** Background: `rgba(255, 255, 255, 0.8)`. Backdrop Blur: `20px`. Shadow: `0 20px 25px -5px rgba(0, 0, 0, 0.05)`.

The use of a subtle white inner-stroke (border) on cards is critical to simulate light hitting the edge of the glass, separating the element from the background.

### Dark Mode
The palette above has a dark counterpart (`colors-dark`) in the same Navy family, so the "Trustworthy Blue" brand character survives the switch. Every token is exposed as a CSS variable in `app/globals.css` (`:root` = light, `.dark` = dark) and consumed through Tailwind — never hardcode a hex in a component.

Two rules govern the dark surfaces:
- **Glass must be more opaque in the dark.** Surface Level 1 becomes `rgba(30, 45, 72, 0.55)` and Level 2 `rgba(34, 50, 80, 0.75)`. A dark glass as transparent as the light one lets the background gradient bleed through and text loses contrast.
- **The inner-stroke inverts its job.** Instead of white light hitting the edge, the border is a low-opacity primary (`rgba(173, 198, 255, 0.12)`) that reads as a rim highlight against the darker page.

The `*-fixed` token family (`primary-fixed`, `on-primary-fixed-variant`, `secondary-fixed`, `tertiary-fixed`, …) is deliberately **identical in both themes**, per the Material 3 spec. Tonal buttons and skill chips are built from these pairs, so their contrast is guaranteed without a dark-mode override.

Background blobs drop to roughly half their opacity in the dark, and the radar chart swaps its series colors to the light pair (`#adc6ff` / `#ffb95f`) — the original dark blue and amber disappear against a dark surface. The swapped pair keeps the same CVD separation as the original.

## Shapes
To complement the glass aesthetic, the design system uses significant rounding. Main containers and cards use a **2xl** (1.5rem / 24px) corner radius. This softness reduces the "industrial" feel of HR software, making the AI interactions feel more organic and less rigid. 

Buttons and input fields follow a standard **lg** (0.5rem / 8px) radius to maintain a sense of functional precision within the softer container environment.

## Components

### Buttons
Primary buttons are solid Trustworthy Blue with a subtle glow (soft outer shadow of the same color). Secondary buttons use the glass style: a semi-transparent white fill with a 1px border.

### Cards
All cards must implement `backdrop-filter: blur()`. Header sections within cards should be separated by a very faint horizontal line (`rgba(0,0,0,0.05)`) rather than a heavy border.

### Input Fields
Inputs should be semi-transparent with a 1px border that brightens on focus. Use a light background fill (`rgba(255,255,255,0.5)`) to ensure the text cursor and typed content are clearly visible.

### Chips & Badges
Chips for status (e.g., "Active", "Pending") should use low-opacity versions of the semantic colors (Success, Warning, Danger) with high-saturation text to ensure readability against glass backgrounds.

### AI Insights Module
A signature component for this design system: a card with a slightly more vibrant backdrop blur and a thin, multi-color gradient border to signify "active AI processing" or "smart suggestions."