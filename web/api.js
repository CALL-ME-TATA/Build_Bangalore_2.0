// Read-only HTTP calls for the Khata screen.

async function getJson(path) {
  const code = new URLSearchParams(location.search).get('code');
  const res = await fetch(path, { cache: 'no-store', headers: code ? { 'X-Access-Code': code } : {} });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

/** @returns {Promise<{customers:Array, entries:Array, totals:{credit_today:number,payment_today:number}}>} */
export async function loadKhata() {
  const [c, l] = await Promise.all([getJson('/api/customers'), getJson('/api/ledger?limit=20')]);
  return {
    customers: c.customers || [],
    entries: l.entries || [],
    totals: l.totals || { credit_today: 0, payment_today: 0 },
  };
}
