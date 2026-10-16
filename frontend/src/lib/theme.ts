/**
 * Light, dark, or whatever the operating system says.
 *
 * The choice lives in localStorage and is applied as `data-theme` on <html> —
 * the same mechanism Odysync uses, so both apps switch the same way. An inline
 * script in index.html applies it before the first paint; this module keeps it
 * in sync afterwards, including when the system setting changes while "system"
 * is selected.
 */

export type ThemeChoice = "system" | "light" | "dark";

const KEY = "sensei-theme";

export function getThemeChoice(): ThemeChoice {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "light" || value === "dark" || value === "system") return value;
  } catch {
    // Storage blocked (private window, embedded preview) — fall back silently.
  }
  return "system";
}

function systemPrefersDark(): boolean {
  return typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-color-scheme: dark)").matches
    : true;
}

export function resolveTheme(choice: ThemeChoice): "light" | "dark" {
  if (choice === "system") return systemPrefersDark() ? "dark" : "light";
  return choice;
}

export function applyTheme(choice: ThemeChoice): void {
  const resolved = resolveTheme(choice);
  document.documentElement.dataset.theme = resolved;
  const meta = document.querySelector('meta[name="theme-color"]');
  meta?.setAttribute("content", resolved === "dark" ? "#0d0f10" : "#eff1f5");
}

export function setThemeChoice(choice: ThemeChoice): void {
  try {
    localStorage.setItem(KEY, choice);
  } catch {
    // Not persisted, but still applied for this page.
  }
  applyTheme(choice);
}

/** Follow the OS while the choice is "system". Returns an unsubscribe. */
export function watchSystemTheme(): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  const onChange = () => {
    if (getThemeChoice() === "system") applyTheme("system");
  };
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
