from pydantic import BaseModel

class MRRequest(BaseModel):
    """Model for creating a new merge request."""
    project_id: int
    source_branch: str
    target_branch: str
    new_branch_name: str
    mr_title: str
    mr_description: str = ""

class ExistingMRRequest(BaseModel):
    """Model for referencing an existing merge request."""
    project_id: int
    mr_iid: int

class ReviewRequest(BaseModel):
    """Model for requesting a review on a merge request."""
    project_path: str
    merge_request_iid: str 