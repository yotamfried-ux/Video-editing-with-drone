export function useScreenCapture(): void {
  // Documented web parity boundary (§17.4 #3): browsers cannot block OS screenshots.
  // Preview streams remain short, low-bitrate, and visibly watermarked.
}
