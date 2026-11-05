from __future__ import annotations

from enum import Enum


class GenerationMode(str, Enum):
    """
    Controls the type of response RACA should generate.
    """

    EXPLAIN = "explain"
    GENERATE = "generate"
    REFACTOR = "refactor"
    TEST = "test"
    DOCUMENT = "document"


MODE_INSTRUCTIONS: dict[GenerationMode, str] = {
    GenerationMode.EXPLAIN: """
Explain the requested repository code clearly.

Focus on:
- what the code does
- how it works
- relevant relationships between components
- important implementation details

Do not propose code changes unless they are specifically useful to answer the question.
""".strip(),

    GenerationMode.GENERATE: """
Generate practical code that satisfies the user's request.

The generated code must:
- follow the existing repository architecture
- use patterns and APIs already present in the repository when possible
- identify the file and location where the change belongs
- avoid inventing repository-specific APIs that are not supported by context

Provide the generated code in a clearly labelled code block.
""".strip(),

    GenerationMode.REFACTOR: """
Propose a concrete refactoring of the requested code.

Explain:
- what is being improved
- why the change is useful
- what code should be replaced

Preserve existing behavior unless the user explicitly requests a behavior change.
Provide the proposed replacement code.
""".strip(),

    GenerationMode.TEST: """
Generate tests for the requested repository code.

Follow the testing framework and conventions already used by the repository.

Include:
- the target file/function
- the test file/location
- the generated test code
- a short explanation of what the tests cover
""".strip(),

    GenerationMode.DOCUMENT: """
Generate documentation for the requested repository code.

Prefer the repository's existing documentation style.

The documentation may include:
- docstrings
- API documentation
- usage examples
- explanatory comments

Clearly identify where the documentation should be added.
""".strip(),
}


def get_mode_instruction(mode: GenerationMode) -> str:
    """
    Return the instruction associated with a generation mode.
    """

    try:
        return MODE_INSTRUCTIONS[mode]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported generation mode: {mode}"
        ) from exc