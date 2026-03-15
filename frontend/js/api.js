const API_BASE = "/v1";

async function request(path, options = {}) {
  const { method = "GET", headers = {}, body, credentials = "include" } = options;

  const config = {
    method,
    headers: { Accept: "application/json", ...headers },
    credentials,
  };

  if (body !== undefined) {
    if (body instanceof FormData) {
      config.body = body;
    } else {
      config.body = JSON.stringify(body);
      config.headers["Content-Type"] = "application/json";
    }
  }

  const response = await fetch(`${API_BASE}${path}`, config);
  const contentType = response.headers.get("content-type") || "";

  let payload;
  if (contentType.includes("application/json")) {
    payload = await response.json();
  } else {
    payload = await response.text();
  }

  if (!response.ok) {
    const detail = typeof payload === "string" ? payload : payload?.detail || JSON.stringify(payload);
    throw new Error(`Request failed (${response.status}): ${detail}`);
  }

  return payload;
}

function createIdempotencyKey() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `run-${crypto.randomUUID()}`;
  }
  return `run-${Date.now()}-${Math.round(Math.random() * 100000)}`;
}

async function uploadResume({ file, candidateId, consentVersion }) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("candidate_id", candidateId);
  formData.append("consent_version", consentVersion);
  return request("/resumes/upload", { method: "POST", body: formData });
}

async function startParse(
  resumeId,
  { forceReparse = false, pipelineVersion = "2026.03", idempotencyKey = createIdempotencyKey() } = {}
) {
  return request(`/resumes/${resumeId}/parse`, {
    method: "POST",
    body: {
      force_reparse: forceReparse,
      pipeline_version: pipelineVersion,
      idempotency_key: idempotencyKey,
    },
  });
}

async function getParseJob(parseJobId) {
  return request(`/parse-jobs/${parseJobId}`);
}

async function getParsedResume(resumeId) {
  return request(`/resumes/${resumeId}/parsed`);
}

async function confirmResume(resumeId, payload) {
  return request(`/resumes/${resumeId}/confirm`, { method: "PATCH", body: payload });
}

async function generateInterviewQuestions(payload) {
  return request("/interviews/questions", { method: "POST", body: payload });
}

async function evaluateInterviewAnswer(payload) {
  return request("/interviews/evaluate", { method: "POST", body: payload });
}

async function getDashboardResults(resumeId, limit = 120) {
  return request(`/dashboard/${encodeURIComponent(resumeId)}?limit=${encodeURIComponent(limit)}`);
}

export const api = {
  createIdempotencyKey,
  uploadResume,
  startParse,
  getParseJob,
  getParsedResume,
  confirmResume,
  generateInterviewQuestions,
  evaluateInterviewAnswer,
  getDashboardResults,
};
