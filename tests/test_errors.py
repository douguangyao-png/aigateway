import json

from errors import error_response


def test_error_response_shape():
    resp = error_response("bad model", "invalid_request_error", 400)
    assert resp.status_code == 400
    body = json.loads(resp.body)
    assert body == {
        "error": {"message": "bad model", "type": "invalid_request_error"}
    }


def test_error_response_500():
    resp = error_response("oops", "server_error", 500)
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["error"]["type"] == "server_error"
