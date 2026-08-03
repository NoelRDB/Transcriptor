// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InsightsDialog } from "./InsightsDialog";
import type { ProjectInsights } from "../types";

const insights: ProjectInsights = {
  projectId: "couple-test",
  generatedAt: "2026-08-03T00:00:00Z",
  method: "local-ollama-qwen3.5:9b-single-pass-v2",
  mode: "couple",
  summary: "La pareja identifica una necesidad de comunicación y acuerda avisarse.",
  findings: [{
    id: "finding-1", kind: "tension", title: "Falta de comunicación",
    text: "La ausencia de avisos genera malestar.", evidence: "Necesito que me avises.",
    confidence: "explicit", startMs: 12_000, endMs: 15_000, segmentId: "s1",
  }],
  keyPoints: [], chapters: [], concepts: [], conceptEdges: [],
  signals: { questions: 1, agreements: 2, affectionMarkers: 1, tensionMarkers: 1 },
  statistics: { wordCount: 120, paragraphCount: 6, questions: 1, wordsPerMinute: 80, durationMinutes: 1.5 },
  notice: "Análisis local verificable.",
};

describe("inteligencia de la transcripción", () => {
  it("muestra los modos y señales útiles sin selector de profundidad", () => {
    render(<InsightsDialog
      insights={insights} loading={false} mode="couple" progress={null}
      analysisStartedAt={null} aiStatus={{ available: true, installed: true, version: "0.32.5", model: "qwen3.5:9b", models: ["qwen3.5:9b"], endpoint: "local" }}
      paragraphCount={6} onModeChange={vi.fn()} onAnalyze={vi.fn()} onCancelAnalysis={vi.fn()}
      onGroupParagraphs={vi.fn()} assistantAnswers={[]} assistantLoading={false}
      onAsk={vi.fn()} onSeek={vi.fn()} onClose={vi.fn()}
    />);

    expect(screen.getByRole("option", { name: "General · analiza todo" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Conversación de amigos" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Conversación de pareja" })).toBeTruthy();
    expect(screen.getByRole("option", { name: "Legal / jurídica" })).toBeTruthy();
    expect(screen.queryByText("Profundidad")).toBeNull();
    expect(screen.getByText("Acuerdos / decisiones")).toBeTruthy();
    expect(screen.getByText("Emoción / afecto")).toBeTruthy();
    expect(screen.getByText("Tensiones / problemas")).toBeTruthy();
    expect(screen.getByText("Preguntas abiertas")).toBeTruthy();
    expect(screen.getByText(/Necesito que me avises/)).toBeTruthy();
  });
});
