"""Memory Validator — rule-based validation for candidate memories.

Replaces the old validation logic with explicit checks before promotion.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ValidationResult:
    passed: bool
    errors: List[str]
    warnings: List[str]


class MemoryValidator:
    """Validates candidate memories with rule-based checks."""

    VALID_TYPES = {"person", "activity", "object", "place", "preference", "taboo", "goal", "pattern", "thought"}

    def __init__(self, taboo_patterns: Optional[List[str]] = None):
        self.taboo_patterns = taboo_patterns or []

    def validate(self, candidate: dict, chat_context: Optional[dict] = None) -> ValidationResult:
        """Run all validation checks on a candidate memory."""
        errors = []
        warnings = []

        # 1. Type validation
        mem_type = candidate.get("memory_type", "")
        if mem_type not in self.VALID_TYPES:
            errors.append(f"Invalid memory_type: {mem_type}")

        # 2. Content validation
        abstract = candidate.get("abstract", "").strip()
        content = candidate.get("content", "").strip()
        if not abstract:
            errors.append("Missing abstract (L0)")
        if not content:
            errors.append("Missing content (L2)")
        if len(abstract) > 500:
            warnings.append("Abstract too long (>500 chars)")

        # 3. Speaker attribution validation (for chat sources)
        if chat_context:
            speaker_id = candidate.get("speaker_id", "")
            speaker_name = candidate.get("speaker_name", "")
            if chat_context.get("is_group_chat") and not speaker_id:
                warnings.append("Group chat message missing speaker attribution")

        # 4. Time normalization check
        content_text = candidate.get("content", "")
        relative_time_patterns = [r"昨天", r"最近", r"上周", r"以前", r"小时候", r"之前"]
        for pattern in relative_time_patterns:
            import re
            if re.search(pattern, content_text):
                warnings.append(f"Contains relative time reference: {pattern}")

        # 5. Taboo check
        for pattern in self.taboo_patterns:
            if pattern.lower() in content_text.lower():
                errors.append(f"Matches taboo pattern: {pattern}")

        # 6. Confidence threshold
        confidence = candidate.get("confidence", 0.5)
        if confidence < 0.3:
            warnings.append(f"Very low confidence: {confidence}")
        if confidence < 0.5:
            warnings.append(f"Low confidence: {confidence}")

        return ValidationResult(
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    def validate_speaker_attribution(self, candidate: dict, message_source: dict) -> Tuple[bool, str]:
        """Validate that speaker attribution matches the actual message source."""
        claimed_speaker = candidate.get("speaker_name", "")
        actual_speaker = message_source.get("sender_name", "")
        is_group = message_source.get("is_group", False)

        if not is_group:
            # Private chat - simpler attribution
            return True, "Private chat"

        if not claimed_speaker:
            return False, "Group chat missing speaker attribution"

        if claimed_speaker != actual_speaker:
            return False, f"Speaker mismatch: claimed '{claimed_speaker}' but source is '{actual_speaker}'"

        return True, "OK"
