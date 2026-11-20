"""Single-frame extraction shared by the four workflow-scheduler transports."""


def extract_framed_payload(stdout: object, *, frame_start: str, frame_end: str) -> str | None:
    """Extract and trim one ordered frame; the caller owns its content and meaning."""
    if (
        type(stdout) is not str
        or stdout.count(frame_start) != 1
        or stdout.count(frame_end) != 1
    ):
        return None
    start = stdout.find(frame_start)
    end = stdout.find(frame_end)
    return stdout[start + len(frame_start):end].strip() if start >= 0 and end > start else None
