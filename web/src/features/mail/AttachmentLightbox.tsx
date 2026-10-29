import { ChevronLeft, ChevronRight, Download, FileText, Printer, RotateCw, X, ZoomIn, ZoomOut } from 'lucide-react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import { useCallback, useEffect, useRef, useState, type ReactNode, type TouchEvent } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';

import { MOBILE_QUERY, useMediaQuery } from '../../lib/useMediaQuery';
import { attachmentUrl, type AttachmentOut } from './mailApi';
import { openPdf, pageImages, pageSize, renderPage } from './pdfRender';
import { previewKind, xmlRows, type XmlRow } from './previewKind';

const ZOOM_STEP = 0.25;
const ZOOM_MIN = 0.25;
const ZOOM_MAX = 4;

type Props = {
  mailbox: string;
  /** Previewable attachments of the message, in chip order; ←/→ move between them. */
  attachments: AttachmentOut[];
  index: number;
  onIndex: (index: number) => void;
  onClose: () => void;
  formatSize: (bytes: number) => string;
};

type Loaded =
  | { state: 'loading' }
  | { state: 'error'; code: 'infected' | 'failed' }
  | { state: 'pdf'; doc: PDFDocumentProxy }
  | { state: 'image'; url: string }
  | { state: 'xml'; rows: XmlRow[] | null };

/** W2l Náhľad prílohy (#46): full-screen dark overlay; PDF via pdf.js (canvas + text layer), images, XML/ISDOC. */
export function AttachmentLightbox(props: Props) {
  // a fresh viewer per attachment: page, zoom and rotation start over
  return <LightboxBody key={props.attachments[props.index]?.id ?? 'none'} {...props} />;
}

