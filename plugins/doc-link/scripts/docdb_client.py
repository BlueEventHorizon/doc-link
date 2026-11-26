"""[doc-db]の MCP（Streamable HTTP）エンドポイントを直接叩く軽量クライアント（標準ライブラリだけ）。

DES-011 §2.2・§5・§7、REQ-006 FR-027・FR-028・NFR-009 を実装する。入口 script ではないので、PEP 723 と
ロックは持たない。`http://localhost:<port>/mcp` へ JSON-RPC を、`initialize` → `notifications/initialized` →
`tools/call` の順に送る。`Mcp-Session-Id` は、同じ `Client` の間、保持する。サーバーは JSON と SSE
（`text/event-stream`）のどちらでも応答しうるので、どちらも同じ JSON-RPC の応答（dict）へ解析する。

## 使う [doc-db] の tool

`query`・`sync_documents`・`get_sync_status` の 3 つだけである（[doc-db]の既存の入出力。互換のために残される）。
[doc-db]の設定ファイル `~/.doc-db/doc-db.yaml` から読むのは、`server.port` の整数だけである。

## 情報保護（要件 NFR-009）[MANDATORY]

認証情報（OpenAI の鍵）を読まず、渡さず、出力しない。環境変数を読まない。設定ファイルの本文も例外・戻り値に載せない。
例外が持つのは、失敗の分類・HTTP の状態コード・URL（localhost とポートだけ）・[doc-db]の識別子（`error.data.code`）
である。HTTP の本文・JSON-RPC のエラーの文言は、利用者向けの出力に載せないので、例外の `detail` には入れない
（`ToolError.message` と `HttpError.body` は、呼び出し側が出力しない前提で保持する）。

## テスト境界

HTTP の送信は `post_json_rpc` の 1 関数に閉じる。`Client` の `transport` 引数で差し替えられる。ポートの解決は
`config_path` で差し替えられる。
"""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "doc-link"
CLIENT_VERSION = "1.0"

#: [doc-db]の設定ファイル。読むのは `port` だけ
DEFAULT_CONFIG_PATH = Path.home() / ".doc-db" / "doc-db.yaml"

#: 通常の操作の HTTP の待ち時間（秒）。検索・同期の投入・状態の取得。TBD: 実測で決める値の暫定
OPERATION_TIMEOUT_SECONDS = 600
#: 接続の確認（`initialize`）の HTTP の待ち時間（秒）。localhost への接続の確認だけに使う。TBD: 実測で決める値の暫定
PROBE_TIMEOUT_SECONDS = 1

#: セッションを付けた要求が、この状態コードを返したとき、セッションの終了を意味する
HTTP_SESSION_EXPIRED = 404

_PORT_LINE = re.compile(r"^\s*port\s*:\s*(\d+)\s*(?:#.*)?$", re.MULTILINE)


class DocDbClientError(Exception):
    """クライアントの基底の例外。`detail` は、利用者向けの出力に載せてよい、失敗の分類（自然文）。"""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail if detail is not None else type(self).__name__


class PortUnavailable(DocDbClientError):
    """設定ファイルから `port` を得られない（ファイルが無い・読めない・`port` が無い）。"""


class TransportError(DocDbClientError):
    """接続そのものを確立できなかった（未起動・接続の拒否・待ち時間の超過）。接続できない (a) の根拠になる。"""


class HttpError(DocDbClientError):
    """HTTP の 4xx・5xx。接続は確立している。"""

    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} ({url})", f"HttpError: HTTP {status} ({url})")
        self.status = status
        self.body = body
        self.url = url


class ProtocolError(DocDbClientError):
    """応答が MCP・JSON-RPC の契約を満たさない（解析できない・空の応答・セッションを確立できない）。"""


