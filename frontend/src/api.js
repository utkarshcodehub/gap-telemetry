// API client — all backend calls in one module.
// Every call now takes an accessToken (the Supabase session's JWT) and
// attaches it as a Bearer token; /analyze and /roadmap reject requests
// without one.

async function jsonOrThrow(resp) {
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (Array.isArray(body.detail)) {
        // FastAPI/Pydantic validation errors: [{type, loc, msg}, ...]
        detail = body.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
      } else if (typeof body.detail === 'string') {
        detail = body.detail;
      } else if (body.detail) {
        detail = JSON.stringify(body.detail);
      }
    } catch { /* keep default */ }
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

export async function getSavedAnalysis(id, { accessToken }) {
  return jsonOrThrow(await fetch(`/api/analyses/${id}`, { headers: authHeader(accessToken) }));
}

export async function deleteSavedAnalysis(id, { accessToken }) {
  return jsonOrThrow(await fetch(`/api/analyses/${id}`, {
    method: 'DELETE', headers: authHeader(accessToken),
  }));
}

export async function fetchListings() {
  return jsonOrThrow(await fetch('/api/listings'));
}

export async function fetchListing(listingId) {
  return jsonOrThrow(await fetch(`/api/listings/${listingId}`));
}

export async function checkRoleFit({ listingId, resumeText, resumeFile, academicMarks, accessToken }) {
  const form = new FormData();
  form.append('listing_id', listingId);
  if (resumeFile) form.append('resume_file', resumeFile);
  if (resumeText) form.append('resume_text', resumeText);
  if (academicMarks) form.append('academic_marks', academicMarks);
  return jsonOrThrow(await fetch('/api/role-fit', {
    method: 'POST', body: form, headers: authHeader(accessToken),
  }));
}
