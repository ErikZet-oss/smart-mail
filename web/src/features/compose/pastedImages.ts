/** Image files on the clipboard (a Win+Shift+S / PrintScreen screenshot, a copied picture). Text and HTML pastes return
 * nothing, so they keep the editor's normal paste. Only the types the inline-image upload accepts. */
const INLINE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif']);

export function pastedImages(data: DataTransfer | null | undefined): File[] {
  if (!data) return [];
  const files: File[] = [];
  for (const item of Array.from(data.items ?? [])) {
    if (item.kind !== 'file' || !INLINE_TYPES.has(item.type)) continue;
    const file = item.getAsFile();
    if (!file) continue;
    // Screenshots arrive as „image.png“; give them a readable name for the attachment list.
    const name = file.name && file.name !== 'image.png' ? file.name : `snimka-${Date.now()}.${item.type.split('/')[1]}`;
    files.push(new File([file], name, { type: item.type }));
  }
  return files;
}
