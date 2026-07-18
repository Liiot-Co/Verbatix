export const TOKEN_KEY = "verbatix:token";

export function decodeStoredToken(value: string | null): string | null {
  if (!value) return null;
  try {
    const parsed: unknown = JSON.parse(value);
    return typeof parsed === "string" ? parsed : value;
  } catch {
    return value;
  }
}

export function readAuthToken(): string | null {
  try {
    return decodeStoredToken(localStorage.getItem(TOKEN_KEY));
  } catch {
    return null;
  }
}

export function writeAuthToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage unavailable
  }
}