function LightboxBody({ mailbox, attachments, index, onIndex, onClose, formatSize }: Props) {
  const { t } = useTranslation();
  const mobile = useMediaQuery(MOBILE_QUERY);
  const att = attachments[index];
  const kind = att ? previewKind(att) : null;
  const [loaded, setLoaded] = useState<Loaded>({ state: 'loading' });
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [printPages, setPrintPages] = useState<string[] | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const touchX = useRef<number | null>(null);

  // load the bytes of the current attachment (same auth as Stiahnuť; infected → 403, never shown)
  useEffect(() => {
    if (!att || !kind) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    let doc: PDFDocumentProxy | null = null;
    void (async () => {
      try {
        const response = await fetch(attachmentUrl(mailbox, att.id), { credentials: 'same-origin' });
        if (response.status === 403) throw new Error('infected');
        if (!response.ok) throw new Error('failed');
        if (kind === 'image') {
          objectUrl = URL.createObjectURL(await response.blob());
          if (!cancelled) setLoaded({ state: 'image', url: objectUrl });
        } else if (kind === 'xml') {
          const rows = xmlRows(await response.text());
          if (!cancelled) setLoaded({ state: 'xml', rows });
        } else {
          doc = await openPdf(await response.arrayBuffer());
          if (cancelled) return;
          const size = await pageSize(doc, 1);
          const box = boxRef.current;
          const roomW = (box?.clientWidth ?? window.innerWidth) - (mobile ? 16 : 160);
          const roomH = (box?.clientHeight ?? window.innerHeight) - 40;
          // phones: fit width (W2l mobile); desktop: the whole page in the window, as in the Figma frame
          const fit = mobile ? roomW / size.width : Math.min(roomW / size.width, roomH / size.height, 1);
          setZoom(Math.max(ZOOM_MIN, fit));
          setLoaded({ state: 'pdf', doc });
        }
      } catch (error) {
        if (!cancelled) {
          setLoaded({ state: 'error', code: (error as Error).message === 'infected' ? 'infected' : 'failed' });
        }
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      void doc?.destroy();
    };
  }, [att, kind, mailbox, mobile]);

  const pages = loaded.state === 'pdf' ? loaded.doc.numPages : 1;
  const go = useCallback(
    (step: number) => {
      const next = index + step;
      if (next >= 0 && next < attachments.length) onIndex(next);
    },
    [attachments.length, index, onIndex],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      else if (event.key === 'ArrowLeft') go(-1);
      else if (event.key === 'ArrowRight') go(1);
      else if (event.key === 'PageDown') setPage((p) => Math.min(pages, p + 1));
      else if (event.key === 'PageUp') setPage((p) => Math.max(1, p - 1));
      else return;
      event.preventDefault();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, onClose, pages]);

  useEffect(() => {
    if (!printPages) return;
    document.body.classList.add('printing-pages');
    const done = () => {
      document.body.classList.remove('printing-pages');
      setPrintPages(null);
    };
    window.addEventListener('afterprint', done, { once: true });
    window.print();
    return () => {
      window.removeEventListener('afterprint', done);
      document.body.classList.remove('printing-pages');
    };
  }, [printPages]);

  if (!att || !kind) return null;

  const print = async () => {
    if (loaded.state === 'pdf') setPrintPages(await pageImages(loaded.doc));
    else if (loaded.state === 'image') setPrintPages([loaded.url]);
    else window.print();
  };
  const onTouchStart = (event: TouchEvent) => {
    touchX.current = event.touches.length === 1 ? (event.touches[0]?.clientX ?? null) : null;
  };
  const onTouchEnd = (event: TouchEvent) => {
    const start = touchX.current;
    const end = event.changedTouches[0]?.clientX;
    touchX.current = null;
    if (start == null || end == null || Math.abs(end - start) < 60 || zoom > 1.01) return;
    go(end < start ? 1 : -1);
  };

  const tool =
    'flex size-9 items-center justify-center rounded-sm text-text-on-rail hover:text-text-on-rail-active disabled:opacity-40';
  const button =
    'type-label inline-flex h-7 shrink-0 items-center gap-1.5 rounded-sm border border-border-strong bg-bg-canvas px-2.5 text-text-primary hover:bg-bg-subtle';

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t('mail.preview.title', { name: att.filename })}
      className="fixed inset-0 z-50 flex flex-col"
      data-testid="attachment-lightbox"
    >
      <div
        aria-hidden="true"
        className={`absolute inset-0 bg-bg-rail ${mobile ? '' : 'opacity-95'}`}
        onClick={onClose}
      />
      <header className="relative flex h-14 shrink-0 items-center gap-3 px-4 text-text-on-rail">
        <FileText size={18} aria-hidden="true" className="shrink-0 text-text-on-rail-active" />
        <p className="type-body-strong min-w-0 flex-1 truncate text-text-on-rail-active">
          {att.filename} · {formatSize(att.size)}
        </p>
        {loaded.state === 'pdf' ? (
          <>
            <button
              type="button"
              className={tool}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              aria-label={t('mail.preview.prevPage')}
            >
              <ChevronLeft size={18} aria-hidden="true" />
            </button>
            <span className="type-small whitespace-nowrap" data-testid="pdf-page">
              {t('mail.preview.page', { page, pages })}
            </span>
            <button
              type="button"
              className={tool}
              onClick={() => setPage((p) => Math.min(pages, p + 1))}
              disabled={page >= pages}
              aria-label={t('mail.preview.nextPage')}
            >
              <ChevronRight size={18} aria-hidden="true" />
            </button>
          </>
        ) : null}
        {loaded.state === 'pdf' || loaded.state === 'image' ? (
          <>
            <button
              type="button"
              className={tool}
              onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))}
              aria-label={t('mail.preview.zoomOut')}
            >
              <ZoomOut size={20} aria-hidden="true" />
            </button>
            <span className="type-small hidden w-12 text-center sm:inline" data-testid="preview-zoom">
              {Math.round(zoom * 100)} %
            </span>
            <button
              type="button"
              className={tool}
              onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))}
              aria-label={t('mail.preview.zoomIn')}
            >
              <ZoomIn size={20} aria-hidden="true" />
            </button>
            {loaded.state === 'image' ? (
              <button
                type="button"
                className={tool}
                onClick={() => setRotation((r) => (r + 90) % 360)}
                aria-label={t('mail.preview.rotate')}
              >
                <RotateCw size={20} aria-hidden="true" />
              </button>
            ) : null}
          </>
        ) : null}
        <a
          href={attachmentUrl(mailbox, att.id)}
          download={att.filename}
          className={mobile ? tool : button}
          aria-label={t('mail.preview.download')}
        >
          <Download size={16} aria-hidden="true" />
          {mobile ? null : t('mail.preview.download')}
        </a>
        {mobile ? null : (
          <button type="button" className={button} onClick={() => void print()} disabled={loaded.state === 'loading'}>
            <Printer size={16} aria-hidden="true" />
            {t('mail.preview.print')}
          </button>
        )}
        <button type="button" className={tool} onClick={onClose} aria-label={t('common.close')}>
          <X size={22} aria-hidden="true" />
        </button>
      </header>

      <div
        ref={boxRef}
        className="relative flex min-h-0 flex-1 items-start justify-center overflow-auto px-2 pb-6 pt-4 sm:px-20"
        style={{ touchAction: 'pan-x pan-y pinch-zoom' }}
        onTouchStart={onTouchStart}
        onTouchEnd={onTouchEnd}
      >
        {loaded.state === 'loading' ? (
          <Note>{t('mail.preview.loading')}</Note>
        ) : loaded.state === 'error' ? (
          <Note>{loaded.code === 'infected' ? t('mail.attachmentInfected') : t('mail.preview.failed')}</Note>
        ) : loaded.state === 'image' ? (
          <img
            src={loaded.url}
            alt={att.filename}
            className="max-w-none bg-bg-canvas shadow-e3"
            style={{ transform: `rotate(${rotation}deg)`, width: `${zoom * 100}%`, maxWidth: `${zoom * 100}%` }}
          />
        ) : loaded.state === 'xml' ? (
          <XmlTable rows={loaded.rows} />
        ) : (
          <PdfPage doc={loaded.doc} page={page} scale={zoom} />
        )}
      </div>

      {attachments.length > 1 && !mobile ? (
        <>
          <button
            type="button"
            onClick={() => go(-1)}
            disabled={index === 0}
            aria-label={t('mail.preview.prev')}
            className="absolute left-6 top-1/2 flex size-11 -translate-y-1/2 items-center justify-center rounded-full bg-bg-rail-active text-text-on-rail-active disabled:opacity-30"
          >
            <ChevronLeft size={24} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={() => go(1)}
            disabled={index === attachments.length - 1}
            aria-label={t('mail.preview.next')}
            className="absolute right-6 top-1/2 flex size-11 -translate-y-1/2 items-center justify-center rounded-full bg-bg-rail-active text-text-on-rail-active disabled:opacity-30"
          >
            <ChevronRight size={24} aria-hidden="true" />
          </button>
        </>
      ) : null}

      {printPages
        ? createPortal(
            <div className="print-pages">
              {printPages.map((src, i) => (
                <img key={i} src={src} alt="" />
              ))}
            </div>,
            document.body,
          )
        : null}
    </div>,
    document.body,
  );
}

