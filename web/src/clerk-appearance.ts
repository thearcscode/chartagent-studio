import type { ClerkProvider } from "@clerk/react";
import type { ComponentProps } from "react";

type Appearance = NonNullable<ComponentProps<typeof ClerkProvider>["appearance"]>;

/**
 * Clerk's prebuilt components, restyled against the vendored tokens. Auth
 * chrome is not the product surface, so the no-component-library rule does
 * not reach it — but the palette is still ours. The primary button is ink on
 * background, matching the sign-in button in design/Chartagent Landing.
 */
export const clerkAppearance: Appearance = {
  variables: {
    colorBackground: "var(--panel)",
    colorForeground: "var(--ink)",
    colorMutedForeground: "var(--muted)",
    colorPrimary: "var(--ink)",
    colorPrimaryForeground: "var(--bg)",
    colorInput: "var(--raised)",
    colorInputForeground: "var(--ink)",
    colorBorder: "var(--border)",
    colorDanger: "var(--red)",
    colorNeutral: "var(--ink)",
    // tokens.css carries no radius or font tokens; these two literals mirror
    // the type and radius the design README specifies.
    borderRadius: "8px",
    fontFamily: "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif",
    fontFamilyButtons: "'IBM Plex Sans', ui-sans-serif, system-ui, sans-serif",
  },
  elements: {
    card: {
      backgroundColor: "var(--panel)",
      border: "1px solid var(--border)",
      boxShadow: "none",
    },
    footer: {
      background: "transparent",
    },
  },
};
