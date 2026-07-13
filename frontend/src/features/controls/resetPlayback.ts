export function handleResetPlayback(
  setPlaying: (value: boolean) => void,
  seek: (value: number) => void
) {
  setPlaying(false);
  seek(0);
}
