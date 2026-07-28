import type { MediaKind } from "../types";

const AUDIO_EXTENSIONS = new Set(["mp3", "wav", "m4a", "aac", "flac", "ogg", "opus"]);
const VIDEO_EXTENSIONS = new Set(["mp4", "mov", "mkv", "avi", "webm", "m4v"]);

export const MEDIA_FILTERS = [
  { name: "Audio, vídeo o proyecto", extensions: [...AUDIO_EXTENSIONS, ...VIDEO_EXTENSIONS, "transcriptor"] },
  { name: "Proyecto Transcriptor", extensions: ["transcriptor"] },
  { name: "Audio", extensions: [...AUDIO_EXTENSIONS] },
  { name: "Vídeo", extensions: [...VIDEO_EXTENSIONS] },
];

export function mediaKind(pathOrName: string): MediaKind | null {
  const extension = pathOrName.split(".").pop()?.toLowerCase() ?? "";
  if (AUDIO_EXTENSIONS.has(extension)) return "audio";
  if (VIDEO_EXTENSIONS.has(extension)) return "video";
  return null;
}

export function displayName(path: string): string {
  return path.split(/[\\/]/).pop()?.replace(/\.[^.]+$/, "") || "Proyecto sin título";
}

export function safeBaseName(name: string): string {
  const withoutReserved = name.replace(/[<>:"/\\|?*]/g, "_");
  return [...withoutReserved].map((character) => character.charCodeAt(0) < 32 ? "_" : character).join("").trim() || "transcripcion";
}
