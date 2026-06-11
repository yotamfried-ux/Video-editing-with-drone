/**
 * Custom entry point: install the JS crash reporter BEFORE anything else is
 * imported. Uses require() (not import) because ES imports are hoisted and
 * would evaluate expo-router/entry before the reporter is installed — too
 * late to catch import-time crashes.
 */
const { installJsCrashReporter } = require('./src/shared/lib/crashReporter');

installJsCrashReporter();

require('expo-router/entry');
