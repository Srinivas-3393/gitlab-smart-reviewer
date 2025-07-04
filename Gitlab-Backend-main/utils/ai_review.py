import os
from openai import AsyncOpenAI
from typing import Dict, Optional
import re
import json

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
async_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

def parse_plain_text_review(review_text: str) -> Dict[int, str]:
    """
    Converts plain text AI review into a dictionary: {line_num: comment}
    Only one comment per issue, at the starting line (even for ranges).
    """
    if not isinstance(review_text, str):
        print("⚠️ parse_plain_text_review got non-str input:", type(review_text))
        return {}

    review_map = {}

    for block in review_text.strip().split("\n\n"):
        # Match: [Line 42] or [Line 10-12] or Line 42
        line_match = re.search(r"(?:\[)?Line[s]*\s*(\d+(?:-\d+)?)(?:[\]:])?", block, re.IGNORECASE)
        # Match: Fix: some suggestion OR Recommendation: some suggestion OR Problem: ...
        comment_match = re.search(r"(?:Fix|Recommendation|Problem):\s*(.+)", block, re.IGNORECASE)
        if line_match and comment_match:
            line_part = line_match.group(1)
            comment = comment_match.group(1).strip()
            # Handle line ranges like 10-12: only use the starting line
            if '-' in line_part:
                start, _ = map(int, line_part.split('-'))
                review_map[start] = comment
            else:
                review_map[int(line_part)] = comment
        else:
            print("⚠️ Skipped block — no valid line or comment match found.")
    if not review_map:
        print("⚠️ No valid comments found in review text.")
    return review_map

async def generate_structured_code_review(diff_text: str, file_path: Optional[str] = None, line_mapping: Optional[Dict[int, str]] = None) -> str:
    """
    Generate a focused code review that specifically addresses changed code,
    performance impacts, and potential improvements.
    """
    if not diff_text.strip():
        return "No code changes to review."
    if line_mapping is None:
        from utils.gitlab_utils import extract_line_numbers_from_diff
        line_mapping = extract_line_numbers_from_diff(diff_text)
    file_type = "unknown"
    if file_path:
        file_type = file_path.split('.')[-1].lower() if '.' in file_path else "unknown"
    system_prompt = f"""
You are a senior software engineer with deep expertise in {file_type}.

Your task is to review Git diffs and provide highly focused, professional feedback on only the lines that changed.

Use a calm, helpful tone. Be brief, constructive, and actionable.

REVIEW FORMAT:
1. Start each issue with "Issue 1:", "Issue 2:", etc.
2. After the issue number, include the affected line number(s) in square brackets, like [Line 12] or [Line 22-26]
3. Each issue must include:
   - A one-line title
   - "Problem:" followed by a short explanation
   - "Fix:" followed by a clear recommendation
4. Leave one blank line between each issue
5. Use plain text only – do not include markdown, emojis, lists, or extra sections

IMPORTANT:
- Only comment on lines that are present in the following mapping of changed lines to their new file line numbers:
{line_mapping}
- When referencing a line, use ONLY the line numbers from this mapping.
- Do NOT reference or comment on any lines not present in this mapping.
- If you find no issues, return an empty string.
"""
    user_prompt = f"""
Review this Git diff for the file: {file_path or 'Unknown File'}

{diff_text}

Please use the line numbers from the mapping above when referencing issues.
If you find no issues or if the git diff is for binary files, return "".
"""
    try:
        response = await async_client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.0,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating review: {str(e)}" 