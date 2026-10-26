import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';

import sk from './sk.json';

// All user-facing text is Slovak and lives in sk.json (CLAUDE.md §0). No other language is supported.
void i18n.use(initReactI18next).init({
  resources: { sk: { translation: sk } },
  lng: 'sk',
  fallbackLng: 'sk',
  interpolation: { escapeValue: false },
  returnNull: false,
});

export default i18n;
