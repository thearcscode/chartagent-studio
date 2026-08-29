type GetToken = () => Promise<string | null>;

/** fetch with the Clerk session JWT attached, for the SPA-private API. */
export async function apiFetch(
  path: string,
  getToken: GetToken,
  init?: RequestInit,
): Promise<Response> {
  const token = await getToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(path, { ...init, headers });
}
