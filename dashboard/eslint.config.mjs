import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "dist/**",
    ".sites-runtime/**",
    ".wrangler/**",
    "next-env.d.ts",
  ]),
  {
    files: ["components/ui/**/*.{ts,tsx}", "hooks/use-mobile.ts"],
    rules: {
      // These files are vendored verbatim from shadcn@4.17.0. Keep the
      // registry source intact while applying the stricter rules to app code.
      "@typescript-eslint/no-unused-vars": "off",
      "react-hooks/purity": "off",
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["components/traffic-dashboard.tsx"],
    rules: {
      // This dashboard uses effects to synchronize camera selection, polling,
      // and request loading state. These transitions intentionally update state.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    files: ["components/camera-monitor.tsx"],
    rules: {
      // Protected camera frames must bypass the public Next.js image optimizer.
      "@next/next/no-img-element": "off",
    },
  },
  {
    files: ["components/sign-in-form.tsx", "components/traffic-dashboard.tsx", "lib/api.ts"],
    rules: {
      // Full navigation at authentication boundaries discards cached server
      // payloads and the previous authenticated dashboard's client state.
      "@next/next/no-location-assign-relative-destination": "off",
    },
  },
]);

export default eslintConfig;
