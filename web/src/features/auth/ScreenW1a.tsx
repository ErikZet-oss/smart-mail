import { useQueryClient } from '@tanstack/react-query';
import { KeyRound, LoaderCircle } from 'lucide-react';
import { useEffect, useRef, useState, type ClipboardEvent, type FormEvent, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';

import { Button } from '../../components/Button';
import { Checkbox } from '../../components/Checkbox';
import { LoginField } from '../../components/LoginField';
import { Logo } from '../../components/Logo';
import { ApiError } from '../../lib/api';
import { rememberAfterLogin, returnTo, verifyMfa } from './authApi';
import { MfaSetup } from './MfaSetup';

const DIGITS = 6;
const empty = () => Array.from({ length: DIGITS }, () => '');

export function ScreenW1a() {
  const location = useLocation();
  if (new URLSearchParams(location.search).get('setup') === '1') return <MfaSetup />;
  return <MfaVerify />;
}

function MfaVerify() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const state = location.state as { from?: string; remember?: boolean } | null;

  const [digits, setDigits] = useState<string[]>(empty);
  const [backupMode, setBackupMode] = useState(false);
  const [backupCode, setBackupCode] = useState('');
  const [rememberDevice, setRememberDevice] = useState(Boolean(state?.remember));
  const [attemptsLeft, setAttemptsLeft] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const backupRef = useRef<HTMLInputElement>(null);

  // also after a wrong code: the inputs are enabled again only after this render
  useEffect(() => {
    if (backupMode) backupRef.current?.focus();
    else boxes.current[0]?.focus();
  }, [backupMode, attemptsLeft]);

  const code = backupMode ? backupCode.trim() : digits.join('');
  const complete = backupMode ? code.length >= 8 : code.length === DIGITS;

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (submitting) return;
    if (!complete) {
      (backupMode ? backupRef.current : boxes.current[digits.findIndex((d) => !d)])?.focus();
      return;
    }
    setSubmitting(true);
    try {
      const result = await verifyMfa(code, rememberDevice);
      queryClient.clear();
      rememberAfterLogin(result.me);
      const from = returnTo(state);
      navigate(result.next === 'who' ? '/who' : from, { replace: true, state: { from } });
    } catch (error) {
      setSubmitting(false);
      const detail = error instanceof ApiError ? error.detail : null;
      if (detail?.code === 'invalid_code') {
        setAttemptsLeft(Number(detail.attempts_left) || 0);
        setDigits(empty());
        setBackupCode('');
        return;
      }
      // locked out, or the pending login expired: start again on W1
      navigate('/login?reason=mfa-locked', { replace: true, state: { from: returnTo(state) } });
    }
  }

  function setDigit(index: number, value: string) {
    const clean = value.replace(/\D/g, '');
    if (clean.length > 1) {
      fill(clean, index);
      return;
    }
    const next = [...digits];
    next[index] = clean;
    setDigits(next);
    if (clean && index < DIGITS - 1) boxes.current[index + 1]?.focus();
  }

  function fill(text: string, start = 0) {
    const clean = text.replace(/\D/g, '').slice(0, DIGITS - start);
    if (!clean) return;
    const next = [...digits];
    [...clean].forEach((d, i) => (next[start + i] = d));
    setDigits(next);
    boxes.current[Math.min(start + clean.length, DIGITS - 1)]?.focus();
  }

  function onKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Backspace' && !digits[index] && index > 0) {
      boxes.current[index - 1]?.focus();
      const next = [...digits];
      next[index - 1] = '';
      setDigits(next);
      event.preventDefault();
    } else if (event.key === 'ArrowLeft' && index > 0) boxes.current[index - 1]?.focus();
    else if (event.key === 'ArrowRight' && index < DIGITS - 1) boxes.current[index + 1]?.focus();
  }

  function onPaste(index: number, event: ClipboardEvent<HTMLInputElement>) {
    event.preventDefault();
    fill(event.clipboardData.getData('text'), index);
  }

  const error = attemptsLeft !== null;
  return (
    <main className="flex min-h-full flex-col items-center justify-center bg-bg-canvas px-4 py-10">
      <form onSubmit={submit} noValidate className="flex w-full max-w-[340px] flex-col items-center gap-3.5">
        <Logo width={120} />
        <div aria-hidden="true" className="h-2" />
        <h1 className="type-title text-text-primary">{t('mfa.title')}</h1>
        <p className="type-small text-center text-text-secondary" id="mfa-help">
          {backupMode ? t('mfa.subtitleBackup') : t('mfa.subtitle')}
        </p>
        {backupMode ? (
          <LoginField
            ref={backupRef}
            icon={<KeyRound size={16} />}
            autoComplete="one-time-code"
            autoCapitalize="none"
            spellCheck={false}
            placeholder={t('mfa.backupCode')}
            aria-label={t('mfa.backupCode')}
            aria-describedby="mfa-help"
            value={backupCode}
            onChange={(e) => setBackupCode(e.target.value)}
            invalid={error}
            disabled={submitting}
          />
        ) : (
          <div className="flex gap-2" role="group" aria-describedby="mfa-help">
            {digits.map((digit, i) => (
              <input
                key={i}
                ref={(el) => {
                  boxes.current[i] = el;
                }}
                value={digit}
                onChange={(e) => setDigit(i, e.target.value)}
                onKeyDown={(e) => onKeyDown(i, e)}
                onPaste={(e) => onPaste(i, e)}
                onFocus={(e) => e.target.select()}
                inputMode="numeric"
                autoComplete={i === 0 ? 'one-time-code' : 'off'}
                maxLength={DIGITS}
                aria-label={t('mfa.digit', { n: i + 1 })}
                aria-invalid={error || undefined}
                disabled={submitting}
                className={`type-title h-[52px] w-11 rounded-md border bg-bg-canvas text-center text-text-primary outline-none focus:border-2 focus:border-brand-primary-500 disabled:bg-bg-subtle disabled:opacity-60 ${
                  error ? 'border-danger-600' : 'border-border-strong'
                }`}
              />
            ))}
          </div>
        )}
        {error ? (
          <p role="alert" className="type-small text-danger-600">
            {t('mfa.errors.invalidCode', { count: attemptsLeft })}
          </p>
        ) : null}
        <Checkbox
          label={t('mfa.rememberDevice')}
          checked={rememberDevice}
          onChange={(e) => setRememberDevice(e.target.checked)}
          disabled={submitting}
        />
        <Button
          type="submit"
          size="lg"
          className="w-full"
          disabled={submitting}
          icon={submitting ? <LoaderCircle size={18} className="animate-spin" aria-hidden="true" /> : undefined}
        >
          {submitting ? t('mfa.submitting') : t('mfa.submit')}
        </Button>
        <button
          type="button"
          className="type-label rounded-xs text-brand-primary-600 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-primary-500"
          onClick={() => {
            setBackupMode((v) => !v);
            setAttemptsLeft(null);
          }}
        >
          {backupMode ? t('mfa.useApp') : t('mfa.useBackup')}
        </button>
      </form>
    </main>
  );
}
