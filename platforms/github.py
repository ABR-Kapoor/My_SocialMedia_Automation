"""
GitHub Platform — Comments on latest commit in DSA-java repo.
Uses PyGitHub with a Fine-Grained Personal Access Token.
Comments are meaningful, DSA-related, and show developer consistency.
"""
import logging
from github import Github, GithubException
from config import GITHUB_PAT, GITHUB_DSA_REPO

logger = logging.getLogger(__name__)


class GithubPlatform:
    def __init__(self):
        self.gh = Github(GITHUB_PAT)

    async def post(self, content: str, image_bytes: bytes | None = None) -> str:
        """
        Comment on the latest commit of DSA-java with meaningful content.
        Returns direct URL to the commit comment.
        image_bytes is ignored (GitHub commit comments are text-only).
        """
        try:
            repo    = self.gh.get_repo(GITHUB_DSA_REPO)
            commits = repo.get_commits()
            latest  = commits[0]

            # Create the commit comment
            comment = latest.create_comment(body=content)

            url = comment.html_url
            logger.info(f"✅ GitHub comment posted: {url}")
            return url

        except GithubException as e:
            status = e.status if hasattr(e, "status") else "?"
            raise RuntimeError(f"GitHub comment failed [{status}]: {e.data}")

    async def get_latest_commit_summary(self) -> dict:
        """
        Returns a short summary of the latest commit — used by content agent
        to craft a contextually relevant comment.
        """
        try:
            repo    = self.gh.get_repo(GITHUB_DSA_REPO)
            commits = repo.get_commits()
            latest  = commits[0]

            files = [f.filename for f in latest.files[:5]]
            return {
                "sha":     latest.sha[:7],
                "message": latest.commit.message.split("\n")[0],
                "files":   files,
                "url":     latest.html_url,
            }
        except GithubException as e:
            logger.error(f"Failed to fetch commit: {e}")
            return {}
