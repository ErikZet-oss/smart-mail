import type { PDFDocumentProxy } from 'pdfjs-dist';

/**
 * pdf.js, loaded only when a PDF is opened (W2l, #46). The worker is bundled by Vite (same origin, CSP
 * `script-src 'self'`); no `eval`, and PDF JavaScript never runs (no scripting sandbox is loaded).
 */
async function pdfjs() {
  const [lib, worker] = await Promise.all([import('pdfjs-dist'), import('pdfjs-dist/build/pdf.worker.min.mjs?url')]);
  lib.GlobalWorkerOptions.workerSrc = worker.default;
  return lib;
}

export async function openPdf(data: ArrayBuffer): Promise<PDFDocumentProxy> {
  const lib = await pdfjs();
  return lib.getDocument({
    data: new Uint8Array(data),
    isEvalSupported: false,
    disableAutoFetch: true,
  }).promise;
}

/** Renders one page into `canvas` and its selectable text into `textBox`; returns a cancel function. */
export async function renderPage(
  doc: PDFDocumentProxy,
  pageNumber: number,
  scale: number,
  canvas: HTMLCanvasElement,
  textBox: HTMLDivElement,
): Promise<() => void> {
  const lib = await pdfjs();
  const page = await doc.getPage(pageNumber);
  const viewport = page.getViewport({ scale });
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;
  const context = canvas.getContext('2d');
  if (!context) return () => undefined;
  const task = page.render({
    canvasContext: context,
    viewport,
    transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0],
  });
  textBox.replaceChildren();
  textBox.style.setProperty('--scale-factor', String(scale));
  const text = new lib.TextLayer({ textContentSource: page.streamTextContent(), container: textBox, viewport });
  await Promise.all([task.promise, text.render()]).catch(() => undefined);
  return () => {
    task.cancel();
    text.cancel();
  };
}

/** Page size at scale 1 (fit to the window). */
export async function pageSize(doc: PDFDocumentProxy, pageNumber: number): Promise<{ width: number; height: number }> {
  const viewport = (await doc.getPage(pageNumber)).getViewport({ scale: 1 });
  return { width: viewport.width, height: viewport.height };
}

/** Every page as a PNG data URL, for „Tlačiť“ (the PDF itself is never embedded). */
export async function pageImages(doc: PDFDocumentProxy, scale = 2): Promise<string[]> {
  const out: string[] = [];
  for (let n = 1; n <= doc.numPages; n += 1) {
    const page = await doc.getPage(n);
    const viewport = page.getViewport({ scale });
    const canvas = document.createElement('canvas');
    canvas.width = Math.floor(viewport.width);
    canvas.height = Math.floor(viewport.height);
    const context = canvas.getContext('2d');
    if (!context) continue;
    await page.render({ canvasContext: context, viewport }).promise;
    out.push(canvas.toDataURL('image/png'));
  }
  return out;
}
