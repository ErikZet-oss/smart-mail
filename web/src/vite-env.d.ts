/// <reference types="vite/client" />

/** package.json version, injected by vite.config.ts (footer of W1). */
declare const __APP_VERSION__: string;

interface ImportMetaEnv {
  /** Optional target of "Pomoc" on the login page. */
  readonly VITE_HELP_URL?: string;
}
