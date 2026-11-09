/** How long the object URL of a saved file lives: Firefox and Safari cancel a download whose URL is revoked at once. */
export const REVOKE_DELAY_MS = 40_000;

/**
 * Saves a blob as a file through a temporary link. The link is in the document while it is clicked
 * (Firefox ignores a click on a detached one) and its object URL is revoked a while later.
 */
export function saveBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
}
