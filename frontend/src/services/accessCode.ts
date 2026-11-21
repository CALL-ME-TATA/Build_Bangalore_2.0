// The access code is passed in the page URL (`?code=...`, before the `#/` route) and forwarded to the
// server in `hello.access_code` and in the X-Access-Code header of REST calls.

export function accessCode(search: string = typeof location === 'undefined' ? '' : location.search): string | null {
  const code = new URLSearchParams(search).get('code');
  return code ? code : null;
}
