import httpx

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
# One pooled client for everything: connection reuse is a big part of the speed.
http = httpx.AsyncClient(
    timeout=15,
    headers=UA,
    follow_redirects=True,
    limits=httpx.Limits(max_connections=50, max_keepalive_connections=25),
)
