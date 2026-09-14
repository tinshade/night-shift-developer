from tools.github_mcp import GitHubMCP


def test_publish_repair_requires_local_changes():
    github = GitHubMCP(token="token", owner="owner", repository="repo")
    github._git = lambda _workspace, args: "" if args == ["status", "--porcelain"] else ""

    try:
        github.publish_repair("workspace", "repair/guid", "Repair guid")
    except Exception as exc:
        assert "no changes" in str(exc)
    else:
        raise AssertionError("publish_repair should reject an unchanged workspace")


def test_publish_repair_runs_branch_commit_push_and_pr():
    github = GitHubMCP(token="token", owner="owner", repository="repo")
    calls = []

    def fake_git(_workspace, args):
        calls.append(("git", args))
        if args == ["status", "--porcelain"]:
            return " M app.py"
        if args == ["rev-parse", "HEAD"]:
            return "commit-sha"
        return ""

    github._git = fake_git
    github.create_branch = lambda branch, target: calls.append(("branch", branch, target)) or branch
    github.create_pull_request = lambda branch, target: calls.append(("pr", branch, target)) or "https://github.test/pr/1"

    result = github.publish_repair("workspace", "repair/guid", "Repair guid", target_branch="dev")

    assert result == "https://github.test/pr/1"
    assert ("branch", "repair/guid", "dev") in calls
    assert ("pr", "repair/guid", "dev") in calls
    assert ("git", ["push", "origin", "repair/guid"]) in calls
