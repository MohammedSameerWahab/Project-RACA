from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

class GitHubRepositoryError(Exception):
    "Raised when a GitHub repository cannot be downloaded."

def validate_github_url(url: str) -> None:
    """Validate that the supplied URL points to GitHub"""
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise GitHubRepositoryError(
            "GitHub URL must use http:// or https://"
        )

    if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
        raise GitHubRepositoryError(
            "the URL must point to github.com"
        )

    path = parsed.path.strip("/")

    if not path or len(path.split("/")) < 2:
        raise GitHubRepositoryError(
            "Invalid GitHub repository URL. Expected format: "
            "https://github.com/<owner>/<repository>"
        )

def get_repository_name(url: str) -> str:
    """Extract the repository name from a GitHub URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    repository_name = path.split("/")[-1]

    if repository_name.endswith(".git"):
        repository_name = repository_name[:-4]

    if not repository_name:
        raise GitHubRepositoryError(
            "Could not determine repository name from URL"
        )

    # repository names cannot contain path separators or trversal.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", repository_name):
        raise GitHubRepositoryError(
            "invalid repository name"
        )
    return repository_name

def clone_repository(
    url: str,
    repositories_dir: Path,
    destination_name: str | None = None,
) -> Path:
    """
    Clone a Github repo into the local repositories directory.

    Returns:
        Path to the cloned repository.
    """
    validate_github_url(url)

    repository_name = get_repository_name(url)
    directory_name = destination_name or repository_name
    if not re.fullmatch(r"[A-Za-z0-9._-]+", directory_name):
        raise GitHubRepositoryError("Invalid clone destination name.")
    repository_path = repositories_dir / directory_name

    if repository_path.exists():
        raise GitHubRepositoryError(
            f"Repository already exists at: {repository_path}"
        )

    repositories_dir.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run(
            [
                "git",
                "clone",
                url,
                str(repository_path),
            ],
            check=True, capture_output=True, text=True,
        )

    except FileNotFoundError as exc:
        raise GitHubRepositoryError(
            "Git is not installed ot could not be found in PATH."
        ) from exc

    except subprocess.CalledProcessError as exc:
        error_message = exc.stderr.strip()
        if repository_path.is_dir():
            shutil.rmtree(repository_path)
        raise GitHubRepositoryError(
            f"Failed to clone repository: {error_message}"
        ) from exc
    return repository_path