from pydantic import BaseModel

class PlatformBase(BaseModel):
    platform_name: str
    api_base_url: str
    ws_base_url: str
    account_api_type: str
    market_api_type: str

class PlatformResponse(PlatformBase):
    platform_id: int

    class Config:
        from_attributes = True
