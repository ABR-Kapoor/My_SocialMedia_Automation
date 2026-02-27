"""
GitHub Agent — fetches repos, checks today's commits, and auto-commits
real DSA content to DSA-java repo. Two modes:
  A (60%): inline comment added to an existing Java file (natural dev review)
  B (40%): new folder + Java file for a DSA topic with full implementation
"""
import base64
import logging
import random
from datetime import datetime, timezone, timedelta

from github import Github, GithubException
from config import GITHUB_PAT, GITHUB_USERNAME, GITHUB_DSA_REPO

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# DSA topics for Mode B — pick one that sounds like a natural next commit
DSA_TOPICS = [
    ("Graph", "TopologicalSort",     "Topological Sort (Kahn's BFS)"),
    ("Graph", "CycleDetectionDFS",   "Cycle detection in directed graph via DFS"),
    ("Tree",  "LevelOrderTraversal", "Level-order traversal using queue"),
    ("Tree",  "DiameterOfBTree",     "Diameter of binary tree — bottom-up DP"),
    ("DP",    "LongestCommonSubseq", "LCS with memoization"),
    ("DP",    "CoinChange",          "Coin change min-coins bottom-up"),
    ("DP",    "KnapsackZeroOne",     "0/1 Knapsack tabulation"),
    ("Heap",  "KthLargestElement",   "Kth largest using min-heap"),
    ("Heap",  "MedianFinder",        "Running median with two heaps"),
    ("Trie",  "TrieImplementation",  "Trie — insert, search, startsWith"),
    ("Backtracking", "NQueens",      "N-Queens backtracking"),
    ("Backtracking", "Sudoku",       "Sudoku solver backtracking"),
    ("Sorting", "MergeSort",         "Merge sort iterative (bottom-up)"),
    ("Sorting", "QuickSort",         "Quick sort with 3-way partition"),
    ("LinkedList", "LRUCache",       "LRU Cache — HashMap + Doubly LinkedList"),
    ("LinkedList", "MergeKLists",    "Merge K sorted lists — min-heap approach"),
    ("BinarySearch", "RotatedArray", "Search in rotated sorted array"),
    ("BinarySearch", "FindPeakElem", "Find peak element — binary search"),
    ("HashMap", "TwoSum",            "Two sum — HashMap O(n)"),
    ("String", "LongestPalinSubstr", "Longest palindromic substring — expand around center"),
]


