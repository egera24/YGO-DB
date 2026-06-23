# Error 429 (snapshot)

> **Canonical:** https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-429/  
> **Snapshot date:** 2026-06-23

## 429 Too Many Requests

The `429 Too Many Requests` status code indicates that the client has sent too many requests in a specified amount of time, as determined by the server's rate-limiting rules. The server may include a `Retry-After` header in the response to specify when the client can try again.

For more details, refer to [RFC 6585](https://tools.ietf.org/html/rfc6585).

### Common use cases

Servers use this status code to prevent excessive API requests from overloading the system. For example, a client making repeated API calls within a short time frame may trigger a 429 response. Websites or services may impose rate limits to manage traffic spikes or prevent abuse, temporarily blocking excessive requests from users.

### Cloudflare-specific information

#### Website end users

Cloudflare will generate a `429` response when a request is being [rate limited](https://www.cloudflare.com/rate-limiting/). If visitors to your site encounter this error, it will be visible in the Rate Limiting Analytics dashboard.

#### Related Cloudflare visitor error

**Error 1015** — “You are being rate limited” — is the HTML error page shown when a rate-limiting rule blocks traffic. It is not a separate HTTP status code in all cases; treat it the same as a severe 429 and honor `Retry-After` when present.

### Implications for Cardmarket scraping

- Always read and respect the `Retry-After` response header.
- Do not retry immediately in a tight loop; exponential backoff is required when the header is absent.
- A `Retry-After` of 3600 means your IP is banned for about an hour — stop scraping and resume later with `--resume`.
