import { api } from "./api.js";
import { setSession, updateSession } from "./state.js";
import { appendEvent, byId, setProgress, setStatus, sleep } from "./ui.js";

const form = byId("uploadForm");
const statusMessage = byId("statusMessage");
const progressBar = byId("progressBar");
const statusList = byId("statusList");
const submitUpload = byId("submitUpload");

if (form) {
  form.addEventListener("submit", handleUpload);
}

async function handleUpload(event) {
  event.preventDefault();

  const candidateId = byId("candidateId")?.value.trim();
  const consentVersion = byId("consentVersion")?.value.trim();
  const file = byId("resumeFile")?.files?.[0];
  const forceReparse = Boolean(byId("forceReparse")?.checked);

  if (!candidateId || !consentVersion || !file) {
    setStatus(statusMessage, "Candidate ID, consent version, and file are required.", "warning");
    return;
  }

  const ext = (file.name.split(".").pop() || "").toLowerCase();
  if (!["pdf", "docx"].includes(ext)) {
    setStatus(statusMessage, "Only PDF and DOCX files are supported.", "warning");
    return;
  }

  submitUpload.disabled = true;
  setProgress(progressBar, 2);
  setStatus(statusMessage, "Uploading resume...", "info");
  appendEvent(statusList, `Uploading ${file.name}`);

  try {
    const upload = await api.uploadResume({ file, candidateId, consentVersion });
    setProgress(progressBar, 15);
    appendEvent(statusList, `Uploaded resume_id: ${upload.resume_id}`);

    setSession({
      resumeId: upload.resume_id,
      candidateId,
      consentVersion,
      latestFileName: file.name,
    });

    setStatus(statusMessage, "Starting parse job...", "info");
    const parse = await api.startParse(upload.resume_id, {
      forceReparse,
      idempotencyKey: api.createIdempotencyKey(),
    });

    appendEvent(statusList, `Parse job queued: ${parse.parse_job_id}`);
    updateSession({ parseJobId: parse.parse_job_id });

    await pollParseJob(parse.parse_job_id, upload.resume_id);
  } catch (error) {
    appendEvent(statusList, `Error: ${error.message}`);
    setStatus(statusMessage, error.message, "error");
  } finally {
    submitUpload.disabled = false;
  }
}

async function pollParseJob(parseJobId, resumeId) {
  let lastStage = "";

  for (let attempt = 0; attempt < 120; attempt += 1) {
    const job = await api.getParseJob(parseJobId);

    setProgress(progressBar, job.progress);
    setStatus(statusMessage, `${job.stage} (${job.progress}%)`, "info");

    if (job.stage && job.stage !== lastStage) {
      appendEvent(statusList, `Stage: ${job.stage}`);
      lastStage = job.stage;
    }

    if (job.status === "completed") {
      setProgress(progressBar, 100);
      setStatus(statusMessage, "Parse complete. Redirecting to dashboard...", "success");
      appendEvent(statusList, "Resume parsed successfully");
      updateSession({ parseStatus: "completed", resumeId });
      await sleep(1100);
      window.location.href = `./dashboard.html?resume_id=${encodeURIComponent(resumeId)}`;
      return;
    }

    if (job.status === "failed") {
      throw new Error(job.error || "Parse job failed");
    }

    await sleep(1500);
  }

  throw new Error("Parse timed out. Please check job status manually.");
}
