"""`docdb_client`（[doc-db]の MCP を直接叩くクライアント）のテスト。HTTP の送信は `transport` に注入する。"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT / "plugins" / "doc-link" / "scripts"))

import docdb_client  # noqa: E402


class FakeTransport:
    """送られた本文を記録し、用意した応答を順に返す。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, url, payload, session_id, timeout):
        self.calls.append((url, payload, session_id, timeout))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


INIT = (
    {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"serverInfo": {"name": "doc-db", "version": "0.4.0"}},
    },
    {"mcp-session-id": "S1"},
)
ACK = (None, {})


def tool_result(value):
    return ({"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": value}}, {})


class ReadPortTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "doc-db.yaml"

    def test_reads_only_the_port(self):
        self.path.write_text(
            'server:\n  port: 58081          # comment\n  db_path: "x"\nembedding:\n  model: m\n',
            encoding="utf-8",
        )
        self.assertEqual(docdb_client.read_port(self.path), 58081)

    def test_missing_unreadable_and_portless_files_have_no_default(self):
        self.assertRaises(
            docdb_client.PortUnavailable, docdb_client.read_port, self.path
        )
        self.path.write_text("server:\n  db_path: x\n", encoding="utf-8")
        self.assertRaises(
            docdb_client.PortUnavailable, docdb_client.read_port, self.path
        )
        self.path.write_text("server:\n  port: 70000\n", encoding="utf-8")
        self.assertRaises(
            docdb_client.PortUnavailable, docdb_client.read_port, self.path
        )

    def test_the_failure_does_not_carry_the_file_body(self):
        self.path.write_text("secret: hunter2\n", encoding="utf-8")
        with self.assertRaises(docdb_client.PortUnavailable) as raised:
            docdb_client.read_port(self.path)
        self.assertNotIn("hunter2", str(raised.exception) + raised.exception.detail)

    def test_endpoint_is_localhost_only(self):
        self.assertEqual(docdb_client.endpoint_url(58080), "http://localhost:58080/mcp")


