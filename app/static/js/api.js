// JSON REST API client.

export async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (res.status === 204) return null;
  const data = await res.json();
  if (!res.ok) throw new Error(typeof data.error === "string" ? data.error : "");
  return data;
}
