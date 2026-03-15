import { api } from "./api.js";
import { getSession, saveInterviewReport, updateSession } from "./state.js";
import { byId, formatPercent, getQueryParam, setStatus, toggleHidden } from "./ui.js";

const resumeIdInput = byId("resumeIdInput");
const startInterviewBtn = byId("startInterviewBtn");
const interviewStatus = byId("interviewStatus");

const interviewPanel = byId("interviewPanel");
const questionCounter = byId("questionCounter");
const roundProgress = byId("roundProgress");
const questionText = byId("questionText");
const answerInput = byId("answerInput");
const submitAnswerBtn = byId("submitAnswerBtn");
const skipQuestionBtn = byId("skipQuestionBtn");
const feedbackBox = byId("feedbackBox");

const runtime = {
  resumeId: "",
  sessionId: "",
  questions: [],
  index: 0,
  answers: [],
};

initialize();

function initialize() {
  const initialResumeId = getQueryParam("resume_id") || getSession().resumeId || "";
  resumeIdInput.value = initialResumeId;

  startInterviewBtn?.addEventListener("click", startInterview);
  submitAnswerBtn?.addEventListener("click", () => handleAnswer(false));
  skipQuestionBtn?.addEventListener("click", () => handleAnswer(true));
}

async function startInterview() {
  runtime.resumeId = resumeIdInput.value.trim();
  if (!runtime.resumeId) {
    setStatus(interviewStatus, "Please provide a resume ID.", "warning");
    return;
  }

  setStatus(interviewStatus, "Building questions from parsed resume...", "info");

  let parsed = null;
  try {
    parsed = await api.getParsedResume(runtime.resumeId);
  } catch {
    setStatus(interviewStatus, "Parsed resume not found. Using fallback starter questions.", "warning");
  }

  runtime.questions = await buildQuestionsWithApiFallback(parsed);
  runtime.index = 0;
  runtime.answers = [];
  runtime.sessionId = createSessionId();

  renderQuestion();
  toggleHidden(interviewPanel, false);
  setStatus(interviewStatus, "Interview in progress.", "success");
  updateSession({ resumeId: runtime.resumeId, interviewStarted: true });
}

async function buildQuestionsWithApiFallback(parsed) {
  try {
    const response = await api.generateInterviewQuestions({
      resume_id: runtime.resumeId,
      question_count: 6,
      parsed_profile: parsed?.profile || null,
    });

    const questions = normalizeQuestions(response);
    if (questions.length) {
      return questions;
    }
  } catch {
    // Fallback to local generation if interview API is not implemented yet.
  }

  return buildQuestions(parsed);
}

function normalizeQuestions(response) {
  const source = Array.isArray(response)
    ? response
    : Array.isArray(response?.questions)
      ? response.questions
      : [];

  return source
    .map((item) => {
      if (typeof item === "string") {
        return { topic: "general", prompt: item };
      }

      const prompt = item?.prompt || item?.question || item?.text || "";
      const topic = item?.topic || item?.category || "general";

      if (!prompt) return null;
      return { topic, prompt };
    })
    .filter(Boolean)
    .slice(0, 6);
}

function buildQuestions(parsed) {
  const questions = [];

  if (parsed?.profile?.skills?.length) {
    parsed.profile.skills.slice(0, 3).forEach((skill) => {
      questions.push({
        topic: skill.canonical || skill.raw,
        prompt: `Design and explain a small production-ready feature where ${skill.canonical || skill.raw} is central. Discuss architecture, tradeoffs, and testing.`,
      });
    });
  }

  if (parsed?.profile?.projects?.length) {
    parsed.profile.projects.slice(0, 2).forEach((project) => {
      questions.push({
        topic: project.name || "project",
        prompt: `Pick a hard technical decision from project \"${project.name || "unknown"}\". Why was that decision made and what alternative did you reject?`,
      });
    });
  }

  const fallback = [
    {
      topic: "system-design",
      prompt: "Design a service that ingests resumes, extracts entities asynchronously, and exposes status polling APIs. Include scaling and failure handling.",
    },
    {
      topic: "python",
      prompt: "In Python, when would you choose background workers over request-time processing for CPU-heavy tasks? Give examples.",
    },
    {
      topic: "databases",
      prompt: "How would you model candidate interview scores over time so that trends and weak areas can be queried efficiently?",
    },
    {
      topic: "testing",
      prompt: "Explain a practical test strategy for an AI interview evaluator that mixes deterministic rubric checks and LLM-based scoring.",
    },
  ];

  return questions.length ? questions.slice(0, 6) : fallback;
}

function renderQuestion() {
  const current = runtime.questions[runtime.index];
  if (!current) return;

  questionCounter.textContent = `Question ${runtime.index + 1} of ${runtime.questions.length}`;
  roundProgress.textContent = formatPercent(runtime.index / runtime.questions.length);
  questionText.textContent = current.prompt;
  answerInput.value = "";
  feedbackBox.textContent = "";
}

