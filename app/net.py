import httpx
UA = {"User-Agent": "Mozilla/5.0 (compatible; leadradar/0.2; personal lead research)"}
# One pooled client for everything: connection reuse is a big part of the speed.
http = httpx.AsyncClient(timeout=15, headers=UA, follow_redirects=True,
                         limits=httpx.Limits(max_connections=40, max_keepalive_connections=20))
