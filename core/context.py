"""Context model with L0/L1/L2 hierarchy and memory decay.

L0: One-line abstract (always loaded, ~10 tokens)
L1: Overview paragraph (loaded on relevance, ~100 tokens)  
L2: Full content (loaded on demand, unlimited)

Decay model based on ACT-R + FSRS (Nowledge Mem reference).
"""

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from .uri import URI


class ContextType(str, Enum):
    MEMORY = "memory"
    PERSON = "person"       # 人：联系人、关系、互动历史
    ACTIVITY = "activity"   # 事：第一视角做了什么（照片语义、日程对账）
    OBJECT = "object"       # 物：物品、项目、地点、概念
    PREFERENCE = "preference"  # 偏好：喜欢/不喜欢/习惯
    TABOO = "taboo"         # 禁忌：不想被提及的事、敏感话题
    GOAL = "goal"           # 目标：短期/长期目标、进度
    PATTERN = "pattern"     # 模式：作息规律、行为模式、工作强度
    THOUGHT = "thought"     # 思考：日记、随感、反思、读书笔记


class MemoryCategory(str, Enum):
    # User memories
    PROFILE = "profile"
    PREFERENCES = "preferences"
    ENTITIES = "entities"
    EVENTS = "events"
    TABOOS = "taboos"
    GOALS = "goals"
    # Agent memories
    CASES = "cases"
    PATTERNS = "patterns"
    THOUGHTS = "thoughts"


class EmotionTag(str, Enum):
    NEUTRAL = "neutral"
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    SURPRISE = "surprise"
    FEAR = "fear"
    LOVE = "love"
    NOSTALGIA = "nostalgia"


@dataclass
class DecayParams:
    """Memory decay parameters.
    
    Score formula:
        score = importance * recency * access_boost * link_boost * emotion_boost
    
    Recency (exponential decay):
        recency = exp(-lambda * days_since_last_access)
        half_life configurable (default 14 days)
    
    Access boost (frequency reinforcement):
        access_boost = 1 + log(1 + access_count) * 0.3
    
    Link boost (connected memories decay slower):
        link_boost = 1 + min(link_count, 10) * 0.05
    
    Emotion boost (emotional memories persist):
        emotion_boost = 1.0 for neutral, up to 1.5 for strong emotions
    
    Importance floor: memories never fully decay below floor
    """
    half_life_days: float = 14.0      # Nowledge uses 30, we use 14 for more aggressive decay
    importance_floor: float = 0.05    # minimum score, never fully forgotten
    access_weight: float = 0.3       # how much access count boosts
    link_weight: float = 0.05        # how much connections boost
    emotion_multipliers: Dict[str, float] = field(default_factory=lambda: {
        "neutral": 1.0,
        "joy": 1.2,
        "sadness": 1.3,
        "anger": 1.1,
        "surprise": 1.15,
        "fear": 1.25,
        "love": 1.4,
        "nostalgia": 1.35,
    })

    # Per-category decay overrides (half_life_days, min_importance)
    category_decay: Dict[str, Tuple[Optional[float], float]] = field(default_factory=lambda: {
        'taboo':      (None, 1.0),    # never decay, importance locked at 1.0
        'person':     (60,   0.3),    # relationships are long-term
        'preference': (30,   0.2),    # preferences change slowly
        'pattern':    (30,   0.2),    # behavioral patterns are stable
        'thought':    (30,   0.15),   # thoughts have long-term value
        'goal':       (45,   0.3),    # goals persist until achieved
        'activity':   (14,   0.1),    # daily activities decay normally
        'object':     (14,   0.1),    # object info decays normally
        'place':      (21,   0.1),    # places slightly more persistent
    })
    
    @property
    def decay_lambda(self) -> float:
        return math.log(2) / self.half_life_days


DEFAULT_DECAY = DecayParams()


