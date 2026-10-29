import { Flag, Forward, Paperclip, Reply, Sparkles } from 'lucide-react';
import { useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { Checkbox } from '../../components/Checkbox';
import { categoryDotClass } from './categoryStyles';
import { endMessageDrag } from './dragMessages';
import { formatMailDate } from './formatMailDate';
import type { MessageListItem, ThreadListItem } from './mailApi';

export type RowItem = { kind: 'message'; data: MessageListItem } | { kind: 'thread'; data: ThreadListItem };

type Props = {
  item: RowItem;
  selected: boolean;
  checked: boolean;
  showCheckbox: boolean;
  density: 'compact' | 'comfortable';
  classic: boolean;
  showAiSummary?: boolean;
  categoryColorToken?: string | null;
  onSelect: () => void;
  onCheck: (checked: boolean) => void;
  /** M1 long-press → multi-select (optional). */
  onLongPress?: () => void;
  /** Desktop drag to a folder (#96); absent = not draggable. */
  onDragStart?: (dt: DataTransfer) => void;
};

function senderLabel(name: string | null, email: string | null): string {
  return name || email || '—';
}

/** Compact 52 px Roundcube two-line row; comfortable adds preview (UX_SPEC MessageRow). */
export function MessageRow({
  item,
  selected,
  checked,
  showCheckbox,
  density,
  classic,
  showAiSummary = false,
  categoryColorToken = null,
  onSelect,
  onCheck,
  onLongPress,
  onDragStart,
}: Props) {
  const { t } = useTranslation();
  const pressTimer = useRef<number | null>(null);
  const longPressed = useRef(false);
  const [dragging, setDragging] = useState(false);
  const unread = item.kind === 'message' ? !item.data.seen : item.data.unread_count > 0;
  const subject = item.data.subject || t('mail.noSubject');
  const date = formatMailDate(item.kind === 'message' ? item.data.received_at : item.data.last_message_at);
  const preview = item.data.preview;
  const answered = item.kind === 'message' ? item.data.answered : false;
  const forwarded = item.kind === 'message' ? Boolean(item.data.forwarded) : false;
  const threadCount = item.kind === 'message' ? item.data.thread_count : item.data.message_count;
  const flagged = item.data.flagged;
  const hasAttachments = item.data.has_attachments;
  const fromName = item.data.from_name;
  const fromEmail = item.data.from_email;
  const aiCategory = item.kind === 'message' ? item.data.ai_category : null;
  const aiSummary = item.kind === 'message' ? item.data.ai_summary : null;
  const showSummary = !classic && showAiSummary && Boolean(aiSummary);
  const summaryOrPreview = showSummary ? aiSummary : density === 'comfortable' && !classic ? preview : null;

  function clearPress() {
    if (pressTimer.current !== null) {
      window.clearTimeout(pressTimer.current);
      pressTimer.current = null;
    }
  }

  function onKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect();
    }
  }

  return (
    <div
      role="option"
      aria-selected={selected}
      data-message-id={item.kind === 'message' ? item.data.id : (item.data.latest_message_id ?? item.data.id)}
      tabIndex={0}
      onClick={() => {
        if (longPressed.current) {
          longPressed.current = false;
          return;
        }
        onSelect();
      }}
      onKeyDown={onKey}
      onTouchStart={() => {
        if (!onLongPress) return;
        longPressed.current = false;
        clearPress();
        pressTimer.current = window.setTimeout(() => {
          longPressed.current = true;
          onLongPress();
        }, 450);
      }}
      onTouchEnd={clearPress}
      onTouchMove={clearPress}
      onTouchCancel={clearPress}
      draggable={Boolean(onDragStart)}
      onDragStart={(event) => {
        if (!onDragStart) return;
        onDragStart(event.dataTransfer);
        setDragging(true);
      }}
      onDragEnd={() => {
        setDragging(false);
        endMessageDrag();
      }}
      className={`relative flex cursor-pointer gap-2.5 border-b border-border-default px-3 focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-brand-primary-500 ${
        density === 'comfortable' || showSummary ? 'min-h-[84px] py-2.5' : 'h-[52px] py-2'
      } ${selected ? 'bg-brand-primary-50' : 'bg-bg-canvas hover:bg-bg-subtle'} ${flagged ? 'text-danger-600' : ''} ${dragging ? 'opacity-50' : ''}`}
    >
      {selected ? <span aria-hidden="true" className="absolute inset-y-0 left-0 w-[3px] bg-brand-primary-400" /> : null}
      {showCheckbox ? (
        <span
          className="pt-0.5"
          onClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <Checkbox
            label={<span className="sr-only">{t('mail.selectRow')}</span>}
            checked={checked}
            onChange={(event) => onCheck(event.target.checked)}
          />
        </span>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2 whitespace-nowrap">
          <span className="type-small min-w-0 flex-1 truncate text-text-secondary">
            {senderLabel(fromName, fromEmail)}
            {threadCount > 1 ? <span className="text-text-tertiary"> · {threadCount}</span> : null}
          </span>
          <span className="type-caption shrink-0 text-brand-primary-700">{date}</span>
        </div>
        <div className="flex items-center gap-1.5">
          {aiCategory && categoryColorToken ? (
            <span
              aria-hidden="true"
              title={t(`ai.categories.${aiCategory}.label`, { defaultValue: aiCategory })}
              className={`size-2 shrink-0 rounded-full ${categoryDotClass(categoryColorToken)}`}
            />
          ) : answered ? (
            <Reply size={14} aria-label={t('mail.answered')} className="shrink-0 text-text-tertiary" />
          ) : forwarded ? (
            <Forward size={14} aria-label={t('mail.forwarded')} className="shrink-0 text-text-tertiary" />
          ) : unread ? (
            <span aria-hidden="true" className="size-2 shrink-0 rounded-full bg-warning-400" />
          ) : (
            <span aria-hidden="true" className="size-2 shrink-0" />
          )}
          <span
            className={`min-w-0 flex-1 truncate ${
              unread ? 'type-body-strong text-text-primary' : 'type-body text-text-primary'
            } ${flagged ? 'text-danger-600' : ''}`}
          >
            {subject}
          </span>
          {flagged ? <Flag size={14} aria-hidden="true" className="shrink-0 fill-danger-600 text-danger-600" /> : null}
          {hasAttachments ? <Paperclip size={14} aria-hidden="true" className="shrink-0 text-text-tertiary" /> : null}
          {!classic && aiCategory ? (
            <Sparkles size={14} aria-hidden="true" className="shrink-0 text-brand-primary-500" data-testid="ai-badge" />
          ) : null}
        </div>
        {summaryOrPreview ? (
          <p className="type-caption truncate pl-3.5 text-text-secondary">{summaryOrPreview}</p>
        ) : null}
      </div>
    </div>
  );
}
