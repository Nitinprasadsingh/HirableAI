import { api } from "./api.js";
import { getInterviewReport, getSession, updateSession } from "./state.js";
import { byId, escapeHtml, formatPercent, getQueryParam, setStatus } from "./ui.js";

const dashboardResumeId = byId("dashboardResumeId");
const loadDashboardBtn = byId("loadDashboardBtn");
const dashboardStatus = byId("dashboardStatus");

const readinessScore = byId("readinessScore");
const readinessBand = byId("readinessBand");
const latestSessionScore = byId("latestSessionScore");
const latestSessionMeta = byId("latestSessionMeta");
const coverageScore = byId("coverageScore");
const coverageMeta = byId("coverageMeta");

const sessionSummaryList = byId("sessionSummaryList");
const profileSummary = byId("profileSummary");
const weakAreasList = byId("weakAreasList");
const studyPlanList = byId("studyPlanList");
const questionBreakdownBody = byId("questionBreakdownBody");
const feedbackTemplatesList = byId("feedbackTemplatesList");
const scoringBands = byId("scoringBands");
const apiContractPreview = byId("apiContractPreview");

let skillRadarChart = null;
let readinessTrendChart = null;

initialize();

function initialize() {
  const presetResumeId = getQueryParam("resume_id") || getSession().resumeId || "";
  dashboardResumeId.value = presetResumeId;

  loadDashboardBtn?.addEventListener("click", loadDashboard);

  if (presetResumeId) {
    loadDashboard();
  }
}

async function loadDashboard() {
  const resumeId = dashboardResumeId.value.trim();
  if (!resumeId) {
    setStatus(dashboardStatus, "Provide a resume ID before loading dashboard.", "warning");
    return;
  }

  setStatus(dashboardStatus, "Loading dashboard insights...", "info");

  try {
    const [dashboardData, parsed] = await Promise.all([
      api.getDashboardResults(resumeId, 120),
      api.getParsedResume(resumeId),
    ]);

    renderDashboard(dashboardData, parsed);

    updateSession({ resumeId, dashboardLoaded: true });
    setStatus(dashboardStatus, "Dashboard loaded.", "success");
  } catch (error) {
    try {
      const parsed = await api.getParsedResume(resumeId);
      const fallbackData = buildFallbackDashboard(resumeId, parsed, getInterviewReport(resumeId));
      renderDashboard(fallbackData, parsed);
      setStatus(dashboardStatus, "Loaded local fallback dashboard (aggregated API unavailable).", "warning");
    } catch {
      setStatus(dashboardStatus, error.message, "error");
    }
  }
}

function renderDashboard(data, parsed) {
  renderMetrics(data);
  renderSessionSummary(data.session_summary || []);
  renderProfile(parsed, data);
  renderWeakAreas(data.weak_areas || []);
  renderStudyPlan(data.recommended_study_plan || []);
  renderQuestionBreakdown(data.question_breakdown || []);
  renderSkillRadar(data.skill_radar || { labels: [], values: [] });
  renderTrend(data.trend || []);
  renderFeedbackTemplates(data.feedback_templates || []);
  renderScoringBands(data.scoring_bands || []);
  renderApiContractPreview(data);
}

function renderMetrics(data) {
  const latestSession = (data.session_summary || [])[0] || null;
  const coverage = latestSession?.question_count || 0;

  readinessScore.textContent = `${Math.round(Number(data.readiness_score_100) || 0)} / 100`;
  readinessBand.textContent = `Band: ${String(data.readiness_band || "unknown").toUpperCase()}`;

  latestSessionScore.textContent = latestSession
    ? `${Math.round(latestSession.avg_score_100 || 0)} / 100`
    : "No data";
  latestSessionMeta.textContent = latestSession
    ? `${latestSession.question_count} questions, ${latestSession.weak_area_count} weak areas`
    : "No completed session yet";

  coverageScore.textContent = String(coverage);
  coverageMeta.textContent = coverage ? "Questions in latest session" : "Session data unavailable";
}

