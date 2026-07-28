import { describe, expect, it } from "vitest";
import { shouldRouteEngineEvent } from "./jobs";

describe("engine job event routing", () => {
  it("accepts events only for the active project", () => {
    expect(shouldRouteEngineEvent("partial_segments", { projectId: "active" }, "active")).toBe(true);
    expect(shouldRouteEngineEvent("partial_segments", { projectId: "old" }, "active")).toBe(false);
  });

  it("rejects unscoped job events but keeps global engine events", () => {
    expect(shouldRouteEngineEvent("transcription_progress", {}, "active")).toBe(false);
    expect(shouldRouteEngineEvent("engine_closed", { code: 1 }, "active")).toBe(true);
  });
});
