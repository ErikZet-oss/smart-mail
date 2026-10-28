import { Component, type ErrorInfo, type ReactNode } from 'react';
import { withTranslation, type WithTranslation } from 'react-i18next';
import { RefreshCw, TriangleAlert } from 'lucide-react';

import { Button } from './Button';
import { StatusPage } from './StatusPage';

type Props = WithTranslation & { children: ReactNode };

type State = { error: Error | null };

/** Catches render crashes in the signed-in shell — never leave a blank dark page (pilot #18 B2). */
class ErrorBoundaryInner extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('shell.error_boundary', error, info.componentStack);
  }

  render() {
    const { t, children } = this.props;
    if (!this.state.error) return children;
    return (
      <StatusPage
        tone="danger"
        icon={<TriangleAlert size={44} strokeWidth={1.5} />}
        code={t('system.error.codeNoRef')}
        title={t('system.loadFailed.title')}
        text={t('system.loadFailed.text')}
        actions={
          <Button
            icon={<RefreshCw size={16} />}
            onClick={() => {
              this.setState({ error: null });
              window.location.reload();
            }}
          >
            {t('system.retry')}
          </Button>
        }
      />
    );
  }
}

export const ErrorBoundary = withTranslation()(ErrorBoundaryInner);
