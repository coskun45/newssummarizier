/**
 * Trigger a browser download of a Blob fetched from the backend (object-URL +
 * synthetic <a download> click, factored out of exportArticles.ts's
 * client-built-HTML download so a fetched-blob download has one place to live).
 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
