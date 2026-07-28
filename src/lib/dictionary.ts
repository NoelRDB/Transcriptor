const STORAGE_KEY = "transcriptor.personal-dictionary";
const WORDS = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;

export function learnedVocabulary(): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string").slice(-300) : [];
  } catch {
    return [];
  }
}

export function learnFromCorrection(before: string, after: string): void {
  const oldWords = before.match(WORDS) ?? [];
  const newWords = after.match(WORDS) ?? [];
  if (oldWords.length !== newWords.length) return;
  const additions = newWords.filter((word, index) => {
    const previous = oldWords[index];
    return previous.localeCompare(word, undefined, { sensitivity: "base" }) !== 0 && word.length >= 2;
  });
  if (!additions.length) return;
  const unique = new Map(learnedVocabulary().map((word) => [word.toLocaleLowerCase(), word]));
  additions.forEach((word) => unique.set(word.toLocaleLowerCase(), word));
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...unique.values()].slice(-300)));
}

export function vocabularyPrompt(existing: string): string {
  return [...new Set([...existing.split(/[,;\n]+/).map((item) => item.trim()).filter(Boolean), ...learnedVocabulary()])].join(", ");
}
