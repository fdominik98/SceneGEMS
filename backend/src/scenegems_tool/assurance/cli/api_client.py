"""A thin httpx client for the control node's operator API, with the server's reasons in its errors."""

from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

DEFAULT_TIMEOUT_S = 30.0


class ApiError(Exception):
    """The operator API refused a request, or could not be reached. reasons are the server's, one per line."""

    def __init__(self, status: Optional[int], reasons: List[str]):
        self.status = status
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def reasons_of(detail: Any) -> List[str]:
    """The readable reasons in an error body's detail: text, a config rejection, a payload rejection or FastAPI's validation errors."""
    if isinstance(detail, str):
        return [detail]
    if isinstance(detail, dict):
        reasons = [str(reason) for reason in detail.get("reasons") or []]
        if not reasons and detail.get("message"):
            reasons = [str(detail["message"])]
        reasons.extend(_located(error) for error in detail.get("errors") or [])
        return reasons or [str(detail)]
    if isinstance(detail, list):
        return [_located(error) for error in detail] or ["unknown error"]
    return [str(detail)]


def _located(error: Any) -> str:
    if isinstance(error, dict) and "msg" in error:
        location = ".".join(str(part) for part in error.get("loc") or [])
        return f"{location}: {error['msg']}" if location else str(error["msg"])
    return str(error)


class OperatorApi:
    def __init__(self, base_url: str, transport: Optional[httpx.BaseTransport] = None, timeout_s: float = DEFAULT_TIMEOUT_S):
        self._client = httpx.Client(base_url=base_url.rstrip("/"), transport=transport, timeout=timeout_s)
        self.base_url = base_url

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OperatorApi":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    def get(self, path: str, **params: Any) -> Any:
        return self._json("GET", path, params=_query(params))

    def post(self, path: str, content: Optional[bytes] = None, content_type: Optional[str] = None, **params: Any) -> Any:
        headers = {"Content-Type": content_type} if content_type else None
        return self._json("POST", path, params=_query(params), content=content, headers=headers)

    def delete(self, path: str) -> None:
        self._json("DELETE", path)

    def download(self, path: str, target: Path, **params: Any) -> int:
        """Streams a GET response body into target; returns its size in bytes. A failed request leaves no file."""
        try:
            with self._client.stream("GET", path, params=_query(params)) as response:
                if response.is_error:
                    response.read()
                    raise _error_of(response)
                size = 0
                with target.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
                        size += len(chunk)
                return size
        except httpx.HTTPError as error:
            target.unlink(missing_ok=True)
            raise ApiError(None, [f"cannot reach {self.base_url}: {error}"]) from error
        except ApiError:
            target.unlink(missing_ok=True)
            raise

    def _json(self, method: str, path: str, **options: Any) -> Any:
        try:
            response = self._client.request(method, path, **options)
        except httpx.HTTPError as error:
            raise ApiError(None, [f"cannot reach {self.base_url}: {error}"]) from error
        if response.is_error:
            raise _error_of(response)
        return response.json() if response.content else None


def _query(params: Dict[str, Any]) -> Dict[str, Any]:
    return {key: (str(value).lower() if isinstance(value, bool) else value) for key, value in params.items() if value is not None}


def _error_of(response: httpx.Response) -> ApiError:
    try:
        body = response.json()
    except ValueError:
        return ApiError(response.status_code, [response.text.strip() or response.reason_phrase])
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return ApiError(response.status_code, reasons_of(detail))
