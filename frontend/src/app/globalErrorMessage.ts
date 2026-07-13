export function resolveGlobalErrorMessage(
  pageErrorMessage: string | null,
  playbackErrorMessage: string | null
): string | null {
  if (pageErrorMessage && pageErrorMessage.trim().length > 0) {
    return pageErrorMessage;
  }
  if (playbackErrorMessage && playbackErrorMessage.trim().length > 0) {
    return playbackErrorMessage;
  }
  return null;
}
