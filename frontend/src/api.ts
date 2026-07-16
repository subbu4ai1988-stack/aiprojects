export async function api(path: string, options: RequestInit = {}) {
  const token = localStorage.getItem('token');
  const response = await fetch('/api' + path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : {'Content-Type': 'application/json'}),
      ...(token ? {Authorization: `Bearer ${token}`} : {}),
      ...options.headers,
    },
  });
  if (!response.ok) throw new Error((await response.json()).detail || 'Request failed');
  return response.json();
}

