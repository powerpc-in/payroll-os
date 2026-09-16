// Session boundary: auth is an httpOnly cookie the backend owns; the frontend's one
// duty is wiping the react-query cache so one account's data never renders for the next.

import { useQuery } from "@tanstack/react-query";
import { queryClient } from "./queryClient";
import { apiGet, apiPost } from "./api";
import type { SessionPayload } from "@/lib/types";

export const sessionKey = ["session"] as const;

export const fetchSession = () => apiGet<SessionPayload>("/v1/auth/me");

export function useSession() {
  return useQuery({ queryKey: sessionKey, queryFn: fetchSession, retry: false, staleTime: 60_000 });
}

// Call after every successful login/signup.
export function beginSession(): void {
  queryClient.clear();
}

// Call from every sign-out control; clears the server session AND the local cache.
export async function endSession(): Promise<void> {
  try {
    await apiPost("/v1/auth/logout", {});
  } finally {
    queryClient.clear();
  }
}

export async function login(email: string, password: string): Promise<SessionPayload> {
  const payload = await apiPost<SessionPayload>("/v1/auth/login", { email, password });
  beginSession();
  return payload;
}

export async function signup(payload: {
  name: string; email: string; password: string; org_name: string;
}): Promise<SessionPayload> {
  const result = await apiPost<SessionPayload>("/v1/auth/signup", payload);
  beginSession();
  return result;
}
