import { describe, expect, it } from "vitest";

import {
  applyTheme,
  getStoredTheme,
  setTheme,
  THEME_STORAGE_KEY,
} from "./theme";

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => void map.set(key, value),
    map,
  };
}

describe("theme", () => {
  it("is dark by default", () => {
    expect(getStoredTheme(fakeStorage())).toBe("dark");
  });

  it("reads a persisted light preference", () => {
    const storage = fakeStorage({ [THEME_STORAGE_KEY]: "light" });
    expect(getStoredTheme(storage)).toBe("light");
  });

  it("persists and applies the choice", () => {
    const storage = fakeStorage();
    const body = document.createElement("body");
    setTheme("light", storage, body);
    expect(storage.map.get(THEME_STORAGE_KEY)).toBe("light");
    expect(body.dataset.theme).toBe("light");
  });

  it("applies dark as an explicit attribute", () => {
    const body = document.createElement("body");
    applyTheme("dark", body);
    expect(body.dataset.theme).toBe("dark");
  });
});