function renderSessionSummary(summaryItems) {
  sessionSummaryList.innerHTML = "";
  if (!summaryItems.length) {
    sessionSummaryList.innerHTML = "<p>No session summaries available yet.</p>";
    return;
  }

  const lines = summaryItems.slice(0, 5).map((item, index) => {
    return `<p><strong>Session ${index + 1}:</strong> ${Math.round(item.readiness_score_100)} readiness, ${item.question_count} questions, ${item.weak_area_count} weak areas</p>`;
  });
  sessionSummaryList.innerHTML = lines.join("");
}

function renderProfile(parsed, dashboardData) {
  const profile = parsed.profile || {};

  const topSkills = (profile.skills || [])
    .slice(0, 6)
    .map((item) => `${escapeHtml(item.canonical || item.raw)} (${Math.round((item.confidence?.score || 0) * 100)}%)`)
    .join(", ");

  const items = [
    `<p><strong>Name:</strong> ${escapeHtml(profile.candidate_name || "Unknown")}</p>`,
    `<p><strong>Headline:</strong> ${escapeHtml(profile.headline || "Not available")}</p>`,
    `<p><strong>Experience entries:</strong> ${(profile.experience || []).length}</p>`,
    `<p><strong>Projects:</strong> ${(profile.projects || []).length}</p>`,
    `<p><strong>Education records:</strong> ${(profile.education || []).length}</p>`,
    `<p><strong>Top skills:</strong> ${topSkills || "No extracted skills"}</p>`,
    `<p><strong>Parser confidence:</strong> ${formatPercent(parsed.quality?.overall_confidence || 0)}</p>`,
    `<p><strong>Readiness:</strong> ${Math.round(dashboardData.readiness_score_100 || 0)} / 100 (${escapeHtml(dashboardData.readiness_band || "unknown")})</p>`,
  ];

  profileSummary.innerHTML = items.join("");
}

function renderWeakAreas(weakAreas) {
  weakAreasList.innerHTML = "";

  if (!weakAreas.length) {
    weakAreasList.innerHTML = "<li>No major weak areas detected yet.</li>";
    return;
  }

  weakAreas.forEach((item) => {
    const li = document.createElement("li");
    const evidence = (item.evidence_points || []).slice(0, 2).join(" | ");
    li.textContent = `${item.topic} (${item.severity}) - avg ${Math.round(item.avg_score_100)} / 100, seen ${item.frequency}x${evidence ? `. Evidence: ${evidence}` : ""}`;
    weakAreasList.appendChild(li);
  });
}

function renderStudyPlan(planItems) {
  studyPlanList.innerHTML = "";
  if (!planItems.length) {
    studyPlanList.innerHTML = "<li>Study plan unavailable.</li>";
    return;
  }

  planItems.forEach((item) => {
    const li = document.createElement("li");
    li.textContent = `[${item.priority}] ${item.title}: ${item.action} (${item.estimated_days} days)`;
    studyPlanList.appendChild(li);
  });
}

function renderQuestionBreakdown(items) {
  questionBreakdownBody.innerHTML = "";
  if (!items.length) {
    questionBreakdownBody.innerHTML = "<tr><td colspan=\"5\">No question breakdown available yet.</td></tr>";
    return;
  }

  items.slice(0, 20).forEach((item) => {
    const row = document.createElement("tr");
    row.innerHTML = [
      `<td>${escapeHtml(item.question)}</td>`,
      `<td>${escapeHtml(item.topic || "general")}</td>`,
      `<td>${Math.round(item.score_100 || 0)} / 100</td>`,
      `<td>${escapeHtml(item.verdict || "unknown")}</td>`,
      `<td>${escapeHtml((item.missed_key_points || []).slice(0, 2).join("; ") || "-" )}</td>`,
    ].join("");
    if (item.is_weak) {
      row.classList.add("row-weak");
    }
    questionBreakdownBody.appendChild(row);
  });
}

