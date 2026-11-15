# Testing

`alphaapi.Client` runs your application on an ephemeral loopback port in a
background thread. Requests go through the real Rust/hyper stack, so routing,
middleware, cookies, and streaming behave the same as in production.

```python
from alphaapi import Client

def test_index(app):
    with Client(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"ok": True}
```

`Application.test_client()` is a small convenience:

```python
with app.test_client() as client:
    client.get("/health/")
```

## Requests

```python
client.get("/items/", headers={"x-token": "abc"})
client.post("/items/", json={"name": "pen"})
client.post("/login/", data={"username": "sam", "password": "secret"})
client.put("/items/1/", body=b"raw")
client.patch("/items/1/", json={"name": "ink"})
client.delete("/items/1/")
client.head("/static/app.css")
client.options("/items/")
```

`json=` sets the JSON content type and serializes the value. `data=` sends
URL-encoded form fields. `body=` sends raw bytes or a string. Explicit
`headers=` are merged with the generated content type.

## Cookies

The client keeps a cookie jar across requests and updates it from `Set-Cookie`
headers, including deletions. Pass `cookies=` to add request-specific cookies.

```python
with Client(app) as client:
    client.get("/login/")             # stores the session cookie
    assert client.get("/whoami/").json()["authenticated"] is True
```

## Responses

`ClientResponse` exposes:

| Attribute / method | Meaning |
| --- | --- |
| `status_code` | HTTP status |
| `headers` | Lowercase header mapping |
| `content` | Raw body bytes |
| `text` | Body decoded as UTF-8 |
| `json()` | Parse the body as JSON |

Responses also unpack as `status, headers, body`.

## Lifecycle

A client starts the server once and reuses it. Use it as a context manager, or
call `close()` yourself. Each `Client` gets its own port and thread, so tests can
run multiple clients or servers.

## Reference

::: alphaapi.testing.Client

::: alphaapi.testing.ClientResponse
