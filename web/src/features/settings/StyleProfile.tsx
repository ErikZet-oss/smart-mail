import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Sparkles } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { Button } from '../../components/Button';
import { Switch } from '../../components/Switch';
import { useToasts } from '../../components/toastContext';
import { ApiError } from '../../lib/api';
import { INPUT } from './adminUi';
import { fetchStyleProfile, generateStyleProfile, saveStyleProfile, styleProfileKey } from './settingsApi';

const KNOWN_ERRORS = new Set(['not_enough_mail', 'ai_unavailable', 'ai_budget_exceeded']);

/** W12-07 „Môj štýl písania“ (Phase 2e): opt-in per person, generate from own sent mail, edit, switch off = delete. */
export function StyleProfileSection({ disabled }: { disabled: boolean }) {
  const { t } = useTranslation();
  const toasts = useToasts();
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: styleProfileKey, queryFn: fetchStyleProfile });
  const [draft, setDraft] = useState<string | null>(null);
  const data = profile.data;
  const text = draft ?? data?.text ?? '';
  const done = (out: unknown) => {
    queryClient.setQueryData(styleProfileKey, out);
    setDraft(null);
  };
  const fail = (error: unknown) => {
    const code = error instanceof ApiError ? String(error.detail.code ?? '') : '';
    toasts.error(t(KNOWN_ERRORS.has(code) ? `ai.styleProfile.errors.${code}` : 'ai.styleProfile.errors.generic'));
  };

  const save = useMutation({
    mutationFn: (body: { opt_in: boolean; text: string }) => saveStyleProfile(body),
    onSuccess: (out) => {
      done(out);
      toasts.success(t('ai.styleProfile.saved'));
    },
    onError: fail,
  });
  const generate = useMutation({ mutationFn: generateStyleProfile, onSuccess: done, onError: fail });

  if (!data) return null;
  const busy = disabled || save.isPending || generate.isPending;
  return (
    <section className="mt-4 flex flex-col gap-2 border-t border-border-default pt-4" data-testid="style-profile">
      <h3 className="type-label text-text-primary">{t('ai.styleProfile.title')}</h3>
      <p className="type-small text-text-secondary">{t('ai.styleProfile.help')}</p>
      <Switch
        checked={data.opt_in}
        disabled={busy}
        onChange={(opt_in) => save.mutate({ opt_in, text: opt_in ? text : '' })}
        label={t('ai.styleProfile.optIn')}
      />
      {data.opt_in ? (
        <>
          <Button
            type="button"
            variant="secondary"
            className="self-start"
            icon={<Sparkles size={16} aria-hidden="true" />}
            disabled={busy}
            onClick={() => generate.mutate()}
          >
            {t(data.text ? 'ai.styleProfile.regenerate' : 'ai.styleProfile.generate')}
          </Button>
          {data.text || draft !== null ? (
            <label className="flex flex-col gap-1">
              <span className="type-label text-text-secondary">{t('ai.styleProfile.label')}</span>
              <textarea
                value={text}
                onChange={(e) => setDraft(e.target.value)}
                rows={6}
                maxLength={1500}
                className={`${INPUT} h-auto py-2`}
              />
            </label>
          ) : null}
          {data.source_count > 0 ? (
            <p className="type-caption text-text-secondary">
              {t('ai.styleProfile.from', { count: data.source_count })}
            </p>
          ) : null}
          {draft !== null ? (
            <Button
              type="button"
              className="self-start"
              disabled={busy}
              onClick={() => save.mutate({ opt_in: true, text })}
            >
              {t('ai.styleProfile.save')}
            </Button>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
