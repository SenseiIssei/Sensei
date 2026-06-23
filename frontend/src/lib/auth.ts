import type { User } from "@/types";

const API_BASE = "/api";

function getToken(): string | null {
  return localStorage.getItem("sensei_token");
}

export const authApi = {
  async register(email: string, password: string, name: string): Promise<{ token: string; user: User }> {
    const resp = await fetch(`${API_BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, name }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.detail || "Registration failed");
    }
    const data = await resp.json();
    localStorage.setItem("sensei_token", data.access_token);
    localStorage.setItem("sensei_user", JSON.stringify(data.user));
    return { token: data.access_token, user: data.user };
  },

  async login(email: string, password: string): Promise<{ token: string; user: User }> {
    const resp = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!resp.ok) {
      const data = await resp.json();
      throw new Error(data.detail || "Login failed");
    }
    const data = await resp.json();
    localStorage.setItem("sensei_token", data.access_token);
    localStorage.setItem("sensei_user", JSON.stringify(data.user));
    return { token: data.access_token, user: data.user };
  },

  logout() {
    localStorage.removeItem("sensei_token");
    localStorage.removeItem("sensei_user");
  },

  getToken,
  getUser(): User | null {
    const raw = localStorage.getItem("sensei_user");
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch {
      return null;
    }
  },

  isAuthenticated(): boolean {
    return !!getToken();
  },
};
