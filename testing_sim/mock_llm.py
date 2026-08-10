"""Provides a simple mock LLM response for testing robot behavior pipelines.
"""

def mock_response():
    return {
        "action": "cautious_walk",
        "speed": 0.25,
        "duration": 5,
        "safety_level": "high"
    }