import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { registerSW } from 'virtual:pwa-register';

import './i18n';
import './styles/index.css';
import { App } from './app/App';

registerSW({ immediate: true });

const root = document.getElementById('root');
if (!root) throw new Error('#root missing in index.html');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
