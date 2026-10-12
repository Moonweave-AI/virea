export type Language = "zh-CN" | "en";
export type Theme = "system" | "light" | "dark";
const read = (key: string, fallback: string) => {try {return localStorage.getItem(key) || fallback;} catch {return fallback;}};
let language: Language = read("virea.language.v1", "zh-CN") === "en" ? "en" : "zh-CN";
let theme = read("virea.theme.v1", "system") as Theme;
if (!["system", "light", "dark"].includes(theme)) theme = "system";
const listeners = new Set<() => void>();
const media = matchMedia("(prefers-color-scheme: dark)");
export const getLanguage = () => language;
export const getTheme = () => theme;
export const subscribe = (listener: () => void) => {listeners.add(listener); return () => {listeners.delete(listener);};};
export const t = (zh: string, en: string) => language === "en" ? en : zh;
function apply() {
  const resolved = theme === "system" ? media.matches ? "dark" : "light" : theme;
  const html = document.documentElement;
  html.dataset.theme = resolved; html.classList.toggle("dark", resolved === "dark"); html.classList.toggle("light", resolved === "light");
  html.lang = language;
  for (const listener of listeners) listener();
}
export function setLanguage(value: Language) {
  language = value; try {localStorage.setItem("virea.language.v1", value);} catch { /* Session-only preferences still work. */ } apply();
}
export function setTheme(value: Theme) {
  theme = value; try {localStorage.setItem("virea.theme.v1", value);} catch { /* Session-only preferences still work. */ } apply();
}
media.addEventListener("change", apply);
window.addEventListener("storage", event => {
  if (event.key === "virea.language.v1") language = event.newValue === "en" ? "en" : "zh-CN";
  if (event.key === "virea.theme.v1") theme = ["system","light","dark"].includes(event.newValue || "") ? event.newValue as Theme : "system";
  apply();
});
apply();
