import { describe, it, expect } from "vitest";
import { PROVIDERS } from "../types";

describe("PROVIDERS catalog", () => {
  it("includes the core providers", () => {
    const ids = PROVIDERS.map((p) => p.id);
    expect(ids).toContain("openrouter");
    expect(ids).toContain("ollama");
    expect(ids).toContain("anthropic");
  });

  it("every provider lists at least one model", () => {
    for (const p of PROVIDERS) {
      expect(p.models.length).toBeGreaterThan(0);
    }
  });
});
