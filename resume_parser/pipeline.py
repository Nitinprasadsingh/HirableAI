from __future__ import annotations

import re
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .config import settings
from .schemas import (
    Confidence,
    ConfidenceSignals,
    EducationItem,
    ExperienceItem,
    ParsedResume,
    Profile,
    ProjectItem,
    Quality,
    ReviewField,
    Skill,
    SourceMetadata,
    Tool,
)


SKILL_TAXONOMY: dict[str, dict[str, Any]] = {
    "python": {"aliases": ["python", "py"], "category": "backend"},
    "java": {"aliases": ["java"], "category": "backend"},
    "javascript": {"aliases": ["javascript", "js"], "category": "frontend"},
    "typescript": {"aliases": ["typescript", "ts"], "category": "frontend"},
    "node.js": {"aliases": ["node", "nodejs", "node.js"], "category": "backend"},
    "react": {"aliases": ["react", "react.js", "reactjs"], "category": "frontend"},
    "next.js": {"aliases": ["next", "nextjs", "next.js"], "category": "frontend"},
    "postgresql": {"aliases": ["postgres", "postgresql", "postgre"], "category": "database"},
    "mysql": {"aliases": ["mysql"], "category": "database"},
    "redis": {"aliases": ["redis"], "category": "database"},
    "fastapi": {"aliases": ["fastapi"], "category": "backend"},
    "django": {"aliases": ["django"], "category": "backend"},
    "flask": {"aliases": ["flask"], "category": "backend"},
    "docker": {"aliases": ["docker"], "category": "devops"},
    "kubernetes": {"aliases": ["kubernetes", "k8s"], "category": "devops"},
    "aws": {"aliases": ["aws", "amazon web services"], "category": "cloud"},
    "azure": {"aliases": ["azure"], "category": "cloud"},
    "gcp": {"aliases": ["gcp", "google cloud"], "category": "cloud"},
    "kafka": {"aliases": ["kafka"], "category": "data"},
}

TOOL_CANONICAL = {"docker", "kubernetes", "aws", "azure", "gcp", "kafka", "redis"}

SECTION_ALIASES = {
    "summary": ["summary", "profile", "objective"],
    "skills": ["skills", "technical skills", "core skills", "competencies"],
    "experience": ["experience", "work experience", "professional experience", "employment"],
    "projects": ["projects", "personal projects", "selected projects"],
    "education": ["education", "academics", "academic background"],
    "certifications": ["certifications", "licenses"],
    "tools": ["tools", "technologies", "tech stack"],
}

MONTH_PATTERN = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
DATE_RANGE_RE = re.compile(
    rf"(?P<start>{MONTH_PATTERN}?\s*\d{{4}})\s*(?:-|to|\u2013)\s*(?P<end>Present|Current|{MONTH_PATTERN}?\s*\d{{4}})",
    re.IGNORECASE,
)
YEAR_RANGE_RE = re.compile(r"(?P<start>\d{4})\s*(?:-|to|\u2013)\s*(?P<end>Present|Current|\d{4})", re.IGNORECASE)


@dataclass
class ExtractionResult:
    text: str
    pages: int
    extractor: str
    ocr_used: bool