class GithubAgent:
    def __init__(self):
        self.gh    = Github(GITHUB_PAT)
        self._repo = None

    # ── DSA-java repo (lazy) ──────────────────────────────────────────────────

    def _get_dsa_repo(self):
        if self._repo is None:
            self._repo = self.gh.get_repo(GITHUB_DSA_REPO)
        return self._repo

    # ── Public repos list ─────────────────────────────────────────────────────

    def get_user_repos(self, limit: int = 15) -> list[dict]:
        try:
            user  = self.gh.get_user(GITHUB_USERNAME)
            repos = []
            for repo in user.get_repos(type="public", sort="updated"):
                if repo.fork:
                    continue
                repos.append({
                    "name":        repo.name,
                    "full_name":   repo.full_name,
                    "description": repo.description or "",
                    "language":    repo.language or "Unknown",
                    "stars":       repo.stargazers_count,
                    "url":         repo.html_url,
                    "topics":      repo.get_topics(),
                })
                if len(repos) >= limit:
                    break
            return repos
        except GithubException as e:
            logger.error(f"Failed to fetch repos: {e}")
            return []

    # ── Today's commit check (IST) ────────────────────────────────────────────

    def check_today_commit(self) -> dict:
        try:
            repo      = self._get_dsa_repo()
            today_ist = datetime.now(IST).date()
            count     = 0
            last_msg  = ""
            last_url  = ""

            for commit in repo.get_commits(author=GITHUB_USERNAME):
                commit_date_ist = commit.commit.author.date.replace(
                    tzinfo=timezone.utc
                ).astimezone(IST).date()

                if commit_date_ist == today_ist:
                    count += 1
                    if not last_msg:
                        last_msg = commit.commit.message.split("\n")[0]
                        last_url = commit.html_url
                elif commit_date_ist < today_ist:
                    break

            return {"committed": count > 0, "count": count,
                    "last_msg": last_msg, "last_url": last_url}
        except GithubException as e:
            logger.error(f"Today commit check failed: {e}")
            return {"committed": False, "count": 0, "last_msg": "", "last_url": ""}

    # ── Pick random Java file (Mode A) ────────────────────────────────────────

    def get_random_java_file(self) -> dict | None:
        """Returns a random .java file with its full content."""
        try:
            repo = self._get_dsa_repo()
            tree = repo.get_git_tree(repo.default_branch, recursive=True)
            java_files = [
                item for item in tree.tree
                if item.type == "blob" and item.path.endswith(".java")
                # skip tiny/empty files
            ]
            if not java_files:
                return None

            chosen = random.choice(java_files)
            blob   = repo.get_contents(chosen.path)
            raw    = base64.b64decode(blob.content).decode("utf-8", errors="ignore")

            return {
                "path":         chosen.path,
                "name":         chosen.path.split("/")[-1],
                "folder":       "/".join(chosen.path.split("/")[:-1]) or "root",
                "full_content": raw,
                "preview":      "\n".join(raw.splitlines()[:80]),
                "sha":          blob.sha,
                "url":          blob.html_url,
            }
        except GithubException as e:
            logger.error(f"get_random_java_file failed: {e}")
            return None

    # ── Get folder list for display ───────────────────────────────────────────

    def get_repo_folders(self) -> list[str]:
        """Returns top-level folder names in DSA-java."""
        try:
            repo    = self._get_dsa_repo()
            contents = repo.get_contents("")
            return [c.name for c in contents if c.type == "dir"]
        except GithubException as e:
            logger.error(f"get_repo_folders failed: {e}")
            return []

    # ── Mode A: Insert inline comment in existing file ────────────────────────

    def commit_inline_comment(self, file_info: dict, comment_lines: str) -> dict:
        """
        Inserts comment_lines right after the class declaration line
        (or after the first { if no class line found).
        """
        try:
            repo  = self._get_dsa_repo()
            lines = file_info["full_content"].splitlines()
            insert_at = 0

            # Find first opening brace of class body
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.startswith("class ") and "{" in stripped:
                    insert_at = i + 1
                    break
                if stripped == "{" and i > 0 and "class" in lines[i - 1]:
                    insert_at = i + 1
                    break
            # Fallback: find first method or code line
            if insert_at == 0:
                for i, line in enumerate(lines):
                    if line.strip().startswith("public ") or line.strip().startswith("static "):
                        insert_at = i
                        break
                insert_at = max(insert_at, 1)

            # Format comment lines (ensure each starts with //)
            comment_block = "\n".join(
                f"    {ln.strip()}" if ln.strip().startswith("//") else f"    // {ln.strip()}"
                for ln in comment_lines.strip().splitlines()
                if ln.strip()
            )

            new_lines = lines[:insert_at] + [comment_block, ""] + lines[insert_at:]
            new_content = "\n".join(new_lines)

            # Human-sounding commit messages
            fname = file_info["name"].replace(".java", "")
            commit_msg = random.choice([
                f"add complexity notes to {fname}",
                f"minor comments in {fname} — clarify edge cases",
                f"note on {fname} approach after revisiting",
                f"left a few comments in {fname} to explain the logic",
                f"revisited {fname}, added inline notes",
            ])

            result = repo.update_file(
                path=file_info["path"],
                message=commit_msg,
                content=new_content,
                sha=file_info["sha"],
            )
            url = result["commit"].html_url
            logger.info(f"✅ Inline comment committed: {file_info['path']}")
            return {
                "success": True, "url": url, "message": commit_msg,
                "mode": "comment", "file": file_info["path"],
            }
        except GithubException as e:
            logger.error(f"commit_inline_comment failed: {e}")
            return {"success": False, "url": "", "message": str(e)}

    # ── Mode B: Create new DSA topic file ────────────────────────────────────

    def pick_new_dsa_topic(self) -> tuple[str, str, str]:
        """Pick a random topic from DSA_TOPICS. Returns (folder, filename, description)."""
        return random.choice(DSA_TOPICS)

    def create_dsa_file(self, folder: str, filename: str,
                        java_code: str, description: str) -> dict:
        """Create a new .java file in the given folder inside DSA-java."""
        try:
            repo      = self._get_dsa_repo()
            file_path = f"{folder}/{filename}.java"

            # Human commit messages
            commit_msg = random.choice([
                f"add {filename} — {description[:50]}",
                f"implement {filename.lower()} in {folder}",
                f"{filename}: working solution, needs cleanup",
                f"finally got {filename} working — adding to repo",
                f"solved {filename}, committing before I forget",
            ])

            result = repo.create_file(
                path=file_path,
                message=commit_msg,
                content=java_code,
            )
            url = result["commit"].html_url
            logger.info(f"✅ New DSA file created: {file_path}")
            return {
                "success": True, "url": url, "message": commit_msg,
                "mode": "new_file", "file": file_path,
            }
        except GithubException as e:
            logger.error(f"create_dsa_file failed: {e}")
            return {"success": False, "url": "", "message": str(e)}

    # ── Latest commit info (for /post GitHub content) ─────────────────────────

    def get_latest_commit_info(self) -> dict | None:
        try:
            repo   = self._get_dsa_repo()
            latest = repo.get_commits()[0]
            return {
                "sha":       latest.sha,
                "short_sha": latest.sha[:7],
                "message":   latest.commit.message.split("\n")[0],
                "files":     [f.filename for f in latest.files[:5]],
                "url":       latest.html_url,
                "author":    latest.commit.author.name,
                "date":      latest.commit.author.date,
            }
        except GithubException as e:
            logger.error(f"get_latest_commit_info failed: {e}")
            return None

    # ── Format helpers ────────────────────────────────────────────────────────

    def format_repos_for_display(self, repos: list[dict]) -> str:
        if not repos:
            return "No public repos found."
        lines = []
        for i, r in enumerate(repos, 1):
            desc = (r["description"][:60] + "…") if len(r["description"]) > 60 else r["description"]
            line = f"{i}. *{r['name']}* ({r['language']} ⭐{r['stars']})"
            if desc:
                line += f"\n   _{desc}_"
            lines.append(line)
        return "\n".join(lines)
