"""[doc-db]の利用の可否を確定する（接続の確認 → その場での起動 → 期限付きの再接続）。

DES-011 §2.2、REQ-006 FR-027・AC-047（D-071）を実装する。入口 script ではないので、PEP 723 とロックは持たない。
`ensure_available()` を 1 回呼び、返った `Availability` の `status` だけで次を決める。

| `status`      | 意味                                           | 呼び出し側の動作                             |
| ------------- | ---------------------------------------------- | -------------------------------------------- |
| `available`   | MCP のセッションを確立した（`client` を持つ）  | その client で操作する                       |
| `unavailable` | 起動しても接続できなかった                     | 接続できない (a) として[ToC]へ切り替える     |

## 判定の根拠は MCP の `initialize` の成否だけである

プロセスの有無・ポートの待受は、根拠にしない。複数の呼び出しが同時に[doc-db]を起動すると、後から起動した
プロセスは、稼働中として自ら終了しうる。プロセスの生死を根拠にすると、実際には接続できる[doc-db]を、使えない
と誤判定する。自分の起動したプロセスが終了していても、接続できれば使える。

## 起動（要件 FR-027）

接続できないとき、実行ファイル `doc-db` を実行ファイルの検索パスから解決し、新しいセッションで、引数なしで起動する。
標準入力・標準出力・標準エラーは切り離して破棄する（起動のログを出力に混ぜない。doc-link はログのファイルを作らない）。
引数なしにするのは、ポートとログの出力先を[doc-db]自身の設定に任せるためである。起動したプロセスは、停止・再起動・
監視をしない。OS の自動起動・サービスへの登録もしない。環境変数は、呼び出し元から引き継ぐ（doc-link は読まない）。
起動の直後は待受の前なので、期限内に一定の間隔で `initialize` を繰り返す。無期限には再試行しない。

## 原因（`cause`。通知の「原因」の分類。固定の語句で、利用者向けの出力に載せてよい）

| `cause`              | 意味                                                                                  |
| -------------------- | ------------------------------------------------------------------------------------- |
| `config_unreadable`  | [doc-db]の設定ファイルから `port` を得られない。接続も起動も試みない                  |
| `executable_missing` | 接続できず、実行ファイル `doc-db` が検索パスに無い（未導入）                          |
| `spawn_failed`       | 実行ファイルを起動できなかった                                                        |
| `exited_early`       | 起動したプロセスが、接続の前に終了した。1 回だけ再接続を試した後も接続できなかった    |
| `reconnect_failed`   | 起動したが、期限内に接続できなかった                                                  |

情報保護: 例外の文言を載せない。載せるのは、失敗の分類・終了コード・HTTP の状態コード・URL だけである。

## テスト境界

`which`・`spawn`・`sleep`・`now`・`client_factory` は引数で差し替えられる。実行ファイル・実プロセス・実サーバー・
実時間に依存せずに検証できる。
"""

import shutil
import subprocess
import time

import docdb_client

#: 実行ファイル名
DOCDB_EXECUTABLE = "doc-db"

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

#: 起動の試行（結果の `startup`）
STARTUP_NOT_ATTEMPTED = "not_attempted"  # 最初の接続で成功した。起動を試みていない
STARTUP_SUCCEEDED = "succeeded"  # 起動して、接続できた
STARTUP_FAILED = "failed"  # 起動を試みた（または試みられなかった）が、接続できなかった

CAUSE_CONFIG_UNREADABLE = "config_unreadable"
CAUSE_EXECUTABLE_MISSING = "executable_missing"
CAUSE_SPAWN_FAILED = "spawn_failed"
CAUSE_EXITED_EARLY = "exited_early"
CAUSE_RECONNECT_FAILED = "reconnect_failed"

#: 再接続の期限と間隔（秒）。TBD: 実測で決める値の暫定
RECONNECT_DEADLINE_SECONDS = 10
RECONNECT_INTERVAL_SECONDS = 0.25


