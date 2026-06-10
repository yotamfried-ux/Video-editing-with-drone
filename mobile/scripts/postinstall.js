#!/usr/bin/env node
// Patches node_modules packages that ship TypeScript/ESM source as their
// "main" entry — which breaks Node.js when running expo config or EAS CLI.
const fs = require('fs');
const path = require('path');

// 1. expo-modules-core: "main" points to src/index.ts → redirect to index.js
(function patchExpoModulesCore() {
  const pkgPath = path.join('node_modules', 'expo-modules-core', 'package.json');
  try {
    const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf8'));
    if (pkg.main === 'src/index.ts') {
      pkg.main = 'index.js';
      fs.writeFileSync(pkgPath, JSON.stringify(pkg, null, 2));
      console.log('postinstall: patched expo-modules-core main → index.js');
    }
  } catch (_) {}
})();

// 2. expo-screen-capture: no app.plugin.js, main is ESM → create a CJS no-op plugin
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
