import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';

import { useToast } from '../../components/toastContext';
import { fetchDraft, undoDraft, type ComposeDraft } from './composeApi';
import { sendErrorMessage } from './sendCopy';
import {
  dropWatch,
  getWatches,
  markAnnounced,
  replaceWatchDraft,
  useSendWatches,
  watchKey,
  type SendWatch,
} from './sendWatch';

const POLL_MS = 1000;
const CAP_MS = 60_000;
/** Sent row is written inside the send request; keep polling briefly if the id is not there yet. */
const SENT_LINK_WAIT_MS = 8_000;

type Navigator = { navigate: (to: string) => unknown };

function undoDurationMs(draft: ComposeDraft): number {
  if (!draft.undo_until) return 10_000;
  const left = new Date(draft.undo_until).getTime() - Date.now();
  if (Number.isNaN(left)) return 10_000;
  return Math.min(CAP_MS, Math.max(10_000, left + 500));
}

function openSent(router: Navigator, mailbox: string, draft: ComposeDraft): void {
  const ref = encodeURIComponent(draft.sent_folder_ref || 'sent');
  const mb = encodeURIComponent(mailbox);
  const thread = draft.sent_thread_id || draft.sent_message_id;
  if (draft.sent_message_id && thread) {
    void router.navigate(`/mail/${mb}/${ref}/${encodeURIComponent(thread)}`);
    return;
  }
  void router.navigate(`/mail/${mb}/${ref}`);
}

function composePath(watch: SendWatch): string {
  return `/compose/${watch.id}?mailbox=${encodeURIComponent(watch.mailbox)}`;
}

/**
 * Follows a send after W4/M4 closes. Toasts live in the app shell, so they survive navigation.
 * Polls the draft for at most 60 s (there is no mail WebSocket).
 */
export function SendTracker({ router }: { router: Navigator }) {
  const push = useToast();
  const { t } = useTranslation();
  const qc = useQueryClient();
  const watches = useSendWatches();
  const key = watchKey(watches);

  useEffect(() => {
    if (!key) return;
    let cancel = false;
    let running = false;
    const started = Date.now();

    const announceSending = (watch: SendWatch, draft: ComposeDraft) => {
      if (!markAnnounced(`${watch.id}:${watch.generation}:sending`)) return;
      push({
        kind: 'success',
        message: t('compose.sendingUndo'),
        durationMs: undoDurationMs(draft),
        action: {
          label: t('compose.undo'),
          onClick: () => {
            void undoDraft(watch.id)
              .then(() => {
                dropWatch(watch.id, watch.generation);
                push({ kind: 'success', message: t('compose.undone') });
                void router.navigate(composePath(watch));
              })
              .catch(() => {
                // The undo window already closed; the next poll reports sent or failed.
              });
          },
        },
      });
    };

    const finishSent = (watch: SendWatch, draft: ComposeDraft): boolean => {
      const appendFailed = (draft.send_error ?? '').split(':')[0] === 'append_failed';
      if (!appendFailed && !draft.sent_message_id && Date.now() - started < SENT_LINK_WAIT_MS) return false;
      const token = appendFailed ? 'append' : 'sent';
      if (markAnnounced(`${watch.id}:${watch.generation}:${token}`)) {
        if (appendFailed) {
          push({ kind: 'error', message: t('compose.sentNotStored') });
        } else {
          push({
            kind: 'success',
            message: t('compose.sent'),
            onActivate: () => openSent(router, watch.mailbox, draft),
          });
        }
      }
      dropWatch(watch.id, watch.generation);
      void qc.invalidateQueries({ queryKey: ['mail'] });
      return true;
    };

    const finishFailed = (watch: SendWatch, draft: ComposeDraft) => {
      const errorKey = `${watch.id}:${watch.generation}:failed:${draft.send_error ?? ''}`;
      if (markAnnounced(errorKey)) {
        push({
          kind: 'error',
          message: sendErrorMessage(t, draft.send_error),
          action: {
            label: t('compose.openDraft'),
            onClick: () => {
              void router.navigate(composePath(watch));
            },
          },
        });
      }
      dropWatch(watch.id, watch.generation);
    };

    const settle = async (watch: SendWatch) => {
      let draft = watch.draft;
      if (draft.status === 'queued' || draft.status === 'sending') {
        announceSending(watch, draft);
        try {
          draft = await fetchDraft(watch.id);
        } catch {
          return;
        }
        if (cancel) return;
        replaceWatchDraft(watch.id, watch.generation, draft);
        if (draft.status === 'queued' || draft.status === 'sending') return;
      }
      if (draft.status === 'editing' || draft.status === 'cancelled' || draft.status === 'scheduled') {
        dropWatch(watch.id, watch.generation);
        return;
      }
      if (draft.status === 'sent') {
        const appendFailed = (draft.send_error ?? '').split(':')[0] === 'append_failed';
        if (!appendFailed && !draft.sent_message_id && Date.now() - started < SENT_LINK_WAIT_MS) {
          try {
            const fresh = await fetchDraft(watch.id);
            if (!cancel) replaceWatchDraft(watch.id, watch.generation, fresh);
            if (fresh.sent_message_id || (fresh.send_error ?? '').split(':')[0] === 'append_failed') {
              finishSent(watch, fresh);
            }
          } catch {
            return;
          }
          return;
        }
        finishSent(watch, draft);
        return;
      }
      if (draft.status === 'failed') finishFailed(watch, draft);
    };

    const tick = async () => {
      if (cancel || running) return;
      if (Date.now() - started > CAP_MS) {
        for (const watch of getWatches()) dropWatch(watch.id, watch.generation);
        return;
      }
      running = true;
      try {
        for (const watch of getWatches()) {
          if (cancel) return;
          await settle(watch);
        }
      } finally {
        running = false;
      }
    };

    void tick();
    const timer = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancel = true;
      window.clearInterval(timer);
    };
  }, [key, push, qc, router, t]);

  return null;
}
