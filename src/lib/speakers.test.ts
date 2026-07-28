import { describe, expect, it } from "vitest";
import { speakerClassName } from "./speakers";

describe("speakerClassName", () => {
  it("da una identidad visual estable a tantos hablantes genéricos como aparezcan", () => {
    expect(speakerClassName("Hablante 1")).toBe("speaker-one");
    expect(speakerClassName("Hablante 2")).toBe("speaker-two");
    expect(speakerClassName("Hablante 3")).toBe("speaker-three");
    expect(speakerClassName("Hablante 4")).toBe("speaker-four");
    expect(speakerClassName("Hablante 5")).toBe("speaker-one");
  });

  it("mantiene estable el color de un perfil con nombre", () => {
    expect(speakerClassName("Noel")).toBe(speakerClassName("Noel"));
  });
});
