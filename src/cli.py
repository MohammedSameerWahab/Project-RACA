from src.config import REPOSITORIES_DIR
from src.ingestion.github import GitHubRepositoryError, clone_repository

def main() -> None:
    github_url = input("Enter the Github Repository URL: ").strip()

    try:
        repository_path = clone_repository(github_url, REPOSITORIES_DIR)

        print()
        print("Repository cloned successfully.")
        print(f"Local path: {repository_path}")

    except GitHubRepositoryError as exc:
        print()
        print(f"Error: {exc}")

if __name__ == "__main__":
    main()