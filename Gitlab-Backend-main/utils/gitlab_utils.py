import json
import httpx
import gitlab
import re
from typing import Dict, Any, List, Tuple
import os
 
from dotenv import load_dotenv
load_dotenv()
 
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
HEADERS = {"PRIVATE-TOKEN": GITLAB_TOKEN}
 
 
def load_gitlab_cookies() -> Dict[str, str]:
    """Load GitLab cookies from a JSON file."""
    try:
        with open("gitlab_cookies.json", "r") as f:
            cookies = json.load(f)
            return {cookie['name']: cookie['value'] for cookie in cookies}
    except Exception as e:
        print("⚠️ Failed to load cookies:", e)
        return {}
 
async def create_branch_if_not_exists(project_id: int, branch_name: str, ref_branch: str) -> None:
    """Create a branch if it does not exist."""
    async with httpx.AsyncClient() as client_http:
        resp = await client_http.get(
            f"https://gitlab.com/api/v4/projects/{project_id}/repository/branches/{branch_name}",
            headers=HEADERS,
        )
        if resp.status_code == 404:
            create_resp = await client_http.post(
                f"https://gitlab.com/api/v4/projects/{project_id}/repository/branches",
                headers=HEADERS,
                json={"branch": branch_name, "ref": ref_branch},
            )
            if create_resp.status_code not in (200, 201):
                raise Exception(f"Branch creation failed: {create_resp.text}")
        elif resp.status_code != 200:
            raise Exception(f"Error checking branch: {resp.text}")
 
async def create_merge_request(project_id: int, source_branch: str, target_branch: str, title: str, description: str) -> Dict[str, Any]:
    """Create a merge request in GitLab."""
    async with httpx.AsyncClient() as client_http:
        mr_resp = await client_http.post(
            f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests",
            headers=HEADERS,
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
            },
        )
        if mr_resp.status_code not in (200, 201):
            raise Exception(f"MR creation failed: {mr_resp.text}")
        return mr_resp.json()
 
async def get_mr_changes(project_id: int, mr_iid: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Get changes and diff refs for a merge request."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes",
            headers=HEADERS
        )
        if response.status_code != 200:
            raise Exception(f"Failed to fetch MR changes: {response.text}")
        data = response.json()
        return data.get("changes", []), data.get("diff_refs", {})
 
async def post_mr_comment(project_id: int, mr_iid: int, comment: str) -> Dict[str, Any]:
    """Post a general comment on a merge request."""
    async with httpx.AsyncClient() as client_http:
        comment_resp = await client_http.post(
            f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes",
            headers=HEADERS,
            json={"body": comment},
        )
        if comment_resp.status_code not in (200, 201):
            raise Exception(f"Failed to post comment: {comment_resp.text}")
        return comment_resp.json()
 
def extract_line_numbers_from_diff(diff_text: str) -> Dict[int, str]:
    """
    Maps added lines in the diff to their new file line numbers.
    Returns: {new_line_number: line_content}
    """
    line_mapping = {}
    new_line_num = None
    old_line_num = None
    for line in diff_text.split('\n'):
        if line.startswith('@@'):
            m = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if m:
                old_line_num = int(m.group(1))
                new_line_num = int(m.group(2))
            continue
        if new_line_num is None or old_line_num is None:
            # Skip lines until we have a header
            continue
        if line.startswith('+') and not line.startswith('+++'):
            line_mapping[new_line_num] = line[1:]
            new_line_num += 1
        elif line.startswith('-') and not line.startswith('---'):
            old_line_num += 1
        else:
            new_line_num += 1
            old_line_num += 1
    return line_mapping
 
def split_diff_by_hunks(diff_text: str):
    """Yield (hunk_header, hunk_lines) for each diff hunk."""
    lines = diff_text.splitlines()
    hunk = []
    hunk_header = None
    for line in lines:
        if line.startswith('@@'):
            if hunk:
                yield (hunk_header, hunk)
                hunk = []
            hunk_header = line
        if hunk_header:
            hunk.append(line)
    if hunk:
        yield (hunk_header, hunk)
 