class ToolError(DocDbClientError):
    """`tools/call` が、エラーを返した。`code`（数値）・`identifier`（`error.data.code`。無ければ `None`）を持つ。

    判別は識別子だけで行う。文言・数値の `code` では判別しない（要件 FR-028）。
    """

    def __init__(self, message: str, code: int | None = None, data=None):
        identifier = None
        if isinstance(data, dict) and isinstance(data.get("code"), str):
            identifier = data["code"]
        detail = "ToolError"
        if identifier is not None:
            detail += f": {identifier}"
        elif code is not None:
            detail += f": JSON-RPC {code}"
        # OpenAI の HTTP の状態コード（[doc-db]が確かめられたときだけ付ける）。状態コードは出力に載せてよい
        status = data.get("http_status") if isinstance(data, dict) else None
        if isinstance(status, int) and not isinstance(status, bool):
            detail += f"（OpenAI の HTTP {status}）"
        super().__init__(message, detail)
        self.message = message
        self.code = code
        self.data = data
        self.identifier = identifier


# --- ポートの解決 --------------------------------------------------------------


def read_port(config_path: str | Path | None = None) -> int:
    """[doc-db]の設定ファイルから `port` を読む。得られないときは `PortUnavailable`。

    既定のポートを仮定しない。[doc-db]は設定ファイルが無いと起動できないので、読めないときは、接続も
    起動も試みない（要件 FR-027、DES-011 §2.2）。設定ファイルの本文は、戻り値にも例外にも載せない。
    """
    path = DEFAULT_CONFIG_PATH if config_path is None else Path(config_path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PortUnavailable(
            "doc-db の設定ファイルを読めない",
            f"設定ファイルを読めない（{type(exc).__name__}）",
        ) from exc
    match = _PORT_LINE.search(text)
    if match is None:
        raise PortUnavailable(
            "doc-db の設定ファイルに port が無い", "設定ファイルに port が無い"
        )
    port = int(match.group(1))
    if not 1 <= port <= 65535:
        raise PortUnavailable(
            "doc-db の設定ファイルの port が範囲外", "設定ファイルの port が範囲外"
        )
    return port


def endpoint_url(port: int) -> str:
    return f"http://localhost:{port}/mcp"


# --- 応答の解析 ----------------------------------------------------------------


def parse_response(raw: bytes, content_type: str, expected_id=None) -> dict:
    """JSON の応答と SSE の応答を、同じ JSON-RPC の応答（dict）へ解析する。

    SSE は、送った要求の `id` と一致する応答を選ぶ。サーバー発の通知（`id` が無い）と、別の `id` のメッセージは
    読み飛ばす。
    """
    body = raw.decode("utf-8", errors="replace")
    if "text/event-stream" in (content_type or "").lower():
        stray: dict | None = None
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data:
                continue
            try:
                message = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ProtocolError(
                    "SSE の data を JSON として解析できない",
                    "ProtocolError: SSE の解析",
                ) from exc
            if not isinstance(message, dict) or "id" not in message:
                continue
            if expected_id is None or message.get("id") == expected_id:
                return message
            if stray is None:
                stray = message
        if stray is not None:
            raise ProtocolError(
                "SSE に、送った要求と一致する id の応答が無い",
                "ProtocolError: SSE の id の不一致",
            )
        raise ProtocolError("SSE に data が無い", "ProtocolError: SSE の応答が空")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ProtocolError(
            "応答を JSON として解析できない", "ProtocolError: JSON の解析"
        ) from exc
    if not isinstance(parsed, dict):
        raise ProtocolError(
            "応答が JSON のオブジェクトでない", "ProtocolError: 応答の形"
        )
    return parsed


# --- HTTP の送信（唯一の境界。テストはここへ応答を注入する） -------------------


def post_json_rpc(
    url: str, payload: dict, session_id: str | None, timeout: float
) -> tuple[dict | None, dict]:
    """JSON-RPC の本文を POST し、`(応答の dict または None, 応答のヘッダ（名前は小文字）)` を返す。

    通知（`id` が無い本文）は、空の本文が返るので、応答は `None` である。
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json, text/event-stream")
    if session_id:
        request.add_header("Mcp-Session-Id", session_id)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        raise HttpError(exc.code, body, url) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise TransportError(
            "doc-db に接続できない", f"TransportError（{type(exc).__name__}）"
        ) from exc
    if not raw:
        return None, headers
    return (
        parse_response(raw, headers.get("content-type", ""), payload.get("id")),
        headers,
    )


# --- クライアント --------------------------------------------------------------


class Client:
    """MCP のセッションを保持し、同じセッションで `tools/call` を発行する。"""

    def __init__(
        self,
        port: int,
        timeout: float = OPERATION_TIMEOUT_SECONDS,
        transport=post_json_rpc,
    ):
        self.port = int(port)
        self.url = endpoint_url(self.port)
        self.timeout = timeout
        self._transport = transport
        self.session_id: str | None = None
        self._next_id = 1
        self._initialized = False

    def initialize(self) -> None:
        """`initialize` → `notifications/initialized`。接続の可否の唯一の根拠である。"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._take_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
        response, headers = self._transport(self.url, payload, None, self.timeout)
        if response is None:
            raise ProtocolError(
                "initialize が空の応答を返した", "ProtocolError: initialize が空"
            )
        if "error" in response:
            raise ProtocolError(
                "initialize が失敗した", "ProtocolError: initialize の失敗"
            )
        self.session_id = headers.get("mcp-session-id")
        self._initialized = True
        self._transport(
            self.url,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            self.session_id,
            self.timeout,
        )

    def call(self, name: str, arguments: dict) -> dict:
        """`tools/call` を発行し、tool の応答の本文（dict）を返す。エラーは `ToolError`。"""
        if not self._initialized:
            self.initialize()
        response = self._call_once(name, arguments)
        if response is None:
            raise ProtocolError(
                f"tools/call({name}) が空の応答を返した", "ProtocolError: 応答が空"
            )
        if "error" in response:
            error = response["error"]
            error = error if isinstance(error, dict) else {}
            message = error.get("message")
            raise ToolError(
                message if isinstance(message, str) else "doc-db がエラーを返した",
                code=error.get("code") if isinstance(error.get("code"), int) else None,
                data=error.get("data"),
            )
        return _unwrap_result(name, response.get("result") or {})

    def _call_once(self, name: str, arguments: dict) -> dict | None:
        """1 回送る。セッションの終了（404）のときだけ、再確立して 1 回再送する。"""
        payload = {
            "jsonrpc": "2.0",
            "id": self._take_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        try:
            response, _ = self._transport(
                self.url, payload, self.session_id, self.timeout
            )
        except HttpError as exc:
            if exc.status != HTTP_SESSION_EXPIRED or not self.session_id:
                raise
            self.session_id = None
            self._initialized = False
            self.initialize()
            retry = dict(payload, id=self._take_id())
            response, _ = self._transport(
                self.url, retry, self.session_id, self.timeout
            )
        return response

    def query(self, key: str, series: str, query: str, mode: str, top_n: int) -> dict:
        return self.call(
            "query",
            {
                "key": key,
                "series": series,
                "query": query,
                "mode": mode,
                "top_n": top_n,
            },
        )

    def sync_documents(self, key: str, series: str, documents: list) -> dict:
        return self.call(
            "sync_documents",
            {"key": key, "series": series, "documents": list(documents)},
        )

    def get_sync_status(self, job_id: str) -> dict:
        return self.call("get_sync_status", {"job_id": job_id})

    def _take_id(self) -> int:
        current = self._next_id
        self._next_id += 1
        return current


def _unwrap_result(name: str, result: dict) -> dict:
    """`tools/call` の result から、tool の応答の本文を取り出す。`isError` の真は `ToolError`（識別子なし）。"""
    if result.get("isError"):
        raise ToolError(
            _text_content(result) or f"tools/call({name}) が isError を返した"
        )
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        try:
            parsed = json.loads(item.get("text", ""))
        except json.JSONDecodeError:
            return {"text": item.get("text", "")}
        return parsed if isinstance(parsed, dict) else {"text": item.get("text", "")}
    return result


def _text_content(result: dict) -> str:
    parts = [
        str(item.get("text", ""))
        for item in result.get("content") or []
        if isinstance(item, dict) and item.get("type") == "text"
    ]
    return "\n".join(part for part in parts if part)
