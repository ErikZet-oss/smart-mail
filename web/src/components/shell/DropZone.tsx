import { Upload } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useToast } from '../toastContext';

function hasFiles(event: DragEvent): boolean {
  if (document.querySelector('[data-compose-dropzone]')) return false; // W4/M4 attaches dropped files itself
  return Array.from(event.dataTransfer?.types ?? []).includes('Files');
}

/** G7: dragging a file over any signed-in screen shows the full-screen drop overlay. The target (W6u Nahrať doklad)
 * arrives with the documents in Phase 4; until then a drop only explains that and never opens the file. */
export function DropZone() {
  const { t } = useTranslation();
  const toast = useToast();
  const [over, setOver] = useState(false);
  const depth = useRef(0);

  useEffect(() => {
    const enter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth.current += 1;
      setOver(true);
    };
    const leave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setOver(false);
    };
    const overHandler = (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
    };
    const drop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setOver(false);
      toast({ message: t('shell.dropLater') });
    };
    window.addEventListener('dragenter', enter);
    window.addEventListener('dragleave', leave);
    window.addEventListener('dragover', overHandler);
    window.addEventListener('drop', drop);
    return () => {
      window.removeEventListener('dragenter', enter);
      window.removeEventListener('dragleave', leave);
      window.removeEventListener('dragover', overHandler);
      window.removeEventListener('drop', drop);
    };
  }, [t, toast]);

  if (!over) return null;
  return (
    <div role="status" className="pointer-events-none fixed inset-0 z-50 bg-bg-overlay p-6">
      <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-brand-primary-500 bg-bg-canvas text-center">
        <span className="flex size-[72px] items-center justify-center rounded-full bg-brand-primary-50">
          <Upload size={28} aria-hidden="true" className="text-brand-primary-600" />
        </span>
        <p className="type-heading text-text-primary">{t('shell.dropHere')}</p>
        <p className="type-caption text-text-secondary">{t('shell.dropFormats')}</p>
      </div>
    </div>
  );
}
