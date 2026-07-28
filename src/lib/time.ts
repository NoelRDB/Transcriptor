export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function formatClock(ms: number): string {
  const safe = Math.max(0, Math.floor(ms));
  const totalSeconds = Math.floor(safe / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const prefix = hours > 0 ? `${String(hours).padStart(2, "0")}:` : "";
  return `${prefix}${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function formatSrtTime(ms: number): string {
  return formatSubtitleTime(ms, ",");
}

export function formatVttTime(ms: number): string {
  return formatSubtitleTime(ms, ".");
}

function formatSubtitleTime(ms: number, separator: string): string {
  const safe = Math.max(0, Math.round(ms));
  const hours = Math.floor(safe / 3_600_000);
  const minutes = Math.floor((safe % 3_600_000) / 60_000);
  const seconds = Math.floor((safe % 60_000) / 1000);
  const millis = safe % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}${separator}${String(millis).padStart(3, "0")}`;
}

export function activeSegmentIndex(segments: { startMs: number; endMs: number }[], currentMs: number): number {
  let low = 0;
  let high = segments.length - 1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    const segment = segments[mid];
    if (currentMs < segment.startMs) high = mid - 1;
    else if (currentMs >= segment.endMs) low = mid + 1;
    else return mid;
  }
  return -1;
}

export function followSegmentIndex(segments: { startMs: number; endMs: number }[], currentMs: number): number {
  if (!segments.length) return -1;
  const active = activeSegmentIndex(segments, currentMs);
  if (active >= 0) return active;
  let low = 0;
  let high = segments.length;
  while (low < high) {
    const mid = (low + high) >> 1;
    if (segments[mid].startMs <= currentMs) low = mid + 1;
    else high = mid;
  }
  return low < segments.length ? low : segments.length - 1;
}
