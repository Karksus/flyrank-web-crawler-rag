from typing import List, Optional

from pydantic import BaseModel, Field


class PublicOpinionItem(BaseModel):
    source: str
    source_label: str
    title: str
    url: str
    snippet: str = ""
    score: int = 0
    comments: int = 0
    created_at: Optional[str] = None
    author: Optional[str] = None


class PublicOpinionSentiment(BaseModel):
    label: str
    summary: str
    positives: List[str] = Field(default_factory=list)
    negatives: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    method: str = "unknown"


class PublicOpinionSource(BaseModel):
    name: str
    status: str
    count: int = 0


class PublicOpinionSubreddit(BaseModel):
    name: str
    title: Optional[str] = None
    subscribers: Optional[int] = None
    url: Optional[str] = None
    description: Optional[str] = None


class PublicOpinionResponse(BaseModel):
    company: str
    query: str
    checked_at: str
    cached: bool = False
    subreddit: Optional[PublicOpinionSubreddit] = None
    sources: List[PublicOpinionSource] = Field(default_factory=list)
    sentiment: PublicOpinionSentiment
    items: List[PublicOpinionItem] = Field(default_factory=list)
    disclaimer: str