function renderSkillRadar(radar) {
  const canvas = byId("skillRadarChart");
  if (!canvas) return;

  const labels = radar.labels || [];
  const values = radar.values || [];

  if (skillRadarChart) {
    skillRadarChart.destroy();
    skillRadarChart = null;
  }

  if (!labels.length || typeof Chart === "undefined") {
    const context = canvas.getContext("2d");
    if (context) {
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#64748b";
      context.font = "16px Manrope";
      context.fillText("No skill data available", 20, 40);
    }
    return;
  }

  skillRadarChart = new Chart(canvas, {
    type: "radar",
    data: {
      labels,
      datasets: [
        {
          label: "Skill Readiness",
          data: values,
          borderWidth: 2,
          borderColor: "#0f766e",
          pointBackgroundColor: "#0f766e",
          backgroundColor: "rgba(15, 118, 110, 0.22)",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        r: {
          beginAtZero: true,
          max: 100,
          grid: { color: "rgba(15, 118, 110, 0.16)" },
          angleLines: { color: "rgba(15, 118, 110, 0.16)" },
        },
      },
    },
  });
}

function renderTrend(points) {
  const canvas = byId("trendChart");
  if (!canvas) return;

  if (readinessTrendChart) {
    readinessTrendChart.destroy();
    readinessTrendChart = null;
  }

  if (!points.length || typeof Chart === "undefined") {
    const context = canvas.getContext("2d");
    if (context) {
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = "#64748b";
      context.font = "16px Manrope";
      context.fillText("No trend data yet", 20, 40);
    }
    return;
  }

  readinessTrendChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: points.map((item, idx) => `S${idx + 1}`),
      datasets: [
        {
          label: "Readiness",
          data: points.map((item) => item.readiness_score_100),
          borderColor: "#0f766e",
          backgroundColor: "rgba(15, 118, 110, 0.15)",
          tension: 0.3,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
      },
      scales: {
        y: {
          beginAtZero: true,
          max: 100,
          grid: { color: "rgba(15, 118, 110, 0.15)" },
        },
      },
    },
  });
}

function renderFeedbackTemplates(templates) {
  feedbackTemplatesList.innerHTML = "";
  (templates || []).slice(0, 10).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    feedbackTemplatesList.appendChild(li);
  });
}

function renderScoringBands(bands) {
  if (!bands.length) {
    scoringBands.innerHTML = "<p>Bands unavailable.</p>";
    return;
  }

  const markup = bands.map((band) => {
    return `<p><strong>${escapeHtml(String(band.label).toUpperCase())}</strong> (${Math.round(band.min_score)}-${Math.round(band.max_score)}): ${escapeHtml(band.meaning)}</p>`;
  });
  scoringBands.innerHTML = markup.join("");
}

function renderApiContractPreview(data) {
  const preview = {
    resume_id: data.resume_id,
    candidate_name: data.candidate_name,
    target_role: data.target_role,
    readiness_score_100: data.readiness_score_100,
    readiness_band: data.readiness_band,
    session_summary: (data.session_summary || []).slice(0, 1),
    skill_radar: data.skill_radar,
    question_breakdown: (data.question_breakdown || []).slice(0, 1),
    weak_areas: (data.weak_areas || []).slice(0, 2),
    trend: (data.trend || []).slice(0, 3),
    recommended_study_plan: (data.recommended_study_plan || []).slice(0, 2),
  };
  apiContractPreview.textContent = JSON.stringify(preview, null, 2);
}