function Note({ children }: { children: ReactNode }) {
  return <p className="type-body relative mt-24 text-text-on-rail">{children}</p>;
}

function PdfPage({ doc, page, scale }: { doc: PDFDocumentProxy; page: number; scale: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const text = useRef<HTMLDivElement>(null);
  const [rendered, setRendered] = useState(0);
  useEffect(() => {
    let cancel: (() => void) | null = null;
    let stale = false;
    if (canvas.current && text.current) {
      void renderPage(doc, page, scale, canvas.current, text.current).then((fn) => {
        if (stale) fn();
        else {
          cancel = fn;
          setRendered(page);
        }
      });
    }
    return () => {
      stale = true;
      cancel?.();
    };
  }, [doc, page, scale]);
  return (
    <div className="relative shrink-0 bg-bg-canvas shadow-e3" data-testid="pdf-page-view" data-rendered={rendered}>
      <canvas ref={canvas} className="block" />
      <div ref={text} className="pdf-text-layer" />
    </div>
  );
}

function XmlTable({ rows }: { rows: XmlRow[] | null }) {
  const { t } = useTranslation();
  if (!rows) return <Note>{t('mail.preview.failed')}</Note>;
  return (
    <div className="relative w-full max-w-4xl overflow-hidden rounded-md bg-bg-canvas shadow-e3">
      <table className="w-full border-collapse" data-testid="xml-table">
        <thead className="bg-bg-subtle">
          <tr className="type-label text-left text-text-secondary">
            <th className="px-3 py-2 font-semibold">{t('mail.preview.xmlField')}</th>
            <th className="px-3 py-2 font-semibold">{t('mail.preview.xmlValue')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="type-small border-t border-border-default text-text-primary">
              <td className="px-3 py-1.5 text-text-secondary">{row.path}</td>
              <td className="break-all px-3 py-1.5">{row.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
