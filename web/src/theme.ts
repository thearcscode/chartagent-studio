export type Theme = "dark" | "light";

// Also hardcoded in index.html's pre-module script (which cannot import);
// rename both or neither.
export const THEME_STORAGE_KEY = "studio-theme";

type Reader = Pick<Storage, "getItem">;
type Writer = Pick<Storage, "setItem">;

/** Dark by default; a stored "light" is the only way out. */
export function getStoredTheme(storage: Reader): Theme {
  return storage.getItem(THEME_STORAGE_KEY) === "light" ? "light" : "dark";
}

/** tokens.css keys its light override off body[data-theme="light"]. */
export function applyTheme(theme: Theme, body: HTMLElement): void {
  body.dataset.theme = theme;
}

export function setTheme(theme: Theme, storage: Writer, body: HTMLElement): void {
  storage.setItem(THEME_STORAGE_KEY, theme);
  applyTheme(theme, body);
}
