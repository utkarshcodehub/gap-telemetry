// Light/dark theme persistence — applied as a data-theme attribute on <html>.
export function getInitialTheme() {
  return localStorage.getItem('theme') || 'light';
}

export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
}
