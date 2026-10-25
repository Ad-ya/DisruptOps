import os
from pathlib import Path


def load_google_key(dotenv_path: Path) -> bool:
    from dotenv import dotenv_values

    names = ('GOOGLE_API_KEY', 'GEMINI_API_KEY')
    if any(os.getenv(name) for name in names):
        return True
    values = dotenv_values(dotenv_path) if dotenv_path.is_file() else {}
    for name in names:
        if not os.getenv(name) and values.get(name):
            os.environ[name] = values[name]
    return any(os.getenv(name) for name in names)


def public_error(error: Exception) -> str:
    """Preserve local validation feedback; provider errors expose type/code only."""
    from pydantic import ValidationError

    source = error
    for _ in range(4):
        if isinstance(source, ValidationError):
            details = source.errors(include_input=False, include_context=False, include_url=False)
            message = '; '.join(f'{".".join(str(item) for item in row["loc"]) or "finding"}: {row["msg"]}'
                                for row in details)
            for name in ('GOOGLE_API_KEY', 'GEMINI_API_KEY'):
                if secret := os.getenv(name):
                    message = message.replace(secret, '[redacted]')
            return f'Structured validation failed: {message[:1200]}'
        source = getattr(source, 'source', None) or getattr(source, '__cause__', None)
        if source is None:
            break
    if isinstance(error, (ValueError, KeyError, FileNotFoundError)):
        message = str(error)
        for name in ('GOOGLE_API_KEY', 'GEMINI_API_KEY'):
            if secret := os.getenv(name):
                message = message.replace(secret, '[redacted]')
        return f'{type(error).__name__}: {message[:1200]}'
    code = getattr(error, 'code', None)
    suffix = f' (code {code})' if isinstance(code, int) else ''
    return f'{type(error).__name__}{suffix}: execution failed; check provider availability or source data.'
