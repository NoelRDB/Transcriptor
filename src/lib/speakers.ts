const SPEAKER_CLASSES = ["speaker-one", "speaker-two", "speaker-three", "speaker-four"] as const;

export function speakerClassName(speaker?: string): string {
  if (!speaker) return SPEAKER_CLASSES[0];
  const generic = /^Hablante\s+(\d+)$/i.exec(speaker.trim());
  if (generic) {
    const position = Math.max(0, Number(generic[1]) - 1);
    return SPEAKER_CLASSES[position % SPEAKER_CLASSES.length];
  }
  let hash = 0;
  for (const character of speaker) hash = (hash * 31 + (character.codePointAt(0) ?? 0)) >>> 0;
  return SPEAKER_CLASSES[hash % SPEAKER_CLASSES.length];
}
