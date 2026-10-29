import { useQueryClient } from '@tanstack/react-query';
import { ArrowUp, CircleX, Clock, Eye, EyeOff, KeyRound, LoaderCircle, Lock, User } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Checkbox } from '../../components/Checkbox';
import { LoginField } from '../../components/LoginField';
import { Logo } from '../../components/Logo';
import { ApiError } from '../../lib/api';
import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { login, rememberAfterLogin, returnTo, SHARED_DEVICE_KEY } from './authApi';

type Failure =
  { kind: 'invalid' } | { kind: 'server' } | { kind: 'rate'; minutes: number; until: number } | { kind: 'generic' };

type Reason = 'password-changed' | 'expired' | 'mfa-locked';
const REASONS: readonly Reason[] = ['password-changed', 'expired', 'mfa-locked'];

function toFailure(error: unknown): Failure {
  if (!(error instanceof ApiError)) return { kind: 'server' }; // network error: the server is not reachable
  if (error.detail.code === 'invalid_credentials') return { kind: 'invalid' };
  if (error.detail.code === 'mail_server_unavailable') return { kind: 'server' };
  if (error.detail.code === 'rate_limited') {
    const seconds = Number(error.detail.retry_after) || 300;
    return { kind: 'rate', minutes: Math.max(1, Math.ceil(seconds / 60)), until: Date.now() + seconds * 1000 };
  }
  return { kind: 'generic' };
}

/** Banner of W1c (password changed / session expired) and the 2FA lock-out. */
function ReasonBanner({ reason }: { reason: Reason }) {
  const { t } = useTranslation();
  const danger = reason !== 'expired';
  const Icon = reason === 'expired' ? Clock : KeyRound;
  const text = {
    'password-changed': t('login.reason.passwordChanged'),
    expired: t('login.reason.expired'),
    'mfa-locked': t('login.reason.mfaLocked'),
  }[reason];
  return (
    <div
      role={danger ? 'alert' : 'status'}
      className={`type-small flex w-full items-start gap-2 rounded-sm border-l-[3px] px-3 py-2.5 text-left ${
        danger
          ? 'border-danger-600 bg-danger-50 text-danger-600'
          : 'border-brand-primary-600 bg-brand-primary-50 text-brand-primary-700'
      }`}
    >
      <Icon size={16} aria-hidden="true" className="mt-px shrink-0" />
      <span>{text}</span>
    </div>
  );
}

