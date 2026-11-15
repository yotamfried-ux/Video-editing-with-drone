import { MD3DarkTheme, configureFonts, type MD3Theme } from 'react-native-paper';
import { Colors, Radius } from './theme';

// React Native Paper (Material Design 3) carries the brand tokens: the app keeps one palette and one
// typeface, and Paper's inputs, dialogs and feedback components inherit them.
const fonts = configureFonts({
  config: {
    fontFamily: 'PlusJakartaSans_400Regular',
  },
});

export const paperTheme: MD3Theme = {
  ...MD3DarkTheme,
  roundness: Radius.md,
  fonts,
  colors: {
    ...MD3DarkTheme.colors,
    primary: Colors.accent,
    onPrimary: Colors.background,
    primaryContainer: '#0B3B47',
    onPrimaryContainer: Colors.textPrimary,
    secondary: Colors.textSecondary,
    background: Colors.background,
    onBackground: Colors.textPrimary,
    surface: Colors.card,
    onSurface: Colors.textPrimary,
    surfaceVariant: Colors.card,
    onSurfaceVariant: Colors.textSecondary,
    outline: Colors.cardBorder,
    outlineVariant: Colors.cardBorder,
    error: Colors.danger,
    onError: Colors.textPrimary,
    elevation: {
      ...MD3DarkTheme.colors.elevation,
      level1: Colors.card,
      level2: Colors.card,
      level3: Colors.card,
    },
  },
};
