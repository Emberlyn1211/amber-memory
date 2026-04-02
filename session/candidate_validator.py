"""Candidate memory validator for Amber Memory.

Validates extracted candidate memories before they enter canonical storage.
"""

import json
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ValidationResult:
    """Result of validating a candidate memory."""
    passed: bool
    errors: List[str]
    warnings: List[str]
    normalized: Dict[str, any]


class CandidateValidator:
    """Validates candidate memories with rule-based checks."""

    # Valid memory types
    VALID_TYPES = {
        "person", "activity", "object", "place",
        "preference", "taboo", "goal", "pattern", "thought"
    }

    # Types that require speaker attribution in group chats
    SPEAKER_REQUIRED_TYPES = {"preference", "goal", "thought", "activity"}

    # Relative time patterns to normalize
    RELATIVE_TIME_PATTERNS = [
        (r'昨天|昨日', 'yesterday'),
        (r'今天|今日', 'today'),
        (r'明天|明日', 'tomorrow'),
        (r'上周', 'last_week'),
        (r'下周', 'next_week'),
        (r'上个月', 'last_month'),
        (r'下个月', 'next_month'),
        (r'去年', 'last_year'),
        (r'明年', 'next_year'),
        (r'最近|前不久', 'recently'),
        (r'以前|从前', 'past'),
        (r'小时候', 'childhood'),
    ]

    def __init__(self, reference_time: Optional[float] = None):
        """
        Args:
            reference_time: Unix timestamp for relative time normalization.
                           If None, uses current time.
        """
        self.reference_time = reference_time

    def validate(
        self,
        candidate: Dict[str, any],
        is_group_chat: bool = False,
        chat_participants: Optional[List[str]] = None,
    ) -> ValidationResult:
        """Validate a candidate memory.

        Args:
            candidate: Raw candidate dict from extractor
            is_group_chat: Whether source is group chat
            chat_participants: List of participant names/IDs

        Returns:
            ValidationResult with passed/failed status and normalized fields
        """
        errors = []
        warnings = []
        normalized = dict(candidate)

        # 1. Type validation
        mem_type = candidate.get("memory_type", "")
        if mem_type not in self.VALID_TYPES:
            errors.append(f"Invalid memory_type: {mem_type}")
            normalized["memory_type"] = "thought"  # fallback

        # 2. Speaker attribution (critical for group chats)
        if is_group_chat and mem_type in self.SPEAKER_REQUIRED_TYPES:
            speaker_id = candidate.get("speaker_id", "")
            speaker_name = candidate.get("speaker_name", "")
            if not speaker_id and not speaker_name:
                errors.append(
                    f"Speaker attribution required for {mem_type} in group chat"
                )

        # 3. Content validation
        abstract = candidate.get("abstract", "").strip()
        content = candidate.get("content", "").strip()

        if not abstract:
            errors.append("abstract is required")
        if len(abstract) > 500:
            warnings.append("abstract exceeds 500 chars, truncating")
            normalized["abstract"] = abstract[:500]

        if not content:
            errors.append("content is required")

        # 4. Evidence quote validation
        evidence = candidate.get("evidence_quote", "").strip()
        if not evidence:
            warnings.append("No evidence_quote provided")
        elif len(evidence) < 10:
            warnings.append("evidence_quote seems too short")

        # 5. Confidence check
        confidence = candidate.get("confidence", 0.5)
        if confidence < 0.3:
            warnings.append(f"Low confidence: {confidence}")
        if confidence > 1.0:
            normalized["confidence"] = 1.0

        # 6. Time normalization
        normalized_content = self._normalize_relative_time(content)
        if normalized_content != content:
            normalized["content"] = normalized_content
            normalized["_time_normalized"] = True

        # 7. Taboo check (placeholder - actual check done at storage layer)
        if mem_type == "taboo":
            warnings.append("Taboo memories require manual review")

        # 8. Subject validation
        subject = candidate.get("subject_guess", "").strip()
        if mem_type == "person" and not subject:
            errors.append("person memory requires subject_guess (person name)")

        # Determine final status
        passed = len(errors) == 0

        return ValidationResult(
            passed=passed,
            errors=errors,
            warnings=warnings,
            normalized=normalized,
        )

    def _normalize_relative_time(self, text: str) -> str:
        """Normalize relative time expressions in text.

        Examples:
            "昨天去了北京" -> "[2026-04-01]去了北京" (if today is 2026-04-02)
            "最近在学习" -> "[recently]在学习"
        """
        import time
        from datetime import datetime, timedelta

        ref_time = self.reference_time or time.time()
        ref_date = datetime.fromtimestamp(ref_time)

        result = text

        for pattern, marker in self.RELATIVE_TIME_PATTERNS:
            matches = list(re.finditer(pattern, result))
            # Process from end to start to preserve indices
            for match in reversed(matches):
                start, end = match.span()
                original = match.group()

                # Calculate absolute date if possible
                if marker == 'yesterday':
                    abs_date = (ref_date - timedelta(days=1)).strftime('%Y-%m-%d')
                    replacement = f"[{abs_date}]"
                elif marker == 'today':
                    abs_date = ref_date.strftime('%Y-%m-%d')
                    replacement = f"[{abs_date}]"
                elif marker == 'tomorrow':
                    abs_date = (ref_date + timedelta(days=1)).strftime('%Y-%m-%d')
                    replacement = f"[{abs_date}]"
                elif marker == 'last_week':
                    abs_date = (ref_date - timedelta(weeks=1)).strftime('%Y-%m-%d')
                    replacement = f"[around {abs_date}]"
                elif marker == 'next_week':
                    abs_date = (ref_date + timedelta(weeks=1)).strftime('%Y-%m-%d')
                    replacement = f"[around {abs_date}]"
                elif marker == 'last_month':
                    abs_date = (ref_date.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
                    replacement = f"[{abs_date}]"
                elif marker == 'next_month':
                    if ref_date.month == 12:
                        abs_date = f"{ref_date.year + 1}-01"
                    else:
                        abs_date = f"{ref_date.year}-{ref_date.month + 1:02d}"
                    replacement = f"[{abs_date}]"
                elif marker == 'last_year':
                    replacement = f"[{ref_date.year - 1}]"
                elif marker == 'next_year':
                    replacement = f"[{ref_date.year + 1}]"
                else:
                    # Keep marker for uncertain times
                    replacement = f"[{marker}]"

                result = result[:start] + replacement + result[end:]

        return result

    def batch_validate(
        self,
        candidates: List[Dict[str, any]],
        is_group_chat: bool = False,
        chat_participants: Optional[List[str]] = None,
    ) -> Tuple[List[Dict[str, any]], List[Dict[str, any]]]:
        """Validate multiple candidates.

        Returns:
            (passed_candidates, failed_candidates_with_errors)
        """
        passed = []
        failed = []

        for candidate in candidates:
            result = self.validate(candidate, is_group_chat, chat_participants)

            if result.passed:
                passed.append(result.normalized)
            else:
                failed.append({
                    "candidate": candidate,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "normalized": result.normalized,
                })

        return passed, failed
