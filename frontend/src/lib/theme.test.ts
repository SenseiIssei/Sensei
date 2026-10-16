import { afterEach, describe, expect, it, vi } from "vitest";
import { applyTheme, getThemeChoice, resolveTheme, setThemeChoice } from "./theme";

function prefersDark(dark: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("dark") ? dark : !dark,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("theme", () => {
  it("defaults to following the system", () => {
    expect(getThemeChoice()).toBe("system");
    prefersDark(false);
    expect(resolveTheme("system")).toBe("light");
    prefersDark(true);
    expect(resolveTheme("system")).toBe("dark");
  });

  it("an explicit choice wins over the system and is remembered", () => {
    prefersDark(true);
    setThemeChoice("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(getThemeChoice()).toBe("light");
  });

  it("ignores garbage in storage", () => {
    localStorage.setItem("sensei-theme", "neon");
    expect(getThemeChoice()).toBe("system");
  });

  it("applies the resolved theme to <html>", () => {
    prefersDark(true);
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
