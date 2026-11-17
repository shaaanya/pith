import js from "@eslint/js";
import globals from "globals";
import jsxA11y from "eslint-plugin-jsx-a11y";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "test-results", "playwright-report"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  jsxA11y.flatConfigs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
      // The page CSP forbids HTML sinks; keep them out of the source too.
      "no-restricted-syntax": [
        "error",
        { selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']", message: "No HTML sinks: build elements instead." },
        { selector: "MemberExpression[property.name=/^(innerHTML|outerHTML)$/]", message: "No HTML sinks: build elements instead." },
      ],
      "no-eval": "error",
      "no-new-func": "error",
    },
  },
  { files: ["e2e/**/*.mjs", "scripts/**/*.mjs", "*.config.{js,ts}"], languageOptions: { globals: globals.node } },
);