function analyzeAnswer(answer, topic, skipped) {
  if (skipped) {
    return {
      score: 0.1,
      feedback: "Question skipped. This usually indicates low confidence in this area.",
      weak: true,
    };
  }

  const cleaned = answer.trim();
  const wordCount = cleaned.split(/\s+/).filter(Boolean).length;
  const sentenceCount = cleaned.split(/[.!?]+/).filter((x) => x.trim()).length;

  const lengthScore = Math.min(wordCount / 130, 1);
  const structureScore = Math.min(sentenceCount / 7, 1);

  const keywordMap = {
    "system-design": ["scal", "queue", "retry", "cache", "latency"],
    python: ["async", "thread", "worker", "process", "context"],
    databases: ["index", "schema", "query", "transaction", "normal"],
    testing: ["unit", "integration", "mock", "regression", "coverage"],
  };

  const tokens = (keywordMap[topic] || ["tradeoff", "test", "performance", "error"])
    .map((token) => cleaned.toLowerCase().includes(token) ? 1 : 0)
    .reduce((sum, value) => sum + value, 0);

  const keywordScore = Math.min(tokens / 4, 1);
  const score = Number((lengthScore * 0.45 + structureScore * 0.25 + keywordScore * 0.3).toFixed(2));

  const weak = score < 0.55;
  const feedback = weak
    ? "Answer needs more depth. Add architecture details, concrete examples, and explicit tradeoffs."
    : "Good structure. To improve further, add one real production incident and what you changed after it.";

  return { score, feedback, weak };
}

async function handleAnswer(skipped) {
  const current = runtime.questions[runtime.index];
  if (!current) return;

  const answer = answerInput.value;
  if (!skipped && !answer.trim()) {
    feedbackBox.textContent = "Please write an answer or skip this question.";
    return;
  }

  const analysis = await evaluateAnswerWithFallback(current, answer, skipped);
  runtime.answers.push({
    question: current.prompt,
    topic: current.topic,
    answer,
    score: analysis.score,
    feedback: analysis.feedback,
    followUps: analysis.adaptiveFollowUpPrompts || [],
  });

  const followUpLine = (analysis.adaptiveFollowUpPrompts || []).length
    ? ` Suggested follow-up: ${analysis.adaptiveFollowUpPrompts[0]}`
    : "";
  feedbackBox.textContent = `Score: ${Math.round(analysis.score * 100)} / 100. ${analysis.feedback}${followUpLine}`;

  runtime.index += 1;
  if (runtime.index >= runtime.questions.length) {
    finishInterview();
    return;
  }

  renderQuestion();
}

async function evaluateAnswerWithFallback(current, answer, skipped) {
  try {
    const response = await api.evaluateInterviewAnswer({
      resume_id: runtime.resumeId,
      session_id: runtime.sessionId,
      question_id: `Q${String(runtime.index + 1).padStart(2, "0")}`,
      question: current.prompt,
      topic: current.topic,
      answer,
      skipped,
    });

    if (typeof response?.score === "number") {
      return {
        score: Math.max(0, Math.min(1, Number(response.score))),
        feedback: response.feedback || "Evaluation complete.",
        weak: Boolean(response.weak),
        adaptiveFollowUpPrompts: Array.isArray(response.adaptive_follow_up_prompts)
          ? response.adaptive_follow_up_prompts
          : [],
      };
    }
  } catch {
    // Local rubric fallback keeps the interview flow usable without backend interview APIs.
  }

  return analyzeAnswer(answer, current.topic, skipped);
}

function createSessionId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.round(Math.random() * 100000)}`;
}

function finishInterview() {
  const average = runtime.answers.reduce((sum, item) => sum + item.score, 0) / runtime.answers.length;
  const weakAreas = [...new Set(runtime.answers.filter((item) => item.score < 0.55).map((item) => item.topic))];

  const recommendations = weakAreas.length
    ? weakAreas.map((topic) => `Practice one focused exercise on ${topic} and answer out loud in under 3 minutes.`)
    : ["Maintain momentum: attempt one mixed mock interview per week and review rubric deltas."];

  const report = {
    resumeId: runtime.resumeId,
    completedAt: new Date().toISOString(),
    questionCount: runtime.answers.length,
    overallScore: Number(average.toFixed(2)),
    weakAreas,
    recommendations,
    answers: runtime.answers,
  };

  saveInterviewReport(runtime.resumeId, report);
  updateSession({ resumeId: runtime.resumeId, interviewCompleted: true, latestInterviewScore: report.overallScore });

  setStatus(interviewStatus, "Interview complete. Redirecting to dashboard...", "success");
  feedbackBox.textContent = `Final score: ${Math.round(report.overallScore * 100)} / 100`;

  setTimeout(() => {
    window.location.href = `./dashboard.html?resume_id=${encodeURIComponent(runtime.resumeId)}`;
  }, 1200);
}