class Availability:
    """[doc-db]の利用の可否の確定結果。`unavailable` のとき `cause`・`detail` を持ち、`available` のとき `client` を持つ。"""

    def __init__(
        self,
        status,
        startup,
        cause=None,
        detail=None,
        client=None,
        port=None,
    ):
        self.status = status
        self.startup = startup
        self.cause = cause
        self.detail = detail
        self.client = client
        self.port = port

    @property
    def available(self) -> bool:
        return self.status == STATUS_AVAILABLE

    def __repr__(self) -> str:
        return (
            f"Availability(status={self.status!r}, startup={self.startup!r}, "
            f"cause={self.cause!r})"
        )


def spawn_server(executable: str) -> subprocess.Popen:
    """[doc-db]を新しいセッションで起動し、標準入出力を切り離す。"""
    return subprocess.Popen(
        [executable],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def probe(client_factory, timeout):
    """`initialize` を 1 回試み、`(Client または None, 失敗の分類または None)` を返す。

    成功した Client は、そのまま使う（セッションを捨てて再接続しない）。失敗の分類は、例外の文言を含まない。
    """
    client = client_factory(timeout)
    try:
        client.initialize()
    except docdb_client.DocDbClientError as exc:
        return None, exc.detail
    return client, None


def ensure_available(
    *,
    config_path=None,
    client_factory=None,
    which=shutil.which,
    spawn=spawn_server,
    sleep=time.sleep,
    now=time.monotonic,
    probe_timeout=docdb_client.PROBE_TIMEOUT_SECONDS,
    deadline=RECONNECT_DEADLINE_SECONDS,
    interval=RECONNECT_INTERVAL_SECONDS,
    transport=None,
) -> Availability:
    """接続の確認 → 実行ファイルの解決 → 起動 → 期限付きの再接続を、この順に行う。"""
    try:
        port = docdb_client.read_port(config_path)
    except docdb_client.PortUnavailable as exc:
        return Availability(
            STATUS_UNAVAILABLE,
            STARTUP_FAILED,
            CAUSE_CONFIG_UNREADABLE,
            exc.detail,
        )

    if client_factory is None:
        kwargs = {} if transport is None else {"transport": transport}

        def client_factory(timeout):
            return docdb_client.Client(port, timeout=timeout, **kwargs)

    def available(startup, client):
        return Availability(
            STATUS_AVAILABLE,
            startup,
            client=client,
            port=port,
        )

    def unavailable(cause, detail):
        return Availability(
            STATUS_UNAVAILABLE, STARTUP_FAILED, cause, detail, port=port
        )

    client, detail = probe(client_factory, probe_timeout)
    if client is not None:
        return available(STARTUP_NOT_ATTEMPTED, client)

    executable = which(DOCDB_EXECUTABLE)
    if not executable:
        return unavailable(
            CAUSE_EXECUTABLE_MISSING,
            f"実行ファイル {DOCDB_EXECUTABLE} が検索パスに無い（接続も失敗した: {detail}）",
        )
    try:
        process = spawn(executable)
    except OSError as exc:
        return unavailable(
            CAUSE_SPAWN_FAILED,
            f"{DOCDB_EXECUTABLE} を起動できなかった（{type(exc).__name__}）",
        )

    start = now()
    while True:
        client, detail = probe(client_factory, probe_timeout)
        if client is not None:
            return available(STARTUP_SUCCEEDED, client)
        exit_code = process.poll()
        remaining = deadline - (now() - start)
        if exit_code is not None:
            # 別の呼び出しが先に起動していて、そちらの待受が僅かに遅れることがある。1 回だけ再接続する。
            if remaining > 0:
                sleep(min(interval, remaining))
            client, detail = probe(client_factory, probe_timeout)
            if client is not None:
                return available(STARTUP_SUCCEEDED, client)
            return unavailable(
                CAUSE_EXITED_EARLY,
                f"起動した {DOCDB_EXECUTABLE} のプロセスが、接続の前に終了した"
                f"（終了コード {exit_code}。接続の失敗: {detail}。OpenAI の認証情報が無いときも、"
                f"この形になる。{DOCDB_EXECUTABLE} のログで確認する）",
            )
        if remaining <= 0:
            return unavailable(
                CAUSE_RECONNECT_FAILED,
                f"{DOCDB_EXECUTABLE} を起動したが、{deadline} 秒以内に接続できなかった"
                f"（接続の失敗: {detail}）",
            )
        sleep(min(interval, remaining))
