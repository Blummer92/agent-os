/**
 * Minimal `react-native` stub for the Vitest fixture suite.
 *
 * The real `react-native` package entry uses Flow type syntax
 * (`import typeof ...`) that Vitest's esbuild transform cannot parse.
 * This stub provides the small surface the fixture's mobile reference
 * actually uses, rendering host elements that
 * `@testing-library/react-native` can query.
 *
 * Plain JavaScript (no TypeScript syntax): Node's native loader may
 * `require` this file directly via the setup-file resolution redirect.
 *
 * Fixture-scoped: only used by the ui-cross-platform-reference tests.
 */
const React = require("react");

function hostComponent(name, defaultProps) {
  const Host = (props) =>
    React.createElement(name, { ...defaultProps, ...props });
  Host.displayName = name;
  return Host;
}

const View = hostComponent("View");
const Text = hostComponent("Text");
const TextInput = hostComponent("TextInput");
// Pressable is accessible by default in React Native; RNTL's
// `isAccessibilityElement` requires the `accessible` prop to be set.
const Pressable = hostComponent("Pressable", { accessible: true });
const SafeAreaView = hostComponent("SafeAreaView");

const StyleSheet = {
  create: (styles) => styles,
  flatten: (style) => {
    if (Array.isArray(style)) {
      return Object.assign({}, ...style.filter(Boolean));
    }
    return style ?? {};
  },
};

function useWindowDimensions() {
  return { width: 390, height: 844, scale: 2, fontScale: 2 };
}

module.exports = {
  View,
  Text,
  TextInput,
  Pressable,
  SafeAreaView,
  StyleSheet,
  useWindowDimensions,
};
