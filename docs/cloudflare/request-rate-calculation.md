# Request rate calculation (snapshot)

> **Canonical:** https://developers.cloudflare.com/waf/rate-limiting-rules/request-rate/  
> **Snapshot date:** 2026-06-23

## How counters work

Cloudflare tracks request rates by maintaining separate counters for each unique combination of values in a rule's **characteristics**.

**Example:** A rule with characteristics `IP` + header `x-api-key` creates separate counters per (IP, key) pair.

## Per-data-center scope

- Counters are **not** global across the entire Cloudflare network.
- Each data center maintains its own counters (except DCs in the same geographical location, which may share counters).
- Every rate limiting rule includes `cf.colo.id` as a mandatory characteristic behind the scenes.

## Response-based counting

Some rules increment counters only when a **counting expression** matches after the response — e.g. only failed login attempts (`401`/`403`). Other rules count every matching request.

## Complexity-based rate limiting (Enterprise)

Enterprise customers can rate-limit by a **complexity score** returned in a response header from the origin, instead of raw request count.

## Implications for scrapers

1. **Same IP = same counter** when IP is a characteristic (typical for anti-scraping rules).
2. Rotating User-Agent or browser profile **without changing IP** may not help.
3. Distributed traffic across many egress IPs can keep per-DC rates lower — but that is not an excuse to scrape aggressively from one IP.
4. When blocked, mitigation often applies for the full **duration** window even if you slow down immediately afterward.
