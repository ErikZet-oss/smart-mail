import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Config } from 'tailwindcss';

// Colours come only from the design tokens (CLAUDE.md §10): every `--<group>-<name>: #hex` variable of the light
// theme in src/styles/tokens.css becomes a Tailwind colour `<group>-<name>` that points to the CSS variable, so
// dark mode works by switching variables. Never add hex values here.
const tokensCss = readFileSync(fileURLToPath(new URL('./src/styles/tokens.css', import.meta.url)), 'utf8');
const rootBlock = tokensCss.slice(tokensCss.indexOf(':root'), tokensCss.indexOf('}'));
const colors: Record<string, string> = {};
for (const match of rootBlock.matchAll(/--([a-z0-9_-]+):\s*#[0-9a-fA-F]{3,8};/g)) {
  const name = match[1];
  if (name) colors[name] = `var(--${name})`;
}

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors,
      fontFamily: { ui: 'var(--font-ui)', mono: 'var(--font-mono)' },
    },
  },
  plugins: [],
} satisfies Config;
