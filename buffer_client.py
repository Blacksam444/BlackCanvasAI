import json
import os
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class BufferError(Exception):
    pass


class BufferRejected(BufferError):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


ORGANIZATIONS_QUERY = "query { account { organizations { id name } } }"
CHANNELS_QUERY = """
    query Channels($input: ChannelsInput!) {
        channels(input: $input) {
            id name displayName service type isDisconnected isLocked isQueuePaused
            metadata { ... on PinterestMetadata { boards { serviceId name } } }
        }
    }
"""
CREATE_POST = """
    mutation SchedulePost($input: CreatePostInput!) {
        createPost(input: $input) {
            __typename
            ... on PostActionSuccess { post { id dueAt status } }
            ... on MutationError { message }
        }
    }
"""


class BufferClient:
    def __init__(self):
        self.api_key = os.environ.get("BUFFER_API_KEY", "").strip()

    def request(self, query, variables=None):
        request = Request(
            "https://api.buffer.com",
            data=json.dumps({"query": query, "variables": variables or {}}).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        try:
            with build_opener(NoRedirects()).open(request, timeout=15) as response:
                result = json.load(response)
        except HTTPError as error:
            if error.code in (401, 403):
                raise BufferRejected("Buffer rejected the API key or account permissions.") from error
            raise BufferError("Buffer did not confirm the request.") from error
        except (OSError, ValueError) as error:
            raise BufferError("Buffer did not confirm the request.") from error
        if not isinstance(result, dict) or result.get("errors") or not isinstance(result.get("data"), dict):
            raise BufferError("Buffer returned an unexpected response.")
        return result["data"]

    def organizations(self):
        return self.request(ORGANIZATIONS_QUERY)["account"]["organizations"]

    def channels(self, organization_id):
        channels = self.request(CHANNELS_QUERY, {"input": {"organizationId": organization_id}})["channels"]
        return [
            {
                "id": channel["id"],
                "name": channel["displayName"] or channel["name"],
                "platform": channel["service"].lower(),
                "boards": (channel.get("metadata") or {}).get("boards", []),
            }
            for channel in channels
            if channel["service"].lower() in {"facebook", "instagram", "pinterest", "tiktok"}
            and not (channel["isDisconnected"] or channel["isLocked"] or channel["isQueuePaused"])
            and (channel["service"].lower() != "facebook" or channel["type"].lower() == "page")
        ]

    def schedule(self, post):
        result = self.request(CREATE_POST, {"input": post}).get("createPost") or {}
        kind = result.get("__typename")
        if kind in {"InvalidInputError", "LimitReachedError", "NotFoundError", "UnauthorizedError"}:
            raise BufferRejected(str(result.get("message") or "Buffer rejected this post.")[:300])
        if kind != "PostActionSuccess" or not result.get("post", {}).get("id"):
            raise BufferError("Buffer did not confirm the post.")
        return result["post"]
