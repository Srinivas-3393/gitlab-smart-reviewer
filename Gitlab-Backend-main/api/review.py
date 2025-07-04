from fastapi import APIRouter, HTTPException
from models.schemas import ReviewRequest
from utils.gitlab_utils import (
    get_mr_changes, extract_line_numbers_from_diff, split_diff_by_hunks
)
from utils.ai_review import generate_structured_code_review, parse_plain_text_review
import httpx
import os
import gitlab

router = APIRouter()

GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")

@router.post("/review")
async def review_mr(data: ReviewRequest):
    try:
        # Step 1: Get project ID from project_path
        encoded_path = data.project_path.replace("/", "%2F")
        async with httpx.AsyncClient() as client:
            project_resp = await client.get(
                f"https://gitlab.com/api/v4/projects/{encoded_path}",
                headers={"PRIVATE-TOKEN": GITLAB_TOKEN}
            )
            if project_resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch project ID")
            project_id = project_resp.json().get("id")
            if not project_id:
                raise HTTPException(status_code=400, detail="Project ID not found")

        # Step 2: Fetch MR changes and diff refs
        changes, diff_refs = await get_mr_changes(project_id, data.merge_request_iid)
        if not changes:
            return {"message": "No changes detected in MR."}

        all_status = []

        # Step 3: Process each changed file
        for change in changes:
            diff_text = change.get("diff", "")
            file_path = change.get("new_path") or change.get("old_path")

            print(f"\n===== RAW DIFF for {file_path} =====\n{diff_text}\n==============================\n")

            # If the diff is large or the file is new, split by hunks
            hunks = list(split_diff_by_hunks(diff_text))
            if len(hunks) > 1 or diff_text.startswith('@@ -0,0'):
                print(f"Reviewing by hunks for {file_path}")
                for hunk_header, hunk_lines in hunks:
                    hunk_diff = '\n'.join(hunk_lines)
                    hunk_line_mapping = extract_line_numbers_from_diff(hunk_diff)
                    print(f"\n===== HUNK HEADER for {file_path} =====\n{hunk_header}\n==============================\n")
                    print(f"\n===== HUNK DIFF for {file_path} =====\n{hunk_diff}\n==============================\n")
                    print(f"\n===== HUNK LINE MAPPING for {file_path} =====\n{hunk_line_mapping}\n==============================\n")
                    review_text = await generate_structured_code_review(hunk_diff, file_path, hunk_line_mapping)
                    print(f"\n===== AI REVIEW OUTPUT for {file_path} (hunk) =====\n{review_text}\n==============================\n")
                    # Parse and post inline comments for this hunk
                    parsed_review = parse_plain_text_review(review_text)
                    if not parsed_review:
                        all_status.append(f"ℹ️ No review issues found in hunk of {file_path}")
                        continue
                    # Map hunk line numbers to global line numbers
                    for hunk_line_num, comment in parsed_review.items():
                        global_line_num = None
                        if hunk_line_num in hunk_line_mapping:
                            global_line_num = hunk_line_num
                        else:
                            possible = [k for k in hunk_line_mapping.keys() if isinstance(k, int)]
                            if possible:
                                global_line_num = min(possible, key=lambda x: abs(x - hunk_line_num))
                        if global_line_num is not None:
                            post_inline_comments_from_review(
                                parsed_review={global_line_num: comment},
                                file_path=file_path,
                                project_id=project_id,
                                mr_iid=data.merge_request_iid,
                                diff_refs=diff_refs,
                                diff_text=diff_text
                            )
                            all_status.append(f"✅ Inline comment posted for {file_path}:{global_line_num}")
                        else:
                            all_status.append(f"❌ Could not map hunk line {hunk_line_num} to global line in {file_path}")
                continue

            # For small diffs, review as a whole
            line_mapping = extract_line_numbers_from_diff(diff_text)
            review_text = await generate_structured_code_review(file_path, diff_text, line_mapping)
            print(f"\n===== AI REVIEW OUTPUT for {file_path} =====\n{review_text}\n==============================\n")

            # Step 5: Parse AI output (should be {line_num: comment})
            if isinstance(review_text, list):
                parsed_review = {item["line"]: item["comment"] for item in review_text if "line" in item and "comment" in item}
            elif isinstance(review_text, dict):
                parsed_review = review_text
            elif isinstance(review_text, str):
                try:
                    try_parse = json.loads(review_text)
                    if isinstance(try_parse, list):
                        parsed_review = {item["line"]: item["comment"] for item in try_parse if "line" in item and "comment" in item}
                    elif isinstance(try_parse, dict):
                        parsed_review = try_parse
                    else:
                        parsed_review = parse_plain_text_review(review_text)
                except Exception:
                    parsed_review = parse_plain_text_review(review_text)
            else:
                print("Unexpected review_text type:", type(review_text), review_text)
                parsed_review = {}

            if not parsed_review:
                all_status.append(f"ℹ️ No review issues found in {file_path}")
                continue

            print(f"Parsed review for {file_path}: {parsed_review}")
            post_inline_comments_from_review(
                parsed_review=parsed_review,
                file_path=file_path,
                project_id=project_id,
                mr_iid=data.merge_request_iid,
                diff_refs=diff_refs,
                diff_text=diff_text
            )

        return {
            "message": "Review completed",
            "status": all_status
        }

    except Exception as e:
        print(f"❌ Exception in review_mr: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error: {str(e)}")

# Helper for posting inline comments (move from main.py or utils if needed)
def post_inline_comments_from_review(
    parsed_review: dict,  # {line_num: comment}
    file_path: str,
    project_id: int,
    mr_iid: int,
    diff_refs: dict,  # {base_sha, start_sha, head_sha}
    diff_text: str = None  # Pass the diff text for this file
) -> list[str]:
    import gitlab
    status = []
    print(f"Posting inline comments for {file_path} in MR {mr_iid} of project {project_id}")
    try:
        from utils.gitlab_utils import extract_line_numbers_from_diff
        line_mapping = extract_line_numbers_from_diff(diff_text) if diff_text else {}
        valid_line_numbers = set(line_mapping.keys())
        gl = gitlab.Gitlab('https://gitlab.com', private_token=GITLAB_TOKEN)
        project = gl.projects.get(project_id)
        mr = project.mergerequests.get(mr_iid)
        for line_num, comment in parsed_review.items():
            if line_num not in valid_line_numbers:
                print(f"⏭️ Skipping comment for {file_path}:{line_num} - not in diff mapping")
                status.append(f"⏭️ Skipped {file_path}:{line_num} (not in diff mapping)")
                continue
            print(f"Posting comment for {file_path}:{line_num} - {comment}")
            try:
                mr.discussions.create({
                    'body': comment,
                    'position': {
                        'position_type': 'text',
                        'new_path': file_path,
                        'old_path': file_path,
                        'new_line': line_num,
                        'base_sha': diff_refs['base_sha'],
                        'head_sha': diff_refs['head_sha'],
                        'start_sha': diff_refs['start_sha']
                    }
                })
                status.append(f"✅ Commented {file_path}:{line_num}")
                print(f"✅ Commented {file_path}:{line_num}")
            except Exception as e:
                status.append(f"❌ Failed {file_path}:{line_num} ({str(e)})")
                print(f"❌ Failed to post comment for {file_path}:{line_num}: {e}")
    except Exception as e:
        status.append(f"❌ Error posting comments: {str(e)}")
    return status 