export function ScreenW1() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const reasonParam = params.get('reason');
  const reason = REASONS.find((r) => r === reasonParam);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(() => localStorage.getItem(SHARED_DEVICE_KEY) === '1');
  const [capsLock, setCapsLock] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  useEffect(() => emailRef.current?.focus(), []);
  useEffect(() => {
    if (failure) passwordRef.current?.focus();
  }, [failure]);

  const rateUntil = failure?.kind === 'rate' ? failure.until : 0;
  useEffect(() => {
    if (!rateUntil) return;
    const timer = window.setTimeout(() => setFailure(null), Math.max(0, rateUntil - Date.now()));
    return () => window.clearTimeout(timer);
  }, [rateUntil]);

  const onKey = (event: KeyboardEvent<HTMLInputElement>) => setCapsLock(event.getModifierState('CapsLock'));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting || failure?.kind === 'rate' || !email.trim() || !password) return;
    setSubmitting(true);
    setFailure(null);
    try {
      const result = await login(email.trim(), password, remember);
      queryClient.clear();
      rememberAfterLogin(result.me);
      const from = returnTo(location.state);
      if (result.next === '2fa') navigate('/login/2fa', { replace: true, state: { from, remember } });
      else if (result.next === '2fa-setup') navigate('/login/2fa?setup=1', { replace: true });
      else if (result.next === 'who') navigate('/who', { replace: true, state: { from } });
      else navigate(from, { replace: true });
    } catch (error) {
      setFailure(toFailure(error));
      setSubmitting(false);
    }
  }

  const failureText =
    failure &&
    {
      invalid: t('login.errors.invalidCredentials'),
      server: t('login.errors.serverUnavailable'),
      rate: t('login.errors.rateLimited', { count: failure.kind === 'rate' ? failure.minutes : 5 }),
      generic: t('login.errors.generic'),
    }[failure.kind];
  const invalid = failure !== null;
  const locked = failure?.kind === 'rate';
  // M-W1 (Figma): the checkbox sits above the button on phones; desktop W1 has it below like Roundcube
  const mobile = useMediaQuery(MOBILE_QUERY);
  const rememberBox = (
    <Checkbox
      className="w-full"
      label={t('login.remember')}
      checked={remember}
      onChange={(e) => setRemember(e.target.checked)}
      disabled={submitting}
    />
  );

  return (
    <main className="flex min-h-full flex-col items-center bg-bg-canvas px-6 pb-10 pt-12 sm:justify-center sm:px-4 sm:pt-10">
      <form
        onSubmit={submit}
        noValidate
        className="flex w-full flex-col items-center gap-3.5 sm:max-w-[300px] sm:gap-3"
      >
        <h1 className="sr-only">{t('login.title')}</h1>
        <div className="flex flex-col items-center gap-5 pb-2.5 sm:pb-8">
          <Logo width={180} className="w-[160px] sm:w-[180px]" />
          <p className="type-body text-center text-text-secondary sm:hidden">{t('login.subtitleMobile')}</p>
        </div>
        {reason && !failure ? <ReasonBanner reason={reason} /> : null}
        {failureText ? (
          <div
            role="alert"
            className="type-small flex w-full items-center gap-2.5 border-l-[3px] border-danger-600 bg-danger-50 px-4 py-2.5 text-left text-danger-600 sm:items-start sm:gap-2 sm:rounded-sm sm:border-l-0 sm:px-2.5 sm:py-2"
          >
            <CircleX aria-hidden="true" className="size-[18px] shrink-0 sm:mt-px sm:size-4" />
            <span>{failureText}</span>
          </div>
        ) : null}
        <LoginField
          ref={emailRef}
          icon={<User size={16} />}
          type="email"
          name="email"
          inputMode="email"
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          placeholder={t('login.email')}
          aria-label={t('login.email')}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          onKeyUp={onKey}
          invalid={invalid}
          disabled={submitting}
          required
        />
        <LoginField
          ref={passwordRef}
          icon={<Lock size={16} />}
          type={showPassword ? 'text' : 'password'}
          name="password"
          autoComplete="current-password"
          placeholder={t('login.password')}
          aria-label={t('login.password')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyUp={onKey}
          onKeyDown={onKey}
          invalid={invalid}
          disabled={submitting}
          required
          trailing={
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              disabled={submitting}
              aria-label={showPassword ? t('login.hidePassword') : t('login.showPassword')}
              aria-pressed={showPassword}
              className="hidden w-9 shrink-0 items-center sm:flex justify-center text-text-tertiary hover:text-text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand-primary-500"
            >
              {showPassword ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
            </button>
          }
        />
        {capsLock ? (
          <p role="status" className="type-caption -mt-1 flex w-full items-center gap-1 text-warning-700">
            <ArrowUp size={14} aria-hidden="true" />
            {t('login.capsLock')}
          </p>
        ) : null}
        {mobile ? rememberBox : null}
        <Button
          type="submit"
          size="lg"
          className="w-full"
          disabled={submitting || locked}
          aria-busy={submitting || undefined}
          icon={submitting ? <LoaderCircle size={18} className="animate-spin" aria-hidden="true" /> : undefined}
        >
          {submitting ? t('login.submitting') : t('login.submit')}
        </Button>
        {mobile ? null : rememberBox}
        <div aria-hidden="true" className="hidden h-4 sm:block" />
        <Footer className="hidden sm:block" />
      </form>
    </main>
  );
}

export function Footer({ className = '' }: { className?: string }) {
  const { t } = useTranslation();
  const helpUrl = import.meta.env.VITE_HELP_URL as string | undefined;
  return (
    <p className={`type-caption text-text-tertiary ${className}`}>
      {t('app.footer', { version: __APP_VERSION__ })} ·{' '}
      {helpUrl ? (
        <a href={helpUrl} className="underline-offset-2 hover:underline" target="_blank" rel="noreferrer">
          {t('app.help')}
        </a>
      ) : (
        t('app.help')
      )}
    </p>
  );
}