function buildFallbackDashboard(resumeId, parsed, report) {
  const localAnswers = report?.answers || [];
  const readiness = Math.round((report?.overallScore || 0) * 100);
  const weakAreas = (report?.weakAreas || []).map((topic) => ({
    topic,
    severity: "high",
    avg_score_100: 52,
    frequency: 1,
    evidence_points: ["Local report fallback"],
  }));

  const skillLabels = (parsed?.profile?.skills || []).slice(0, 6).map((item) => item.canonical || item.raw);
  const skillValues = (parsed?.profile?.skills || []).slice(0, 6).map((item) => Math.round((item.confidence?.score || 0) * 100));

  return {
    resume_id: resumeId,
    candidate_name: parsed?.profile?.candidate_name || "Candidate",
    target_role: inferTargetRoleFromParsed(parsed),
    readiness_score_100: readiness || Math.round((parsed?.quality?.overall_confidence || 0) * 100),
    readiness_band: readiness >= 78 ? "ready" : readiness >= 55 ? "intermediate" : "beginner",
    scoring_bands: [
      { label: "beginner", min_score: 0, max_score: 54, meaning: "Build strong foundations and response structure." },
      { label: "intermediate", min_score: 55, max_score: 77, meaning: "Improve tradeoff reasoning and precision." },
      { label: "ready", min_score: 78, max_score: 100, meaning: "Consistent interview-ready performance." },
    ],
    session_summary: [
      {
        session_id: "local-session",
        completed_at: report?.completedAt || new Date().toISOString(),
        question_count: report?.questionCount || localAnswers.length,
        avg_score_100: readiness || 0,
        readiness_score_100: readiness || 0,
        readiness_band: readiness >= 78 ? "ready" : readiness >= 55 ? "intermediate" : "beginner",
        weak_area_count: weakAreas.length,
      },
    ],
    skill_radar: {
      labels: skillLabels.length ? skillLabels : ["Fundamentals", "Reasoning", "Communication"],
      values: skillValues.length ? skillValues : [45, 50, 48],
    },
    question_breakdown: localAnswers.map((item, idx) => ({
      evaluation_id: `local-${idx + 1}`,
      session_id: "local-session",
      question_id: `Q${String(idx + 1).padStart(2, "0")}`,
      question: item.question,
      topic: item.topic,
      score_100: Math.round((item.score || 0) * 100),
      verdict: (item.score || 0) >= 0.78 ? "strong" : (item.score || 0) >= 0.55 ? "average" : "weak",
      is_weak: (item.score || 0) < 0.55,
      missed_key_points: [],
      coaching: item.feedback || "Add clearer tradeoffs and concrete validation metrics.",
      created_at: report?.completedAt || new Date().toISOString(),
    })),
    weak_areas: weakAreas,
    trend: [
      {
        session_id: "local-session",
        completed_at: report?.completedAt || new Date().toISOString(),
        readiness_score_100: readiness || 0,
        avg_score_100: readiness || 0,
      },
    ],
    recommended_study_plan: (report?.recommendations || ["Run one focused mock interview and review weak answers."]).map((item, idx) => ({
      priority: idx === 0 ? "P1" : idx === 1 ? "P2" : "P3",
      title: `Study Action ${idx + 1}`,
      action: item,
      rationale: "Generated from local interview report.",
      estimated_days: idx === 0 ? 4 : idx === 1 ? 6 : 8,
    })),
    feedback_templates: [
      "Open with one-line architecture summary before details.",
      "State one explicit tradeoff and why you accepted it.",
      "Add one failure mode and mitigation to every design answer.",
      "Anchor your reasoning with one metric to validate success.",
      "Use assumptions first, then approach, then validation.",
      "Compare at least two alternatives before picking one.",
      "Mention rollout safety: canary, monitoring, rollback trigger.",
      "Reduce vague wording by naming specific components and flows.",
      "For debugging questions, rank hypotheses before deep diving.",
      "Close with what you would improve in the next iteration.",
    ],
  };
}

function inferTargetRoleFromParsed(parsed) {
  const profile = parsed?.profile || {};
  const headline = String(profile.headline || "").trim();
  if (headline && headline.length <= 80) return headline;

  const firstExperienceTitle = String(profile.experience?.[0]?.title || "").trim();
  if (firstExperienceTitle) return firstExperienceTitle;

  const firstProjectRole = String(profile.projects?.[0]?.role || "").trim();
  if (firstProjectRole) return firstProjectRole;

  return "Software Engineer";
}
