// Supabase client — the ONLY place this project talks to Supabase directly.
// The backend never sees these values; it only ever verifies the JWTs
// this client's sessions produce, against the project's public JWKS.

import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // eslint-disable-next-line no-console
  console.warn(
    'VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set. ' +
    'Copy frontend/.env.example to frontend/.env and fill in your ' +
    'Supabase project values — auth will not work until then.'
  );
}

export const supabase = createClient(url ?? '', anonKey ?? '');
