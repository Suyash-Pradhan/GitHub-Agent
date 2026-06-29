from github import GithubException


def _commit_file_changes(
    repo, branch_name: str, file_blocks: list[tuple[str, str]], commit_prefix: str
) -> None:
    for path, content in file_blocks:
        commit_message = f"{commit_prefix}: update {path}"
        try:
            existing = repo.get_contents(path, ref=branch_name)
            repo.update_file(
                path=path,
                message=commit_message,
                content=content,
                sha=existing.sha,
                branch=branch_name,
            )
        except GithubException as e:
            if getattr(e, "status", None) == 404:
                repo.create_file(
                    path=path,
                    message=commit_message,
                    content=content,
                    branch=branch_name,
                )
            else:
                raise
