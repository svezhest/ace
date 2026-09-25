"""Interfaces for the context-engineering (symptom diagnosis) task.

The base agent makes exactly one LLM call to diagnose a disease from a
patient's free-text symptoms. The context passed to that call is produced by
get_context(previous_context).
"""


def get_context(symptoms):
    """Return context that helps the single-shot LLM diagnose a disease.

    Args:
        symptoms (str): Patient symptom description.

    Returns:
        str: Curated medical context (the disease reference) that the LLM
        compares the reported symptoms against.
    """
    return read_context_file()


def read_context_file():
    """Read the curated disease reference via ABSOLUTE paths.

    Absolute paths are used on purpose: the retriever/agent invokes this from
    an unpinned working directory, so a bare relative path would silently fail.
    """
    disease_ref = (
        "/private/tmp/mce-live/workspace/live/iter1_sub0/context/diseases.md"
    )
    scratch = (
        "/private/tmp/mce-live/workspace/live/iter1_sub0/context/"
    )
    with open(disease_ref, "r", encoding="utf-8") as fh:
        content = fh.read()
    return scratch + content


__all__ = ["get_context"]