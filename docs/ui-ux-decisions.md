# Mobile UI/UX decisions

Source of the choices: the Engineering-OS knowledge library (`docs/ui-ux/README.md`, `EXPERIENCE-ROUTING.md`,
`MOTION-AND-INTERACTIONS.md`, `patterns/mobile/README.md`, `docs/product-experience/ui-library-candidates-2026.md`).

## Library choice (2026-11-15)

| Need | Chosen | Why | Not chosen |
|---|---|---|---|
| Accessible inputs, switches, progress, dialogs | **React Native Paper 5.15.4** (MIT, callstack/react-native-paper), listed in `patterns/mobile` | Pure JavaScript, no native code, themed from our tokens, labels and error text built in | NativeWind: a styling system, would mean rewriting every screen for no user-visible gain |
| Icons | **@expo/vector-icons 14** (MIT, ships with Expo SDK 53) | Replaces emoji used as icons (emoji differ per device and have no accessible name) | Lucide: listed for web; the RN port needs a second package for the same result |
| Motion and haptics | `Animated` from React Native and `expo-haptics`, both already installed | The motion playbook asks for feedback tied to a task and a reduced-motion variant; no extra runtime needed | Rive, Lottie: no state-machine animation is required yet |
| Vengeance UI, Animate UI, Uiverse, Forge UI, UI Lora | not used in the app | They are web libraries (React DOM, Tailwind, Radix). They cannot render in React Native. Two of them are marked "upstream not verified" in the library | — |

Cost: none. Rollback: `npm uninstall react-native-paper` and revert `FormField`, `paperTheme`, the reel screen
switch and spinner. Verification: type-check, jest, `expo export`, and the Android Maestro journeys in CI.

The existing tokens (`Colors`, `Spacing`, `Radius`, `Typography`) stay the single source of truth; Paper reads
them through `src/shared/constants/paperTheme.ts`.

## Principles applied, and where

| Principle (library section) | Change |
|---|---|
| Label every field; a placeholder is not a label (Forms) | `FormField`: floating label, hint under the field, show/hide password |
| Errors in context, next to the field (Error states) | Sign-in and sign-up errors are attached to the field they concern |
| Progress indicator for multi-step setup (Onboarding) | "Step 1 of 2" / "Step 2 of 2" on sign-up |
| Three kinds of empty: first-run, error, loading (Empty states) | Discover: skeleton while loading, a retry on failure, an explanation when there are no sessions |
| Touch targets of at least 44 pt (Accessibility, Fitts's law) | Back button on the reel screen is 44x44 with an accessible name |
| One primary action per screen; primary action in thumb reach (Mobile first) | Reel screen: one filled button (buy or download) in the bottom panel |
| Do not rely on colour alone (Accessibility) | Owned, preview and action states carry an icon and text |
| Truthful copy, no fake urgency (Conversion, content playbook) | The "sold" badge said "Purchased" to every viewer; it now says "Sold" |
| Feedback on press; respect reduced motion (Motion playbook) | Light haptic on primary and destructive buttons; the skeleton stays still with reduce-motion on |
| Safe areas (Quality gate) | Reel screen controls follow the device insets instead of fixed offsets, which Android 16 edge-to-edge requires |

## Not done in this pass

Operator screens, the checkout screen, RTL and Hebrew copy, dynamic type audit, a screen-reader pass on a device.
