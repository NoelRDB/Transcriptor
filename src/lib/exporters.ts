import type { TranscriptSegment, TranscriptionProject } from "../types";
import { formatSrtTime, formatVttTime } from "./time";

export type TextExportFormat = "txt" | "srt" | "vtt" | "json" | "csv";
export type ExportFormat = TextExportFormat | "docx" | "pdf" | "txt-safe" | "docx-safe" | "pdf-safe" | "package" | "package-media";

function normalizedSegments(segments: TranscriptSegment[]): TranscriptSegment[] {
  return [...segments]
    .sort((a, b) => a.startMs - b.startMs || a.order - b.order)
    .map((segment) => ({
      ...segment,
      text: sanitizeUnicode(segment.text),
      speaker: segment.speaker ? sanitizeUnicode(segment.speaker) : segment.speaker,
      words: segment.words.map((word) => ({ ...word, text: sanitizeUnicode(word.text) })),
      startMs: Math.max(0, segment.startMs),
      endMs: Math.max(segment.startMs + 1, segment.endMs),
    }));
}

export function exportProject(project: TranscriptionProject, format: TextExportFormat): string {
  const segments = normalizedSegments(project.segments);
  switch (format) {
    case "txt":
      return segments.map((s) => `${s.speaker ? `${s.speaker}: ` : ""}${s.text.trim()}`).join("\n\n");
    case "srt":
      return segments.map((s, i) => `${i + 1}\n${formatSrtTime(s.startMs)} --> ${formatSrtTime(s.endMs)}\n${s.speaker ? `[${s.speaker}] ` : ""}${s.text.trim()}\n`).join("\n");
    case "vtt":
      return `WEBVTT\n\n${segments.map((s) => `${formatVttTime(s.startMs)} --> ${formatVttTime(s.endMs)}\n${s.speaker ? `<v ${s.speaker}>` : ""}${s.text.trim()}${s.speaker ? "</v>" : ""}`).join("\n\n")}\n`;
    case "csv":
      return ["start_ms,end_ms,speaker,text", ...segments.map((s) => [s.startMs, s.endMs, csv(s.speaker ?? ""), csv(s.text)].join(","))].join("\n");
    case "json":
      return JSON.stringify(
        { version: 1, project: { ...project, mediaUrl: undefined, segments } },
        (_key, value) => typeof value === "string" ? sanitizeUnicode(value) : value,
        2,
      );
  }
}

function csv(value: string): string {
  return `"${value.replaceAll('"', '""')}"`;
}

export function sanitizeUnicode(value: string): string {
  let result = "";
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xD800 && code <= 0xDBFF) {
      const next = value.charCodeAt(index + 1);
      if (next >= 0xDC00 && next <= 0xDFFF) {
        result += value[index] + value[index + 1];
        index += 1;
      } else {
        result += "\uFFFD";
      }
    } else if (code >= 0xDC00 && code <= 0xDFFF) {
      result += "\uFFFD";
    } else {
      result += value[index];
    }
  }
  return result;
}

export function downloadText(filename: string, contents: string, mime = "text/plain;charset=utf-8"): void {
  const withBom = filename.toLocaleLowerCase().endsWith(".json") ? contents : `\uFEFF${contents}`;
  const blob = new Blob([withBom], { type: mime });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
