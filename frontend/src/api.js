// API client — all backend calls in one module.
// Every call now takes an accessToken (the Supabase session's JWT) and
// attaches it as a Bearer token; /analyze and /roadmap reject requests
// without one.

async function jsonOrThrow(resp) {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try { detail = (await resp.json()).detail ?? detail; } catch { /* keep */ }
    throw new Error(detail);
  }
  return resp.json();
}

function authHeader(accessToken) {
  return accessToken ? { Authorization: `Bearer ${accessToken}` } : {};
}

export async function fetchRoles() {
  const data = await jsonOrThrow(await fetch('/api/roles'));
  return data.roles;
}

export async function analyze({ role, resumeText, resumeFile, githubUsername, accessToken }) {
  const form = new FormData();
  form.append('role', role);
  if (resumeFile) form.append('resume_file', resumeFile);
  if (resumeText) form.append('resume_text', resumeText);
  if (githubUsername) form.append('github_username', githubUsername);
  return jsonOrThrow(await fetch('/api/analyze', {
    method: 'POST', body: form, headers: authHeader(accessToken),
  }));
}

export async function getRoadmap({ role, resumeSkills, githubSkills, nWeeks = 6, accessToken }) {
  return jsonOrThrow(await fetch('/api/roadmap', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader(accessToken) },
    body: JSON.stringify({
      role, resume_skills: resumeSkills, github_skills: githubSkills ?? null, n_weeks: nWeeks,
    }),
  }));
}

export async function saveAnalysis({ role, report, accessToken }) {
  return jsonOrThrow(await fetch('/api/analyses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeader(accessToken) },
    body: JSON.stringify({ role, report }),
  }));
}

export async function listSavedAnalyses({ accessToken }) {
  return jsonOrThrow(await fetch('/api/analyses', { headers: authHeader(accessToken) }));
}