@dataclass 
class Context:
    """A memory unit with L0/L1/L2 hierarchy and decay metadata."""
    
    # Identity
    id: str = field(default_factory=lambda: uuid4().hex[:16])
    uri: str = ""                    # URI string
    parent_uri: str = ""             # parent directory URI
    
    # L0/L1/L2 content
    abstract: str = ""               # L0: one-line summary (~10 tokens)
    overview: str = ""               # L1: paragraph overview (~100 tokens)
    content: str = ""                # L2: full content (unlimited)
    
    # Classification
    context_type: str = ContextType.MEMORY
    category: str = ""
    tags: List[str] = field(default_factory=list)
    emotion: str = EmotionTag.NEUTRAL
    
    # Importance (0.0 - 1.0, set by LLM or heuristic)
    importance: float = 0.5
    
    # Temporal
    created_at: float = field(default_factory=time.time)   # unix timestamp
    updated_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    event_time: Optional[float] = None   # when the event happened (vs when recorded)
    valid_from: Optional[float] = None   # validity window start
    valid_to: Optional[float] = None     # validity window end
    
    # Decay tracking
    access_count: int = 0
    link_count: int = 0              # number of linked memories
    
    # Relations
    linked_uris: List[str] = field(default_factory=list)
    source_session: str = ""
    
    # Embedding (stored separately in vector index)
    embedding: Optional[List[float]] = None
    
    # Extra metadata
    meta: Dict[str, Any] = field(default_factory=dict)
    
    def compute_score(self, params: DecayParams = DEFAULT_DECAY, now: Optional[float] = None) -> float:
        """Compute current memory score with category-aware decay."""
        now = now or time.time()
        days_elapsed = max(0, (now - self.last_accessed) / 86400.0)

        # Category-specific decay parameters
        cat_config = params.category_decay.get(self.category)
        if cat_config:
            cat_half_life, cat_min_importance = cat_config
        else:
            cat_half_life, cat_min_importance = params.half_life_days, params.importance_floor

        # Exponential decay (None = never decay)
        if cat_half_life is None:
            recency = 1.0
        else:
            cat_lambda = math.log(2) / cat_half_life
            recency = math.exp(-cat_lambda * days_elapsed)

        # Effective importance (category minimum + commitment lock)
        effective_importance = max(self.importance, cat_min_importance)
        if self.meta.get('locked'):
            effective_importance = max(effective_importance, 0.8)

        # Access frequency boost
        access_boost = 1.0 + math.log(1.0 + self.access_count) * params.access_weight

        # Link boost
        link_boost = 1.0 + min(self.link_count, 10) * params.link_weight

        # Emotion boost
        emotion_boost = params.emotion_multipliers.get(self.emotion, 1.0)

        # Final score
        raw_score = effective_importance * recency * access_boost * link_boost * emotion_boost

        # Apply floor
        return max(raw_score, params.importance_floor * effective_importance)
    
    def touch(self):
        """Record an access, refreshing decay."""
        self.access_count += 1
        self.last_accessed = time.time()
    
    def to_l0(self) -> str:
        """Return L0 representation (minimal, for directory listing)."""
        return self.abstract or self.uri
    
    def to_l1(self) -> str:
        """Return L1 representation (overview, for relevance check)."""
        return self.overview or self.abstract or self.uri
    
    def to_l2(self) -> str:
        """Return L2 representation (full content)."""
        return self.content or self.overview or self.abstract
    
    def to_dict(self) -> Dict[str, Any]:
        d = {
            "id": self.id,
            "uri": self.uri,
            "parent_uri": self.parent_uri,
            "abstract": self.abstract,
            "overview": self.overview,
            "content": self.content,
            "context_type": self.context_type,
            "category": self.category,
            "tags": self.tags,
            "emotion": self.emotion,
            "importance": self.importance,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed": self.last_accessed,
            "event_time": self.event_time,
            "access_count": self.access_count,
            "link_count": self.link_count,
            "linked_uris": self.linked_uris,
            "source_session": self.source_session,
            "meta": self.meta,
        }
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Context':
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
