#!/usr/bin/env node
// Patches node_modules packages that ship TypeScript/ESM source as their
// "main" entry — which breaks Node.js when running expo config or EAS CLI.
const fs = require('fs');
const path = require('path');

// NOTE: do NOT patch expo-modules-core's "main" field. It intentionally points
// to src/index.ts (Metro compiles TS); its index.js is a `module.exports = null`
// stub for Node-only contexts. Redirecting main to index.js makes Metro bundle
// `null` as the entire library → "Cannot read property 'requireOptionalNativeModule'
// of null" crash at app startup. (This was the "SportReel keeps stopping" bug.)

// expo-screen-capture: no app.plugin.js, main is ESM → create a CJS no-op plugin
(function patchExpoScreenCapture() {
  const pluginPath = path.join('node_modules', 'expo-screen-capture', 'app.plugin.js');
  if (!fs.existsSync(pluginPath)) {
    fs.writeFileSync(
      pluginPath,
      // expo-screen-capture relies entirely on expo-module.config.json auto-linking;
      // the config plugin has nothing to add, so return config unchanged.
      `const { createRunOncePlugin } = require('@expo/config-plugins');
module.exports = createRunOncePlugin((config) => config, 'expo-screen-capture', '1.0.0');
`
    );
    console.log('postinstall: created expo-screen-capture/app.plugin.js (no-op CJS)');
  }
})();
