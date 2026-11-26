"""CLI orchestration only; parse arguments, call the service, print a single JSON result."""

import os
from functools import partial

from .args import parse_args
from .errors import ReadError, ValidationError
from .http_client import get_json, normalize_token
from .report import error_payload, render
from .service import measure


def main(argv=None):
    """Return 0 for a verified report, 2 for input errors, or 1 for read/report failures."""
    try:
        population = parse_args(argv)
        token = normalize_token(os.environ.get("GITHUB_TOKEN"))
        output = render(measure(partial(get_json, token=token), population))
    except ReadError as error:
        print(render(error_payload(error)))
        return 1
    except ValidationError as error:
        print(render(error_payload(error)))
        return 1 if error.field == "report" else 2
    print(output)
    return 0
