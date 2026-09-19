"""Built-in config profiles (CONFIGURATION.md §2).

Profiles are partial override maps merged over the defaults; values follow the documented
move direction (e.g. `podcast` raises speech_density and lowers visual_activity). Numbers
are seed values — tuning is data-driven via the SCORING_ENGINE.md §8 fixture set later.
"""

from __future__ import annotations

from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "podcast": {
        "scoring": {
            "weights": {
                "speech_density": 0.19,
                "visual_activity": 0.04,
                "audio_energy": 0.14,
                "keyword_density": 0.03,
            }
        }
    },
    "lecture": {
        "scoring": {
            "weights": {
                "completeness": 0.26,
                "hook": 0.08,
                "pacing": 0.06,
                "speech_density": 0.19,
            }
        }
    },
    "interview": {
        "scoring": {
            "weights": {
                "sentence_quality": 0.12,
                "hook": 0.20,
                "audio_energy": 0.05,
            }
        }
    },
    "gaming": {
        "scoring": {
            "weights": {
                "visual_activity": 0.17,
                "hook": 0.22,
                "speech_density": 0.06,
                "keyword_density": 0.03,
            }
        },
        "reframe": {
            "mode": "gamer",
        },
    },
    "talking-head": {
        "scoring": {
            "weights": {
                "audio_energy": 0.05,
                "visual_activity": 0.06,
                "completeness": 0.24,
            }
        }
    },
}
