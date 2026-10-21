"""Inspect the downloaded OPPO script with mock responses; never sends account requests."""

import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch


def load_script(path: Path):
    """Load function definitions without executing the script main entrypoint."""
    spec = importlib.util.spec_from_file_location("oppo_review_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sign_fields(body: dict) -> str:
    """Reproduce public frontend signing only to compare locally generated request bodies."""
    fields = []
    for key, value in body.items():
        if key == "sign" or value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        fields.append(f"{key}={value}")
    data = "&".join(sorted(fields)) + "&secret=b3WVZrTH4IpFqdneyWxjNg=="
    return hashlib.md5(data.encode()).hexdigest()


def main():
    """Capture requests and demonstrate invalid reuse and misleading reward reporting."""
    parser = argparse.ArgumentParser()
    parser.add_argument("script", type=Path)
    args = parser.parse_args()
    module = load_script(args.script)
    account = {"token": "TEST_TOKEN", "sign": "captured-sign", "timestamp": "1792580000000",
               "nonce": "1792580000000", "guid": "test", "duid": "test", "ouid": "test"}
    session = Mock()
    session.post.return_value.json.return_value = {"success": True, "data": {"ok": True}}
    headers = module.build_headers(account, int(account["timestamp"]))
    module.api_query_home(session, headers, account)
    module.api_report_event(session, headers, account, 100, [{"id": "resource", "type": "APP"}])
    module.api_grant_award(session, headers, account, 100, "record")
    requests = [call.kwargs["json"] for call in session.post.call_args_list]
    assert len({body["sign"] for body in requests}) == 1
    assert len({sign_fields(body) for body in requests}) == 3
    print("All three endpoints reuse one captured sign; official per-body signatures differ.")

    # The report call is accepted, but it explicitly says the task is still RUNNING.
    home = {"taskWallData": {"taskInfos": [{"id": 100, "mainTitle": "test task", "taskType": "APP_AD",
            "taskStatus": "INIT", "taskActionStatus": "RUNNING",
            "completeConditions": [{"eventId": "START_EVENT"}],
            "taskFeature": {"resourceInfoList": [{"id": "r", "type": "APP", "name": "test"}]}}]}}
    with patch.object(module.time, "sleep"), patch.object(module.requests, "Session", return_value=Mock()), \
         patch.object(module, "api_query_home", return_value=home), \
         patch.object(module, "api_report_event", return_value={"taskActionStatus": "RUNNING", "taskRecordId": "r"}), \
         patch.object(module, "api_grant_award") as grant, contextlib.redirect_stdout(io.StringIO()):
        result = module.run_account(account, 1)
        grant.assert_not_called()
    assert "成功: 0" in result and "跳过: 1" in result
    print("Accepted report with RUNNING state produces zero completed tasks and zero rewards.")

    # Even a nonempty award response with no credited amount is reported as success.
    with patch.object(module.time, "sleep"), patch.object(module.requests, "Session", return_value=Mock()), \
         patch.object(module, "api_query_home", return_value=home), \
         patch.object(module, "api_report_event", return_value={"taskActionStatus": "WAIT_REWARD", "taskRecordId": "r"}), \
         patch.object(module, "api_grant_award", return_value={"taskActionStatus": "RUNNING"}), \
         contextlib.redirect_stdout(io.StringIO()):
        result = module.run_account(account, 1)
    assert "成功: 1" in result and "本次获得碎片: 0" in result
    print("A nonempty award payload without coinAmount is incorrectly counted as success with zero reward.")
    print("No live account requests were sent.")


if __name__ == "__main__":
    main()