class ParseResponseTest(unittest.TestCase):
    def test_json_and_sse_give_the_same_dict(self):
        body = {"jsonrpc": "2.0", "id": 7, "result": {"a": 1}}
        as_json = docdb_client.parse_response(
            json.dumps(body).encode(), "application/json"
        )
        sse = b"event: message\ndata: " + json.dumps(body).encode() + b"\n\n"
        as_sse = docdb_client.parse_response(sse, "text/event-stream", 7)
        self.assertEqual(as_json, as_sse)

    def test_sse_skips_notifications_and_other_ids(self):
        note = {"jsonrpc": "2.0", "method": "notifications/x"}
        other = {"jsonrpc": "2.0", "id": 1, "result": {}}
        mine = {"jsonrpc": "2.0", "id": 2, "result": {"ok": True}}
        sse = "".join(
            f"data: {json.dumps(m)}\n\n" for m in (note, other, mine)
        ).encode()
        self.assertEqual(docdb_client.parse_response(sse, "text/event-stream", 2), mine)

    def test_malformed_responses_are_protocol_errors(self):
        for raw, kind in (
            (b"not json", "application/json"),
            (b"[1]", "application/json"),
            (b"", "text/event-stream"),
            (b"data: {bad\n\n", "text/event-stream"),
            (b'data: {"id": 9}\n\n', "text/event-stream"),
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(docdb_client.ProtocolError):
                    docdb_client.parse_response(raw, kind, 1)


class ClientTest(unittest.TestCase):
    def client(self, replies, timeout=5):
        transport = FakeTransport(replies)
        return docdb_client.Client(
            58080, timeout=timeout, transport=transport
        ), transport

    def test_initialize_records_the_session(self):
        client, transport = self.client([INIT, ACK])
        client.initialize()
        self.assertEqual(client.session_id, "S1")
        self.assertEqual(transport.calls[0][1]["method"], "initialize")
        self.assertEqual(transport.calls[1][1]["method"], "notifications/initialized")
        self.assertEqual(transport.calls[1][2], "S1")
        self.assertEqual(transport.calls[0][3], 5)

    def test_initialize_failure_is_a_protocol_error(self):
        client, _ = self.client(
            [({"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "m"}}, {})]
        )
        self.assertRaises(docdb_client.ProtocolError, client.initialize)
        client, _ = self.client([(None, {})])
        self.assertRaises(docdb_client.ProtocolError, client.initialize)

    def test_query_sends_the_documented_arguments(self):
        client, transport = self.client([INIT, ACK, tool_result({"results": []})])
        found = client.query("K", "S", "task", "all", 20)
        self.assertEqual(found, {"results": []})
        call = transport.calls[2][1]
        self.assertEqual(call["method"], "tools/call")
        self.assertEqual(call["params"]["name"], "query")
        self.assertEqual(
            call["params"]["arguments"],
            {"key": "K", "series": "S", "query": "task", "mode": "all", "top_n": 20},
        )

    def test_sync_and_status_use_the_existing_tools(self):
        client, transport = self.client(
            [INIT, ACK, tool_result({"job_id": "J"}), tool_result({"status": "done"})]
        )
        self.assertEqual(
            client.sync_documents("K", "S", [{"path": "a.md"}]), {"job_id": "J"}
        )
        self.assertEqual(client.get_sync_status("J"), {"status": "done"})
        names = [c[1]["params"]["name"] for c in transport.calls[2:]]
        self.assertEqual(names, ["sync_documents", "get_sync_status"])
        self.assertEqual(
            transport.calls[2][1]["params"]["arguments"],
            {"key": "K", "series": "S", "documents": [{"path": "a.md"}]},
        )

    def test_a_tool_error_carries_only_the_identifier_and_numeric_code(self):
        error = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {
                "code": -31001,
                "message": "secret body",
                "data": {"code": "KEY_NOT_FOUND"},
            },
        }
        client, _ = self.client([INIT, ACK, (error, {})])
        with self.assertRaises(docdb_client.ToolError) as raised:
            client.query("K", "S", "t", "all", 1)
        exc = raised.exception
        self.assertEqual((exc.identifier, exc.code), ("KEY_NOT_FOUND", -31001))
        self.assertEqual(exc.detail, "ToolError: KEY_NOT_FOUND")
        self.assertNotIn("secret", exc.detail)

    def test_the_openai_http_status_is_carried_when_doc_db_confirmed_it(self):
        error = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {
                "code": -32603,
                "message": "secret",
                "data": {"code": "EMBEDDING_FAILED", "http_status": 401},
            },
        }
        client, _ = self.client([INIT, ACK, (error, {})])
        with self.assertRaises(docdb_client.ToolError) as raised:
            client.query("K", "S", "t", "all", 1)
        self.assertEqual(raised.exception.identifier, "EMBEDDING_FAILED")
        self.assertIn("HTTP 401", raised.exception.detail)
        self.assertNotIn("secret", raised.exception.detail)

    def test_a_tool_error_without_an_identifier(self):
        error = {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {"code": -32603, "message": "internal"},
        }
        client, _ = self.client([INIT, ACK, (error, {})])
        with self.assertRaises(docdb_client.ToolError) as raised:
            client.query("K", "S", "t", "all", 1)
        self.assertIsNone(raised.exception.identifier)
        self.assertEqual(raised.exception.detail, "ToolError: JSON-RPC -32603")

    def test_is_error_results_are_tool_errors_without_an_identifier(self):
        reply = (
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "boom"}],
                },
            },
            {},
        )
        client, _ = self.client([INIT, ACK, reply])
        with self.assertRaises(docdb_client.ToolError) as raised:
            client.query("K", "S", "t", "all", 1)
        self.assertIsNone(raised.exception.identifier)

    def test_text_content_is_parsed_when_there_is_no_structured_content(self):
        reply = (
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {"content": [{"type": "text", "text": '{"job_id": "J"}'}]},
            },
            {},
        )
        client, _ = self.client([INIT, ACK, reply])
        self.assertEqual(client.sync_documents("K", "S", []), {"job_id": "J"})

    def test_an_expired_session_is_re_established_once(self):
        expired = docdb_client.HttpError(404, "", "u")
        client, transport = self.client(
            [INIT, ACK, expired, INIT, ACK, tool_result({"results": []})]
        )
        self.assertEqual(client.query("K", "S", "t", "all", 1), {"results": []})
        methods = [c[1]["method"] for c in transport.calls]
        self.assertEqual(methods.count("initialize"), 2)

    def test_other_http_errors_are_not_retried(self):
        client, transport = self.client(
            [INIT, ACK, docdb_client.HttpError(500, "body", "u")]
        )
        with self.assertRaises(docdb_client.HttpError) as raised:
            client.query("K", "S", "t", "all", 1)
        self.assertNotIn("body", raised.exception.detail)
        self.assertEqual(len(transport.calls), 3)

    def test_transport_errors_propagate_as_connection_failures(self):
        client, _ = self.client([docdb_client.TransportError("x")])
        self.assertRaises(docdb_client.TransportError, client.initialize)


if __name__ == "__main__":
    unittest.main()