class ResumeParsingPipeline:
    def parse_resume(self, resume_id: UUID, file_path: Path, file_type: str) -> ParsedResume:
        extraction = self._extract_text(file_path=file_path, file_type=file_type)
        cleaned_text = self._clean_text(extraction.text)
        sections = self._detect_sections(cleaned_text)

        candidate_name, headline = self._extract_identity(cleaned_text)
        skills, tools = self._extract_skills_and_tools(cleaned_text, sections)
        experience = self._extract_experience(sections, skills)
        projects = self._extract_projects(sections, skills)
        education = self._extract_education(sections)

        (
            skills,
            tools,
            experience,
            projects,
            duplicate_groups_resolved,
        ) = self._resolve_duplicates(skills, tools, experience, projects)

        fields_needing_review = self._collect_review_fields(skills, tools, experience, projects, education)

        all_scores = [
            *(item.confidence.score for item in skills),
            *(item.confidence.score for item in tools),
            *(item.confidence.score for item in experience),
            *(item.confidence.score for item in projects),
            *(item.confidence.score for item in education),
        ]
        overall_confidence = round(sum(all_scores) / len(all_scores), 4) if all_scores else 0.5

        status = "needs_review" if fields_needing_review else "parsed"

        return ParsedResume(
            resume_id=resume_id,
            version=1,
            status=status,
            source=SourceMetadata(
                file_type=file_type,
                pages=max(1, extraction.pages),
                extractor=extraction.extractor,
                ocr_used=extraction.ocr_used,
            ),
            profile=Profile(
                candidate_name=candidate_name,
                headline=headline,
                skills=skills,
                tools=tools,
                experience=experience,
                projects=projects,
                education=education,
            ),
            quality=Quality(
                overall_confidence=overall_confidence,
                fields_needing_review=fields_needing_review,
                duplicate_groups_resolved=duplicate_groups_resolved,
            ),
        )

    def _extract_text(self, file_path: Path, file_type: str) -> ExtractionResult:
        if file_type == "docx":
            return self._extract_docx(file_path)
        if file_type == "pdf":
            return self._extract_pdf(file_path)
        raise ValueError("unsupported_file_type")

    def _extract_docx(self, file_path: Path) -> ExtractionResult:
        try:
            docx_module = importlib.import_module("docx")
            document = docx_module.Document(str(file_path))
            text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())
            if text.strip():
                return ExtractionResult(text=text, pages=1, extractor="python-docx", ocr_used=False)
        except Exception:
            pass

        try:
            docx2txt = importlib.import_module("docx2txt")
            text = docx2txt.process(str(file_path)) or ""
            return ExtractionResult(text=text, pages=1, extractor="docx2txt", ocr_used=False)
        except Exception as exc:
            raise RuntimeError(f"docx_extraction_failed: {exc}") from exc

    def _extract_pdf(self, file_path: Path) -> ExtractionResult:
        # Fast path for digital PDFs.
        try:
            fitz = importlib.import_module("fitz")
            with fitz.open(str(file_path)) as doc:
                pages = doc.page_count
                text = "\n".join(page.get_text("text") for page in doc)
            if self._has_sufficient_text(text):
                return ExtractionResult(text=text, pages=pages, extractor="pymupdf", ocr_used=False)
        except Exception:
            pass

        try:
            pypdf = importlib.import_module("pypdf")
            reader = pypdf.PdfReader(str(file_path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if self._has_sufficient_text(text):
                return ExtractionResult(text=text, pages=max(1, len(reader.pages)), extractor="pypdf", ocr_used=False)
        except Exception:
            pass

        ocr_text, pages = self._ocr_pdf(file_path)
        if not ocr_text.strip():
            raise RuntimeError("pdf_extraction_failed")
        return ExtractionResult(text=ocr_text, pages=pages, extractor="tesseract", ocr_used=True)

    def _ocr_pdf(self, file_path: Path) -> tuple[str, int]:
        try:
            convert_from_path = importlib.import_module("pdf2image").convert_from_path
            pytesseract = importlib.import_module("pytesseract")
            images = convert_from_path(str(file_path), dpi=220)
            ocr_text = []
            for image in images:
                ocr_text.append(pytesseract.image_to_string(image))
            return "\n".join(ocr_text), max(1, len(images))
        except Exception:
            return "", 1

    def _has_sufficient_text(self, text: str) -> bool:
        return len(re.sub(r"\s+", "", text)) > 200

    def _clean_text(self, text: str) -> str:
        text = text.replace("\u2022", "-")
        text = text.replace("\u00a0", " ")
        text = re.sub(r"\r\n?", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()

    def _detect_sections(self, text: str) -> dict[str, str]:
        sections: dict[str, list[str]] = {key: [] for key in SECTION_ALIASES}
        current_section = "summary"

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            candidate = self._match_section_header(line)
            if candidate:
                current_section = candidate
                continue
            sections[current_section].append(line)

        return {key: "\n".join(value).strip() for key, value in sections.items()}

    def _match_section_header(self, line: str) -> str | None:
        normalized = re.sub(r"[:\-]", "", line).strip().lower()
        if len(normalized.split()) > 4:
            return None
        for section, aliases in SECTION_ALIASES.items():
            if normalized in aliases:
                return section
        return None

    def _extract_identity(self, text: str) -> tuple[str | None, str | None]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None, None

        name = lines[0] if 1 < len(lines[0].split()) <= 4 else None
        headline = lines[1] if len(lines) > 1 and len(lines[1]) < 120 else None
        return name, headline

    def _extract_skills_and_tools(
        self,
        text: str,
        sections: dict[str, str],
    ) -> tuple[list[Skill], list[Tool]]:
        skills_section = "\n".join(
            block for key, block in sections.items() if key in {"skills", "tools", "projects", "experience"}
        )
        lower_skills_section = skills_section.lower()
        lower_text = text.lower()

        skills: list[Skill] = []
        tools: list[Tool] = []

        for canonical, info in SKILL_TAXONOMY.items():
            aliases = info["aliases"]
            found_raw = None
            mentioned_in_skills = False
            mentioned_global = False

            for alias in aliases:
                if self._contains_alias(lower_skills_section, alias.lower()):
                    found_raw = alias
                    mentioned_in_skills = True
                if self._contains_alias(lower_text, alias.lower()):
                    found_raw = found_raw or alias
                    mentioned_global = True

            if not mentioned_global:
                continue

            confidence = self._build_confidence(
                source_quality=0.92,
                section_match=0.95 if mentioned_in_skills else 0.72,
                pattern_validity=0.90,
                cross_field_consistency=0.88,
                model_certainty=0.85,
                evidence=[f"Found alias '{found_raw}'"],
            )

            if canonical in TOOL_CANONICAL:
                tools.append(
                    Tool(
                        raw=found_raw or canonical,
                        canonical=canonical,
                        confidence=confidence,
                    )
                )
            else:
                skills.append(
                    Skill(
                        raw=found_raw or canonical,
                        canonical=canonical,
                        category=info["category"],
                        confidence=confidence,
                    )
                )

        return skills, tools

    def _extract_experience(self, sections: dict[str, str], skills: list[Skill]) -> list[ExperienceItem]:
        text = sections.get("experience", "")
        if not text:
            return []

        blocks = self._split_experience_entries(text)
        results: list[ExperienceItem] = []
        known_skills = [item.canonical for item in skills]

        for block in blocks:
            lines = [line.strip("- ").strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            first_line = lines[0]
            title, company = self._split_title_company(first_line)
            start_date, end_date, is_current = self._extract_dates(block)

            summary = " ".join(lines[1:]) if len(lines) > 1 else ""
            block_lower = block.lower()
            skills_used = [skill for skill in known_skills if re.search(rf"\b{re.escape(skill)}\b", block_lower)]

            confidence = self._build_confidence(
                source_quality=0.9,
                section_match=0.93,
                pattern_validity=0.9 if start_date else 0.65,
                cross_field_consistency=0.9 if company and title else 0.7,
                model_certainty=0.84,
                evidence=[first_line],
            )

            results.append(
                ExperienceItem(
                    company=company,
                    title=title,
                    start_date=start_date or "unknown",
                    end_date=end_date,
                    is_current=is_current,
                    summary=summary,
                    skills_used=skills_used,
                    confidence=confidence,
                )
            )

        return results

    def _extract_projects(self, sections: dict[str, str], skills: list[Skill]) -> list[ProjectItem]:
        text = sections.get("projects", "")
        if not text:
            return []

        blocks = [block.strip() for block in re.split(r"\n\n+", text) if block.strip()]
        results: list[ProjectItem] = []
        known_skills = [item.canonical for item in skills]

        for block in blocks:
            lines = [line.strip("- ").strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            first_line = lines[0]
            name, role = self._split_project_role(first_line)
            description = " ".join(lines[1:]) if len(lines) > 1 else first_line

            impact = None
            for sentence in re.split(r"(?<=[.!?])\s+", description):
                if re.search(r"\d+%|\d+x|reduced|improved|increased", sentence, re.IGNORECASE):
                    impact = sentence
                    break

            block_lower = block.lower()
            tech_stack = [skill for skill in known_skills if re.search(rf"\b{re.escape(skill)}\b", block_lower)]

            confidence = self._build_confidence(
                source_quality=0.89,
                section_match=0.94,
                pattern_validity=0.86,
                cross_field_consistency=0.86,
                model_certainty=0.82,
                evidence=[name],
            )

            results.append(
                ProjectItem(
                    name=name,
                    role=role,
                    description=description,
                    impact=impact,
                    tech_stack=tech_stack,
                    confidence=confidence,
                )
            )

        return results

    def _extract_education(self, sections: dict[str, str]) -> list[EducationItem]:
        text = sections.get("education", "")
        if not text:
            return []

        blocks = [block.strip() for block in re.split(r"\n\n+", text) if block.strip()]
        results: list[EducationItem] = []

        for block in blocks:
            lines = [line.strip("- ").strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue

            institution = self._find_institution(lines)
            degree, field = self._find_degree_and_field(block)
            start_date, end_date, _ = self._extract_dates(block)
            gpa_match = re.search(r"(?:GPA|CGPA)[:\s]+([0-9.]+/?[0-9.]*)", block, re.IGNORECASE)

            confidence = self._build_confidence(
                source_quality=0.94,
                section_match=0.96,
                pattern_validity=0.94 if degree else 0.72,
                cross_field_consistency=0.92 if institution else 0.7,
                model_certainty=0.86,
                evidence=[institution, degree],
            )

            results.append(
                EducationItem(
                    institution=institution or "unknown",
                    degree=degree or "unknown",
                    field=field,
                    start_date=start_date,
                    end_date=end_date,
                    gpa=gpa_match.group(1) if gpa_match else None,
                    confidence=confidence,
                )
            )

        return results

    def _split_title_company(self, first_line: str) -> tuple[str, str]:
        line = self._strip_dates_from_line(first_line)
        match = re.search(r"(?P<title>.+?)\s+(?:at|@)\s+(?P<company>.+)", line, re.IGNORECASE)
        if match:
            title = match.group("title").strip(" -|,")
            company = match.group("company").strip(" -|,")
            return title, company

        parts = [part.strip(" -|,") for part in re.split(r"\||,", line) if part.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
        return line.strip(" -|,"), "unknown"

    def _split_project_role(self, first_line: str) -> tuple[str, str | None]:
        parts = [part.strip() for part in re.split(r"\||-", first_line) if part.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
        return first_line, None

    def _extract_dates(self, text: str) -> tuple[str | None, str | None, bool]:
        match = DATE_RANGE_RE.search(text) or YEAR_RANGE_RE.search(text)
        if not match:
            return None, None, False

        start = self._normalize_date_fragment(match.group("start"))
        raw_end = match.group("end")
        is_current = raw_end.lower() in {"present", "current"}
        end = None if is_current else self._normalize_date_fragment(raw_end)
        return start, end, is_current

    def _normalize_date_fragment(self, token: str) -> str:
        token = re.sub(r"\s+", " ", token).strip()
        month_map = {
            "jan": "01",
            "feb": "02",
            "mar": "03",
            "apr": "04",
            "may": "05",
            "jun": "06",
            "jul": "07",
            "aug": "08",
            "sep": "09",
            "oct": "10",
            "nov": "11",
            "dec": "12",
        }
        match = re.search(r"([A-Za-z]{3,9})\s*(\d{4})", token)
        if match:
            month = month_map.get(match.group(1)[:3].lower(), "01")
            return f"{match.group(2)}-{month}"
        year_match = re.search(r"\d{4}", token)
        if year_match:
            return f"{year_match.group(0)}-01"
        return token

    def _find_institution(self, lines: list[str]) -> str | None:
        institution_regex = re.compile(r"([A-Za-z][A-Za-z&.\- ]*(?:university|college|institute|school))", re.IGNORECASE)

        for line in lines:
            match = institution_regex.search(line)
            if match:
                return match.group(1).strip(" ,")

        for line in lines:
            if re.search(r"university|college|institute|school", line, re.IGNORECASE):
                parts = [part.strip() for part in line.split(",") if part.strip()]
                for part in parts:
                    if re.search(r"university|college|institute|school", part, re.IGNORECASE):
                        return part.strip(" ,")
                return re.sub(r"\b\d{4}\b.*$", "", line).strip(" ,")
        return lines[0] if lines else None

    def _contains_alias(self, text: str, alias: str) -> bool:
        if len(alias) <= 2:
            # Short aliases like js/ts/py should match as standalone tokens only.
            tokens = [token for token in re.split(r"[^a-z0-9.+#-]+", text.lower()) if token]
            return alias in tokens
        pattern = re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE)
        return bool(pattern.search(text))

    def _split_experience_entries(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        entries: list[list[str]] = []
        current: list[str] = []

        for line in lines:
            if self._is_experience_header(line) and current:
                entries.append(current)
                current = [line]
            else:
                current.append(line)

        if current:
            entries.append(current)

        return ["\n".join(entry).strip() for entry in entries if entry]

    def _is_experience_header(self, line: str) -> bool:
        if line.startswith("-"):
            return False
        if not (DATE_RANGE_RE.search(line) or YEAR_RANGE_RE.search(line)):
            return False
        return bool(re.search(r"\b(?:at|@)\b|\||,", line, re.IGNORECASE))

    def _strip_dates_from_line(self, line: str) -> str:
        stripped = DATE_RANGE_RE.sub("", line)
        stripped = YEAR_RANGE_RE.sub("", stripped)
        stripped = re.sub(r"\s{2,}", " ", stripped)
        return stripped.strip(" -|,")

    def _find_degree_and_field(self, block: str) -> tuple[str | None, str | None]:
        degree_pattern = re.search(
            r"(B\.?Tech|M\.?Tech|B\.?E\.?|M\.?S\.?|B\.?Sc\.?|M\.?Sc\.?|MBA|Ph\.?D|Bachelor|Master)",
            block,
            re.IGNORECASE,
        )
        field_pattern = re.search(
            r"(?:in|of)\s+([A-Za-z& ]{3,40})(?:,|$|\n)",
            block,
            re.IGNORECASE,
        )
        degree = degree_pattern.group(1) if degree_pattern else None
        field = field_pattern.group(1).strip() if field_pattern else None
        return degree, field

    def _resolve_duplicates(
        self,
        skills: list[Skill],
        tools: list[Tool],
        experience: list[ExperienceItem],
        projects: list[ProjectItem],
    ) -> tuple[list[Skill], list[Tool], list[ExperienceItem], list[ProjectItem], int]:
        duplicate_groups = 0

        deduped_skills: dict[str, Skill] = {}
        for item in skills:
            existing = deduped_skills.get(item.canonical)
            if not existing:
                deduped_skills[item.canonical] = item
                continue
            duplicate_groups += 1
            if item.confidence.score > existing.confidence.score:
                item.confidence.evidence.extend(existing.confidence.evidence)
                deduped_skills[item.canonical] = item
            else:
                existing.confidence.evidence.extend(item.confidence.evidence)

        deduped_tools: dict[str, Tool] = {}
        for item in tools:
            existing = deduped_tools.get(item.canonical)
            if not existing:
                deduped_tools[item.canonical] = item
                continue
            duplicate_groups += 1
            if item.confidence.score > existing.confidence.score:
                item.confidence.evidence.extend(existing.confidence.evidence)
                deduped_tools[item.canonical] = item
            else:
                existing.confidence.evidence.extend(item.confidence.evidence)

        deduped_experience: dict[str, ExperienceItem] = {}
        for item in experience:
            key = f"{item.company.lower()}::{item.title.lower()}::{item.start_date}"
            existing = deduped_experience.get(key)
            if not existing:
                deduped_experience[key] = item
                continue
            duplicate_groups += 1
            if item.confidence.score > existing.confidence.score:
                deduped_experience[key] = item

        deduped_projects: dict[str, ProjectItem] = {}
        for item in projects:
            key = re.sub(r"\W+", "", item.name.lower())
            existing = deduped_projects.get(key)
            if not existing:
                deduped_projects[key] = item
                continue
            duplicate_groups += 1
            if item.confidence.score > existing.confidence.score:
                deduped_projects[key] = item

        return (
            list(deduped_skills.values()),
            list(deduped_tools.values()),
            list(deduped_experience.values()),
            list(deduped_projects.values()),
            duplicate_groups,
        )

    def _collect_review_fields(
        self,
        skills: list[Skill],
        tools: list[Tool],
        experience: list[ExperienceItem],
        projects: list[ProjectItem],
        education: list[EducationItem],
    ) -> list[ReviewField]:
        threshold = settings.review_threshold
        review_fields: list[ReviewField] = []

        for idx, item in enumerate(skills):
            if item.confidence.score < threshold:
                review_fields.append(
                    ReviewField(
                        path=f"profile.skills[{idx}].canonical",
                        reason="low_confidence",
                        current_confidence=item.confidence.score,
                    )
                )
        for idx, item in enumerate(tools):
            if item.confidence.score < threshold:
                review_fields.append(
                    ReviewField(
                        path=f"profile.tools[{idx}].canonical",
                        reason="low_confidence",
                        current_confidence=item.confidence.score,
                    )
                )
        for idx, item in enumerate(experience):
            if item.confidence.score < threshold:
                review_fields.append(
                    ReviewField(
                        path=f"profile.experience[{idx}]",
                        reason="low_confidence",
                        current_confidence=item.confidence.score,
                    )
                )
        for idx, item in enumerate(projects):
            if item.confidence.score < threshold:
                review_fields.append(
                    ReviewField(
                        path=f"profile.projects[{idx}]",
                        reason="low_confidence",
                        current_confidence=item.confidence.score,
                    )
                )
        for idx, item in enumerate(education):
            if item.confidence.score < threshold:
                review_fields.append(
                    ReviewField(
                        path=f"profile.education[{idx}]",
                        reason="low_confidence",
                        current_confidence=item.confidence.score,
                    )
                )

        return review_fields

    def _build_confidence(
        self,
        *,
        source_quality: float,
        section_match: float,
        pattern_validity: float,
        cross_field_consistency: float,
        model_certainty: float,
        evidence: list[str],
    ) -> Confidence:
        weights = {
            "source_quality": 0.25,
            "section_match": 0.2,
            "pattern_validity": 0.2,
            "cross_field_consistency": 0.2,
            "model_certainty": 0.15,
        }
        score = (
            source_quality * weights["source_quality"]
            + section_match * weights["section_match"]
            + pattern_validity * weights["pattern_validity"]
            + cross_field_consistency * weights["cross_field_consistency"]
            + model_certainty * weights["model_certainty"]
        )

        return Confidence(
            score=round(max(0.0, min(1.0, score)), 4),
            signals=ConfidenceSignals(
                source_quality=round(source_quality, 4),
                section_match=round(section_match, 4),
                pattern_validity=round(pattern_validity, 4),
                cross_field_consistency=round(cross_field_consistency, 4),
                model_certainty=round(model_certainty, 4),
            ),
            evidence=[e for e in evidence if e],
        )


pipeline = ResumeParsingPipeline()
