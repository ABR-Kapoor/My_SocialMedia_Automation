"""
LinkedIn Platform — OAuth2 PKCE + UGC Post API.
Posts to Abeer's personal LinkedIn profile (not company page).
Token is stored in Neon DB after one-time /auth_linkedin flow.
"""
import logging
import requests
from config import (
    LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET,
    LINKEDIN_REDIRECT_URI, LINKEDIN_ACCESS_TOKEN,
)
from database.models import save_oauth_token, get_oauth_token

logger = logging.getLogger(__name__)

LINKEDIN_AUTH_URL   = "https://www.linkedin.com/oauth/v2/authorization"
LINKEDIN_TOKEN_URL  = "https://www.linkedin.com/oauth/v2/accessToken"
LINKEDIN_USERINFO   = "https://api.linkedin.com/v2/userinfo"
LINKEDIN_UGC_POSTS  = "https://api.linkedin.com/v2/ugcPosts"
LINKEDIN_MEDIA_UPLOAD = "https://api.linkedin.com/v2/assets?action=registerUpload"
SCOPES = "openid profile email w_member_social"


class LinkedInPlatform:

    def get_auth_url(self, state: str = "random_state_123") -> str:
        """Return the OAuth URL for the /auth_linkedin flow."""
        params = {
            "response_type": "code",
            "client_id":     LINKEDIN_CLIENT_ID,
            "redirect_uri":  LINKEDIN_REDIRECT_URI,
            "scope":         SCOPES,
            "state":         state,
        }
        from urllib.parse import urlencode
        return f"{LINKEDIN_AUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict:
        """Exchange OAuth code for access token; store in Neon DB."""
        data = {
            "grant_type":    "authorization_code",
            "code":          code,
            "redirect_uri":  LINKEDIN_REDIRECT_URI,
            "client_id":     LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
        }
        resp = requests.post(LINKEDIN_TOKEN_URL, data=data)
        resp.raise_for_status()
        token_data = resp.json()
        access_token = token_data["access_token"]

        # Get person URN from userinfo
        person_urn = await self._get_person_urn(access_token)

        await save_oauth_token(
            platform="linkedin",
            access_token=access_token,
            person_urn=person_urn,
            extra_data=token_data,
        )
        logger.info(f"✅ LinkedIn token stored for URN: {person_urn}")
        return {"access_token": access_token, "person_urn": person_urn}

    async def _get_access_token(self) -> tuple[str, str]:
        """Retrieve stored token and person URN from DB or env."""
        token_data = await get_oauth_token("linkedin")
        if token_data and token_data.get("access_token"):
            urn = token_data.get("person_urn", "")
            # Ensure full URN format — DB stores raw sub ID, API needs urn:li:person:xxx
            if urn and not urn.startswith("urn:li:person:"):
                urn = f"urn:li:person:{urn}"
            return token_data["access_token"], urn
        # Fall back to env (for initial setup)
        if LINKEDIN_ACCESS_TOKEN:
            urn = await self._get_person_urn(LINKEDIN_ACCESS_TOKEN)
            return LINKEDIN_ACCESS_TOKEN, urn
        raise RuntimeError("LinkedIn not authenticated. Run /auth_linkedin first.")

    async def _get_person_urn(self, access_token: str) -> str:
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = requests.get(LINKEDIN_USERINFO, headers=headers)
        resp.raise_for_status()
        sub = resp.json().get("sub", "")
        return f"urn:li:person:{sub}"

    async def post(self, content: str, image_bytes: bytes | None = None) -> str:
        """
        Post to LinkedIn personal profile.
        Returns the post URL (best effort — LinkedIn API doesn't return direct URL).
        """
        access_token, person_urn = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }

        # Build UGC post body
        post_body: dict = {
            "author":         person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary":    {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        # If image provided — upload it first
        if image_bytes:
            try:
                media_urn = await self._upload_image(access_token, person_urn, image_bytes)
                post_body["specificContent"]["com.linkedin.ugc.ShareContent"].update({
                    "shareMediaCategory": "IMAGE",
                    "media": [{
                        "status":      "READY",
                        "media":       media_urn,
                        "description": {"text": ""},
                        "title":       {"text": ""},
                    }],
                })
            except Exception as e:
                logger.warning(f"Image upload failed, posting text-only: {e}")

        resp = requests.post(LINKEDIN_UGC_POSTS, json=post_body, headers=headers)

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"LinkedIn post failed [{resp.status_code}]: {resp.text}")

        post_id = resp.headers.get("x-restli-id", "")
        url = f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else \
              "https://www.linkedin.com/in/abeer-kapoor/"
        logger.info(f"✅ LinkedIn post published: {url}")
        return url

    async def _upload_image(self, access_token: str, person_urn: str, image_bytes: bytes) -> str:
        """Upload image to LinkedIn and return the media asset URN."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type":  "application/json",
        }
        register_body = {
            "registerUploadRequest": {
                "recipes":                   ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner":                     person_urn,
                "serviceRelationships": [{
                    "relationshipType": "OWNER",
                    "identifier":       "urn:li:userGeneratedContent",
                }],
            }
        }
        r = requests.post(LINKEDIN_MEDIA_UPLOAD, json=register_body, headers=headers)
        r.raise_for_status()
        data        = r.json()["value"]
        upload_url  = data["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset_urn   = data["asset"]

        # Upload the binary
        upload_headers = {"Authorization": f"Bearer {access_token}"}
        requests.put(upload_url, data=image_bytes, headers=upload_headers).raise_for_status()
        return asset_urn
